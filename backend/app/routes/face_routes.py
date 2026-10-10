import json
import time

import cv2
import numpy as np
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.attendance import AttendanceSession
from app.models.face_embedding import FaceEmbedding, FaceEnrollment
from app.models.person import Person
from app.schemas.attendance_schema import AttendanceMark
from app.serializers import attendance_record_data, face_enrollment_data, person_data
from app.services.attendance_service import find_today_record, mark_attendance
from app.services.face_service import ENROLLMENT_STEPS, build_gallery, detect_faces, embed_faces, identify, judge_liveness, locate_faces, model_label, run_models, unit_rows, usable_vector
from app.services.quality_service import MESSAGES, check_pose, check_quality, scan_problem
from app.services.tracking_service import assign_tracks, challenge_entry, observe, progress, track_score, verify
from app.utils.image_utils import decode_base64_image, decode_image_bytes
from app.utils import timing
from app.utils.scan_log import log_decision
from app.utils.time_utils import today_local

router = APIRouter(prefix="/face", tags=["Face"])
# Faces smaller than this (pixels) give unreliable embeddings, so they are not matched.
MIN_FACE_SIZE = 50
GALLERY_TTL_SECONDS = 30
SESSION_TTL_SECONDS = 5
gallery_cache = {}
session_cache = {}
marked_today = {}
# Scanner frames being worked on right now. Past this many, a frame is answered "busy" at once
# instead of joining a queue that the models could never catch up with.
MAX_SCANS_IN_FLIGHT = 4
scans_in_flight = 0
# An enrollment in progress lives here, per person, until all its poses are captured. Only then is
# anything written, so a cancelled or failed enrollment leaves the stored faces exactly as they were.
pending_enrollments = {}
# The full, guided enrollment. A quick enrollment captures the first few of these (see enrollment_steps).
REQUIRED_STEPS = ENROLLMENT_STEPS[:5]
# A pose is taken from this many good frames in a row, and the best of them is kept.
CANDIDATES_PER_STEP = settings.face_enroll_burst_frames
CANDIDATE_GAP_SECONDS = 4
# Two frames closer together than this are the same picture twice, so the second is not a new candidate.
CANDIDATE_MIN_GAP_SECONDS = 0.2
# An enrollment nobody has sent a frame to for this long is over. Nothing was saved for it.
ENROLLMENT_IDLE_SECONDS = 180
INSTRUCTIONS = {
    "front": "Look straight",
    "left": "Turn your head slightly to your left",
    "right": "Turn your head slightly to your right",
    "close": "Move face closer",
    "far": "Move face backward",
    "with_specs": "Wear spectacles and look straight",
    None: "Enrollment completed",
}


def clock():
    return time.monotonic()


async def use_models(function, *args):
    # The models are slow enough to stall every other request if they ran on the event loop.
    return await run_in_threadpool(run_models, function, *args)


async def read_face_payload(request: Request):
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        with timing.stage("read"):
            form = await request.form()
            file = form.get("image") or form.get("file")
            raw = await file.read() if file is not None else None
        with timing.stage("decode"):
            image = decode_image_bytes(raw) if raw is not None else decode_base64_image(str(form.get("image_base64") or ""))
        # What the browser measured for this frame and for the answer to its previous one, so the
        # time spent outside this server (camera, network) can be told apart from the time in it.
        timing.note(upload_bytes=len(raw) if raw is not None else None, client_capture_ms=client_ms(form.get("client_capture_ms")), client_roundtrip_ms=client_ms(form.get("client_roundtrip_ms")))
        return {
            "person_id": int(form.get("person_id")) if form.get("person_id") else None,
            "current_step": str(form.get("current_step") or "front"),
            "has_specs": str(form.get("has_specs", "false")).lower() == "true",
            "session_id": int(form.get("session_id")) if form.get("session_id") else None,
            "course_id": int(form.get("course_id")) if form.get("course_id") else None,
            "batch_id": int(form.get("batch_id")) if form.get("batch_id") else None,
            "device_name": form.get("device_name"),
            "scanner_id": form.get("scanner_id"),
            "image": image,
        }
    with timing.stage("read"):
        body = await request.json()
    with timing.stage("decode"):
        image = decode_base64_image(body.get("image_base64") or "")
    return {
        "person_id": body.get("person_id"),
        "current_step": body.get("current_step", "front"),
        "has_specs": bool(body.get("has_specs", False)),
        "session_id": body.get("session_id"),
        "course_id": body.get("course_id"),
        "batch_id": body.get("batch_id"),
        "device_name": body.get("device_name"),
        "scanner_id": body.get("scanner_id"),
        "image": image,
    }


def client_ms(value):
    # A duration reported by the browser. Only ever logged, so anything that is not a sane number is dropped.
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, 1) if 0 <= value < 600_000 else None


@router.get("/enrollment/users")
def enrollment_users(course_id: int, batch_id: int, db: Session = Depends(get_db)):
    rows = db.query(Person).filter(
        Person.course_id == course_id,
        Person.batch_id == batch_id,
    ).order_by(Person.full_name.asc()).all()
    return {"success": True, "message": "Enrollment users fetched", "data": [person_data(row) for row in rows]}


def latest_enrollment(db, person_id):
    return db.query(FaceEnrollment).filter(FaceEnrollment.person_id == person_id).order_by(FaceEnrollment.id.desc()).first()


def active_faces(db, person_id):
    return db.query(FaceEmbedding).filter(FaceEmbedding.person_id == person_id, FaceEmbedding.is_active == True).count()


def enrollment_steps(mode):
    # The poses an enrollment of this kind captures, in order.
    #   "guided": all five. "quick": the ones named in FACE_ENROLL_QUICK_STEPS, front always first.
    # Measured with scripts/compare_enrollment.py: front + left + right recognizes about as well as
    # a five-photo enrollment (93% against 96% of attempts marked); close and far are the front view
    # again at another size and added nothing; front alone is clearly weaker (67%).
    mode = (mode or settings.face_enroll_mode).lower()
    if mode not in ("quick", "guided"):
        raise HTTPException(400, "Enrollment mode must be 'quick' or 'guided'.")
    if mode == "guided":
        return mode, list(REQUIRED_STEPS)
    wanted = set(settings.face_enroll_quick_steps) | {"front"}
    return mode, [step for step in REQUIRED_STEPS if step in wanted]


@router.post("/enrollment/start/{person_id}")
def start_enrollment(person_id: int, db: Session = Depends(get_db), mode: str | None = None):
    mode, steps = enrollment_steps(mode if isinstance(mode, str) else None)
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    print("start enrollment person_id", person_id, mode, steps)
    # The faces already stored stay active until the new set is complete (see save_enrollment),
    # so someone who re-enrolls and gives up half way is still recognized.
    if person.face_enrollment_status != "completed":
        person.face_enrollment_status = "in_progress"
    enrollment = latest_enrollment(db, person_id)
    if enrollment and enrollment.enrollment_status != "completed":
        enrollment.enrollment_status = "in_progress"
        enrollment.current_step = "front"
        enrollment.total_steps = len(steps)
        enrollment.completed_steps = 0
        enrollment.quality_score = None
        enrollment.has_specs_reference = False
        enrollment.started_at = datetime.utcnow()
        enrollment.completed_at = None
    else:
        # A finished enrollment keeps its own record. Enrolling again is a new attempt beside it,
        # which is simply removed if it is cancelled.
        enrollment = FaceEnrollment(
            person_id=person_id,
            enrollment_status="in_progress",
            current_step="front",
            total_steps=len(steps),
            completed_steps=0,
            started_at=datetime.utcnow(),
        )
        db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    pending_enrollments[person_id] = {"mode": mode, "steps": steps, "step": steps[0], "samples": [], "candidates": [], "touched": clock(), "busy": False}
    data = dict(face_enrollment_data(enrollment), mode=mode, steps=steps, instruction=INSTRUCTIONS[steps[0]], frames_per_step=CANDIDATES_PER_STEP)
    return {"success": True, "message": "Face enrollment started", "data": data}


def abandon_enrollment(db, person):
    # Puts the records back to what the stored faces say, after a cancelled or refused enrollment.
    pending_enrollments.pop(person.id, None)
    enrollment = latest_enrollment(db, person.id)
    if enrollment and enrollment.enrollment_status == "in_progress":
        db.delete(enrollment)
    if person.face_enrollment_status != "completed":
        person.face_enrollment_status = "not_started"
    db.commit()


@router.post("/enrollment/cancel/{person_id}")
def cancel_enrollment(person_id: int, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    abandon_enrollment(db, person)
    return {"success": True, "message": "Enrollment cancelled. Nothing was saved.", "data": face_enrollment_data(latest_enrollment(db, person_id))}


def valid_embedding(embedding):
    return usable_vector(embedding, settings.face_embedding_size)


def similarity(first, second):
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    return float(first @ second / (np.linalg.norm(first) * np.linalg.norm(second)))


def moved(previous, box):
    # True when the face shifted or changed size between two frames, i.e. the person is not holding still.
    px, py, pw, ph = previous
    x, y, w, h = box
    shift = max(abs((x + w / 2) - (px + pw / 2)), abs((y + h / 2) - (py + ph / 2)))
    return shift > 0.15 * pw or abs(w - pw) > 0.15 * pw


@router.post("/enrollment/frame")
async def enrollment_frame(request: Request, db: Session = Depends(get_db)):
    timer = timing.start("enroll")
    outcome = "error"
    try:
        result = await handle_enrollment_frame(request, db)
        outcome = "accepted" if result.get("accepted") else "holding" if result.get("holding") else str(result.get("quality_status") or "refused")
        return result
    except HTTPException as exc:
        outcome = f"http_{exc.status_code}"
        raise
    finally:
        timing.finish(timer, outcome)


async def handle_enrollment_frame(request, db):
    payload = await read_face_payload(request)
    step = payload["current_step"]
    print("received person_id", payload["person_id"], "current_step", step)
    person = db.get(Person, payload["person_id"]) if payload["person_id"] else None
    if not person:
        raise HTTPException(404, "Person not found")
    state = pending_enrollments.get(person.id)
    if state and clock() - state["touched"] > ENROLLMENT_IDLE_SECONDS:
        abandon_enrollment(db, person)
        raise HTTPException(409, "Enrollment timed out. Press Start Enrollment.")
    enrollment = latest_enrollment(db, person.id)
    if not state or not enrollment or enrollment.enrollment_status != "in_progress":
        raise HTTPException(409, "Enrollment is not active. Press Start Enrollment.")
    # The server decides which pose comes next; a frame for any other step is never stored.
    if step != state["step"]:
        raise HTTPException(409, f"Expected the {state['step']} step, not {step}. Press Start Enrollment again.")
    if state["busy"]:
        # A second camera sending frames for the same student: its frames wait their turn, they are
        # never mixed into the capture that is being checked.
        return reject(MESSAGES["busy"], step, "busy", int(len(state["samples"]) / len(state["steps"]) * 100))
    state["busy"] = True
    state["touched"] = clock()
    try:
        return await capture_pose(db, person, enrollment, state, payload)
    finally:
        state["busy"] = False


async def capture_pose(db, person, enrollment, state, payload):
    step, steps = state["step"], state["steps"]
    progress_now = int(len(state["samples"]) / len(steps) * 100)

    def refuse(message, quality_status="bad"):
        # One bad frame restarts the run of good frames for this pose.
        state["candidates"] = []
        return reject(message, step, quality_status, progress_now)

    image = payload["image"]
    if image is None:
        return refuse("Invalid image")

    # The cheap half first: where is the face, and is this frame worth keeping at all? Most frames
    # of an enrollment are not (the student is still moving into place), and those never reach the
    # embedding model, which is the most expensive step by far.
    try:
        faces = await use_models(locate_faces, image)
    except RuntimeError as exc:
        return refuse(str(exc), "embedding_failed")

    timing.note(width=int(image.shape[1]), height=int(image.shape[0]), faces=len(faces), step=step)
    with timing.stage("quality"):
        quality = check_quality(image, [face["box"] for face in faces], reject_sunglasses=True)
    print("quality result", quality)
    if not quality["ok"]:
        return refuse(quality["warning"], quality["quality_status"])
    face = faces[0]
    if face["detection_confidence"] < settings.face_enroll_detection_confidence:
        return refuse(MESSAGES["unclear"], "unclear")

    front = state["samples"][0] if state["samples"] else None
    pose_ok, pose_warning = check_pose(image, quality, step, face["turn"], front["face_ratio"] if front else None)
    print("pose result", {"ok": pose_ok, "warning": pose_warning})
    if not pose_ok:
        return refuse(pose_warning, "pose")

    def holding(count):
        return {
            "success": True,
            "accepted": False,
            "holding": True,
            "message": MESSAGES["hold"],
            "current_step": step,
            "next_step": step,
            "instruction": INSTRUCTIONS.get(step, "Look straight"),
            "quality_status": "good",
            "progress_percentage": progress_now,
            "candidates": count,
            "candidates_needed": CANDIDATES_PER_STEP,
            "warning": None,
            "completed": False,
        }

    now = clock()
    candidates = state["candidates"]
    if candidates and (now - candidates[-1]["time"] > CANDIDATE_GAP_SECONDS or moved(candidates[0]["box"], face["box"]) or moved(candidates[-1]["box"], face["box"])):
        # Not held still (or the run went stale): this frame starts a new run.
        candidates = []
    if candidates and now - candidates[-1]["time"] < CANDIDATE_MIN_GAP_SECONDS:
        # The same picture again. Known from the clock alone, so the models are not run for it.
        return holding(len(candidates))

    # The frame is worth keeping. Only now: is it a real face, and what is its vector?
    try:
        liveness, liveness_score = (await use_models(judge_liveness, image, [tuple(face["box"])]))[0]
    except RuntimeError as exc:
        return refuse(str(exc), "embedding_failed")
    if liveness == "spoof":
        return refuse(MESSAGES["spoof"], "spoof")
    if liveness != "live":
        # A reference face is only stored from a frame the liveness model is sure about.
        return refuse(MESSAGES["liveness_uncertain"], "liveness_uncertain")
    try:
        embedding = (await use_models(embed_faces, image, [face]))[0].get("embedding")
    except RuntimeError as exc:
        return refuse(str(exc), "embedding_failed")
    if not valid_embedding(embedding):
        return refuse(f"Face model returned an unusable vector (expected {settings.face_embedding_size} values).", "embedding_failed")
    same_as_front = similarity(embedding, front["embedding"]) if front else None
    if front and same_as_front < settings.face_enroll_same_person:
        return refuse(MESSAGES["mismatch"], "mismatch")
    # Every frame of one run must show the same face, the front pose included: it has nothing
    # earlier to be compared with.
    if candidates and similarity(embedding, candidates[0]["embedding"]) < settings.face_enroll_same_person:
        return refuse(MESSAGES["inconsistent"], "mismatch")
    candidates.append({
        "time": now,
        "box": face["box"],
        "pose_type": step,
        "embedding": embedding,
        "quality_score": quality["quality_score"],
        "brightness_score": quality["brightness_score"],
        "blur_score": quality["blur_score"],
        "focus_score": quality["focus_score"],
        "face_ratio": quality["face_ratio"],
        "face_angle": face["turn"],
        "detection_confidence": face["detection_confidence"],
        "liveness_score": liveness_score,
        "frame_size": [int(image.shape[1]), int(image.shape[0])],
        "same_as_front": same_as_front,
        "has_specs": payload["has_specs"],
    })
    state["candidates"] = candidates
    if len(candidates) < CANDIDATES_PER_STEP:
        return holding(len(candidates))

    sample = max(candidates, key=lambda item: item["quality_score"])
    sample["candidates"] = len(candidates)
    sample["run_similarity"] = min(similarity(sample["embedding"], item["embedding"]) for item in candidates)
    state["samples"].append(sample)
    state["candidates"] = []
    completed_steps = len(state["samples"])
    completed = completed_steps == len(steps)
    next_step = None if completed else steps[completed_steps]
    if completed:
        try:
            with timing.stage("write"):
                save_enrollment(db, person, enrollment, state["samples"], steps, state["mode"])
        except HTTPException:
            # Refused for good (poses missing or invalid, or this face belongs to someone else).
            db.rollback()
            abandon_enrollment(db, person)
            raise
        except Exception as exc:
            # The database let us down. Nothing was written, the old faces are untouched, and the
            # poses captured so far are kept: only this last pose is taken again.
            db.rollback()
            state["samples"].pop()
            print("enrollment save failed:", exc)
            return reject(MESSAGES["save_failed"], step, "save_failed", progress_now)
        pending_enrollments.pop(person.id, None)
    else:
        state["step"] = next_step
        enrollment.current_step = next_step
        enrollment.completed_steps = completed_steps
        enrollment.quality_score = sample["quality_score"]
        db.commit()
    print("captured", step, "next_step", next_step, "saved", completed)
    return {
        "success": True,
        "accepted": True,
        "message": f"{step.replace('_', ' ').title()} face captured successfully",
        "current_step": step,
        "next_step": next_step,
        "instruction": INSTRUCTIONS[next_step],
        "quality_status": "good",
        "progress_percentage": int((completed_steps / len(steps)) * 100),
        "warning": MESSAGES["transparent_specs"] if payload["has_specs"] else None,
        "completed": completed,
        "total_steps": len(steps),
    }


def enrolled_as_someone_else(db, person, samples):
    # The other enrolled person this finished capture looks like, or None. Compared average face to
    # average face, which is steadier than any single frame.
    if settings.face_enroll_duplicate_score > 1:
        return None
    rows = db.query(
        FaceEmbedding.person_id, FaceEmbedding.embedding_vector, Person.person_code, Person.full_name,
    ).join(Person, FaceEmbedding.person_id == Person.id).filter(
        FaceEmbedding.is_active == True,
        FaceEmbedding.model_name == model_label(),
        FaceEmbedding.person_id != person.id,
    ).all()
    others, matrix = build_gallery(rows, "centroid")
    if matrix is None:
        return None
    average = unit_rows(np.array([sample["embedding"] for sample in samples], dtype=float)).mean(axis=0)
    scores = matrix @ (average / np.linalg.norm(average))
    index = int(np.argmax(scores))
    if scores[index] < settings.face_enroll_duplicate_score:
        return None
    return others[index], float(scores[index])


def save_enrollment(db, person, enrollment, samples, steps=REQUIRED_STEPS, mode="guided"):
    # The only place enrollment faces are written: every pose of this enrollment or nothing, in one
    # transaction, and the previous set is retired in that same transaction.
    if not steps or [sample["pose_type"] for sample in samples] != list(steps) or not all(valid_embedding(sample["embedding"]) for sample in samples):
        raise HTTPException(409, "Enrollment is incomplete. Press Start Enrollment again.")
    twin = enrolled_as_someone_else(db, person, samples)
    if twin:
        other, score = twin
        log_decision(event="enrollment_refused", reason="face_enrolled_as_another_person", person_id=person.id, other_person_id=other.person_id, score=round(score, 4))
        raise HTTPException(409, f"This face is already enrolled as {other.full_name} ({other.person_code}). Nothing was saved. One face can belong to one person only.")
    db.query(FaceEmbedding).filter(FaceEmbedding.person_id == person.id, FaceEmbedding.is_active == True).update({"is_active": False})
    for sample in samples:
        db.add(FaceEmbedding(
            person_id=person.id,
            embedding_vector=json.dumps(sample["embedding"]),
            pose_type=sample["pose_type"],
            model_name=model_label(),
            quality_score=sample["quality_score"],
            brightness_score=sample["brightness_score"],
            blur_score=sample["blur_score"],
            face_angle=sample["face_angle"],
            has_specs=sample["has_specs"],
            is_active=True,
            capture_meta=json.dumps(dict(capture_meta(sample), enrollment_mode=mode, enrollment_poses=list(steps))),
        ))
    enrollment.current_step = None
    enrollment.completed_steps = len(samples)
    enrollment.quality_score = min(sample["quality_score"] for sample in samples)
    enrollment.enrollment_status = "completed"
    enrollment.completed_at = datetime.utcnow()
    person.face_enrollment_status = "completed"
    db.commit()
    gallery_cache.clear()


def capture_meta(sample):
    def rounded(value):
        return None if value is None else round(float(value), 4)

    return {
        "pipeline": model_label(),
        "detector": settings.face_detector,
        "model": settings.face_model,
        "normalization": settings.face_normalization,
        "embedding_size": len(sample["embedding"]),
        "frame_size": sample.get("frame_size"),
        "face_box": [int(value) for value in sample["box"]],
        "face_ratio": rounded(sample["face_ratio"]),
        "detection_confidence": rounded(sample.get("detection_confidence")),
        "focus": sample.get("focus_score"),
        "liveness_checked": settings.face_liveness,
        "liveness_score": rounded(sample.get("liveness_score")),
        "candidates": sample.get("candidates"),
        # Lowest similarity between the kept frame and the other frames of its run, and its
        # similarity to the front pose: how sure we are that all of it is one face.
        "run_similarity": rounded(sample.get("run_similarity")),
        "same_as_front": rounded(sample.get("same_as_front")),
    }


def reject(message, current_step, quality_status, progress):
    return {
        "success": False,
        "accepted": False,
        "message": message,
        "current_step": current_step,
        "next_step": current_step,
        "instruction": INSTRUCTIONS.get(current_step, "Look straight"),
        "quality_status": quality_status,
        "progress_percentage": progress,
        "warning": message,
        "completed": False,
    }


@router.post("/enrollment/complete/{person_id}")
def complete_enrollment(person_id: int, db: Session = Depends(get_db)):
    # Capturing the last pose completes an enrollment (save_enrollment). This only confirms it,
    # so it can never mark someone enrolled who has no stored faces.
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "Person not found")
    enrollment = latest_enrollment(db, person_id)
    # A quick enrollment stores fewer poses than a guided one; either is complete once it was saved.
    if not enrollment or enrollment.enrollment_status != "completed" or active_faces(db, person_id) < max(enrollment.completed_steps or 0, 1):
        raise HTTPException(409, "Enrollment is not finished. Capture every pose first.")
    return {"success": True, "message": "Face enrollment completed", "data": {"person_id": person_id}}


@router.get("/enrollment/status/{person_id}")
def enrollment_status(person_id: int, db: Session = Depends(get_db)):
    return {"success": True, "message": "Enrollment status fetched", "data": face_enrollment_data(latest_enrollment(db, person_id))}


@router.get("/timings")
def timings():
    # Median, p95 and p99 of the latest face requests of this process, per stage. Numbers only.
    return {"success": True, "message": "Timings fetched", "data": timing.summarize(list(timing.recent))}


def load_session(db, session_id):
    # Checked every few seconds rather than every frame; a stopped session is noticed within that time.
    # (Before a record is written the session is read again, see mark_for_session.)
    cached = session_cache.get(session_id)
    if cached and clock() - cached[0] < SESSION_TTL_SECONDS:
        return cached[1]
    row = db.get(AttendanceSession, session_id)
    session = SimpleNamespace(id=row.id, course_id=row.course_id, batch_id=row.batch_id, status=row.status) if row else None
    session_cache[session_id] = (clock(), session)
    return session


def load_gallery(db, course_id, batch_id):
    # Live video asks for the same batch several times a second, and the stored vectors are a
    # large download from a remote database, so they are kept in memory for a short while.
    key = (course_id, batch_id, model_label())
    cached = gallery_cache.get(key)
    if cached and clock() - cached[0] < GALLERY_TTL_SECONDS:
        return cached[1]
    query = db.query(
        FaceEmbedding.person_id, FaceEmbedding.embedding_vector,
        Person.person_code, Person.full_name, Person.person_type,
    ).join(Person, FaceEmbedding.person_id == Person.id).filter(
        FaceEmbedding.is_active == True,
        FaceEmbedding.model_name == model_label(),
    )
    if course_id:
        query = query.filter(Person.course_id == course_id)
    if batch_id:
        query = query.filter(Person.batch_id == batch_id)
    gallery = build_gallery(query.all())
    gallery_cache[key] = (clock(), gallery)
    return gallery


def marked_status(db, session, person_id):
    # The same face shows up in many consecutive frames, so only the first one writes a record.
    key = (session.id, person_id, today_local())
    if key not in marked_today:
        existing = find_today_record(db, person_id, session.id)
        if existing:
            marked_today[key] = existing.status
    return marked_today.get(key)


def mark_for_session(db, session, person_id, confidence, device_name):
    # Called only for a face that has passed every check. Writes the record for the session the
    # scanner is running, after making sure that session has not been stopped in the meantime.
    row = db.get(AttendanceSession, session.id)
    if not row or row.status != "active":
        session_cache.pop(session.id, None)
        return {"result": "not_marked", "attendance_status": None, "newly_marked": False, "message": "This session has been stopped. Attendance was not marked."}
    record, message = mark_attendance(db, AttendanceMark(
        session_id=session.id,
        person_id=person_id,
        confidence_score=round(confidence, 4),
        recognition_method="face_ai",
        device_name=device_name,
    ))
    if not record:
        return {"result": "not_marked", "attendance_status": None, "newly_marked": False, "message": message}
    marked_today[(session.id, person_id, today_local())] = record.status
    if message == "Already marked":
        # Another scanner wrote it a moment earlier. There is still exactly one record.
        return {"result": "already_marked", "attendance_status": record.status, "newly_marked": False}
    return {"result": "verified", "attendance_status": record.status, "newly_marked": True, "record": attendance_record_data(record)}


@router.post("/recognize")
async def recognize(request: Request, db: Session = Depends(get_db)):
    global scans_in_flight
    timer = timing.start("scan")
    outcome = "error"
    try:
        payload = await read_face_payload(request)
        image = payload["image"]
        if image is None:
            outcome = "invalid_image"
            return {"success": False, "message": "Invalid image", "details": {}}
        if scans_in_flight >= MAX_SCANS_IN_FLIGHT:
            # Said plainly instead of queueing: this frame was not looked at, nobody in it was checked.
            outcome = "busy"
            return {"success": True, "recognized": False, "status": "busy", "message": "The server is busy with earlier frames. This frame was skipped.", "faces": []}
        timing.note(in_flight=scans_in_flight + 1)
        scans_in_flight += 1
        try:
            response = await scan_frame(db, payload, image)
        finally:
            scans_in_flight -= 1
        outcome = scan_outcome(response)
        return response
    finally:
        timing.finish(timer, outcome)


def scan_outcome(response):
    # The frame's verdicts as one short word list for the timing log, e.g. "pending+unknown".
    results = sorted({str(face.get("result")) for face in response.get("faces", [])})
    return "+".join(results) if results else str(response.get("status"))


async def scan_frame(db, payload, image):
    started = clock()
    try:
        faces = await use_models(detect_faces, image)
    except RuntimeError as exc:
        return {"success": False, "recognized": False, "status": "embedding_failed", "message": str(exc)}

    height, width = image.shape[:2]
    frame = {"width": int(width), "height": int(height)}
    timing.note(width=int(width), height=int(height), faces=len(faces))

    with timing.stage("session"):
        session = load_session(db, payload["session_id"]) if payload["session_id"] else None
    course_id = session.course_id if session else payload["course_id"]
    batch_id = session.batch_id if session else payload["batch_id"]
    active = bool(session and session.status == "active")
    # Faces are followed per camera and per session: what one scanner saw never counts for another.
    scanner = (session.id if session else None, str(payload["scanner_id"] or payload["device_name"] or "default"))
    now = clock()
    tracks = assign_tracks(scanner, [face["box"] for face in faces], now)
    if not faces:
        return {"success": True, "recognized": False, "status": "no_face", "message": MESSAGES["no_face"], "frame": frame, "faces": [], "processing_ms": int((clock() - started) * 1000)}
    with timing.stage("gallery"):
        gallery = load_gallery(db, course_id, batch_id)

    # Every face is judged on its own from here on. A face that is refused at any step is finished
    # with a reason; it never stops, or lends anything to, the other faces in the frame.
    results = []
    named = {}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for face, track in zip(faces, tracks):
        x, y, w, h = face["box"]
        item = {
            "box": {"x": x, "y": y, "w": w, "h": h}, "track_id": track["id"],
            "recognized": False, "status": "unknown", "result": "unknown", "message": "Unknown face",
            "confirm_hits": 0, "confirm_needed": settings.face_confirm_frames,
        }
        results.append(item)
        if min(w, h) < MIN_FACE_SIZE:
            item.update(status="too_far", result="low_quality", message=MESSAGES["too_far"])
            continue
        # A face too dark, burnt out or smeared to trust is not matched, so it can neither be
        # named nor count towards anyone's confirmation.
        with timing.stage("quality"):
            problem = scan_problem(gray, face["box"])
        if problem:
            item.update(status=problem, result="low_quality", message=MESSAGES[problem])
            continue
        with timing.stage("match"):
            answer = identify(face["embedding"], gallery)
        item["_answer"], item["_track"], item["_turn"] = answer, track, face.get("turn")
        if answer["status"] == "matched":
            named.setdefault(answer["embedding"].person_id, []).append(item)
        elif answer["status"] == "ambiguous":
            item.update(status="ambiguous", result="ambiguous", message=MESSAGES["ambiguous"])

    # One person cannot be two faces in the same frame. The clearly stronger match keeps the name;
    # the other face is not that person. When the two are about as strong, neither is trusted.
    pending = []
    for person_id, items in named.items():
        items.sort(key=lambda entry: entry["_answer"]["confidence"], reverse=True)
        clear_winner = len(items) == 1 or items[0]["_answer"]["confidence"] - items[1]["_answer"]["confidence"] >= settings.face_match_margin
        for item in items[0 if not clear_winner else 1:]:
            item.update(status="ambiguous", result="ambiguous", message=MESSAGES["ambiguous"])
        if not clear_winner:
            continue
        item, person = items[0], items[0]["_answer"]["embedding"]
        item.update(
            recognized=True,
            status="matched",
            result="recognized",
            person_id=person.person_id,
            person_code=person.person_code,
            person_name=person.full_name,
            person_type=person.person_type,
            confidence_score=round(item["_answer"]["confidence"], 4),
            message=f"{person.full_name} recognized",
        )
        already = marked_status(db, session, person.person_id) if active else None
        if already:
            item.update(result="already_marked", attendance_status=already, newly_marked=False, message=f"{person.full_name} is already marked {already}")
        else:
            pending.append(item)

    # Liveness only runs for people who are not marked yet, which keeps a full classroom fast.
    # It runs on each of those faces separately, and each verdict is used for that face alone.
    live = []
    if pending:
        boxes = [(item["box"]["x"], item["box"]["y"], item["box"]["w"], item["box"]["h"]) for item in pending]
        try:
            live = await use_models(judge_liveness, image, boxes)
        except RuntimeError as exc:
            # No verdict is never read as "live": the frame fails and nobody in it is marked.
            return {"success": False, "recognized": False, "status": "embedding_failed", "message": str(exc)}
    alive = {id(item): verdict for item, verdict in zip(pending, live)}
    challenge = settings.face_challenge != "off"

    for item in results:
        track, answer, turn = item.pop("_track", None), item.pop("_answer", None), item.pop("_turn", None)
        if answer is None:
            # Too small or too poor to judge. It neither adds to nor ends what this face had collected.
            continue
        liveness, liveness_score = alive.get(id(item), (None, None))
        if item["result"] in ("unknown", "ambiguous"):
            # Seen clearly and not named: whatever name this face was collecting evidence for is dropped.
            observe(scanner, track, None, now=now)
        elif liveness == "spoof":
            # Liveness says nothing about who someone is, only that this is not a real face.
            if active:
                observe(scanner, track, item["person_id"], item["confidence_score"], False, now)
            item.update(recognized=False, status="spoof", result="liveness_failed", message=MESSAGES["spoof"])
        elif liveness == "uncertain":
            # Not sure it is a real face: this look counts for nothing, neither as a hit nor as an
            # answer to the challenge. It is not called a photo either, so nothing is wiped.
            item.update(recognized=False, status="liveness_uncertain", result="liveness_uncertain", message=MESSAGES["liveness_uncertain"], confirm_hits=progress(track))
        elif liveness == "live" and active:
            box = (item["box"]["x"], item["box"]["y"], item["box"]["w"], item["box"]["h"])
            state = verify(scanner, track, item["person_id"], item["confidence_score"], now, turn, box, challenge)
            name = item["person_name"]
            item.update(confirming=True, attendance_status=None, newly_marked=False, confirm_hits=progress(track))
            if state == "confirmed":
                # Identity (several looks, margin, average score), liveness on every one of those
                # looks, and the challenge answered on this same face: only now is a record written.
                item.pop("confirming")
                with timing.stage("write"):
                    marked = mark_for_session(db, session, item["person_id"], track_score(track), payload["device_name"])
                item.update(marked)
                if item["result"] == "verified":
                    item["message"] = f"{name} marked {item['attendance_status']}"
            elif state == "pending":
                item.update(result="pending", message=f"Verifying {name}. Look at the camera.")
            elif state == "straight":
                item.update(result="challenge", challenge={"action": "straight"}, message=f"{name}: look straight at the camera")
            elif state == "turn":
                direction = challenge_entry(scanner[0], item["person_id"], now)["direction"]
                item.update(result="challenge", challenge={"action": "turn", "direction": direction}, message=f"{name}: turn your head to your {direction.upper()}")
            elif state == "failed":
                item.update(confirming=False, result="challenge_failed", message=f"{name}: that was not the movement asked for. Wait a moment and follow the instruction.")
            else:
                item.update(confirming=False, result="locked", message=f"{name}: verification failed several times. Ask the teacher to mark attendance by hand.")
        if track.get("logged") != (item["result"], item.get("challenge", {}).get("action")) or item["result"] in ("verified", "not_marked"):
            # A line when a face's verdict changes, not one per frame.
            track["logged"] = (item["result"], item.get("challenge", {}).get("action"))
            log_decision(
                event="scan", session_id=scanner[0], scanner=scanner[1], track=track["id"], result=item["result"], status=item["status"],
                liveness=liveness, liveness_score=None if liveness_score is None else round(liveness_score, 4),
                turn=None if turn is None else round(turn, 4), challenge=item.get("challenge"),
                person_id=answer["embedding"].person_id if answer["embedding"] is not None else None,
                score=round(answer["confidence"], 4), runner_up_id=answer["runner_up_id"],
                runner_up_score=None if answer["runner_up_score"] is None else round(answer["runner_up_score"], 4),
                face_px=int(min(item["box"]["w"], item["box"]["h"])), hits=len(track["hits"]), faces_in_frame=len(faces),
            )

    best = max((item for item in results if item["recognized"]), key=lambda item: item["confidence_score"], default=None)
    response = {
        "success": True,
        "recognized": bool(best),
        "status": "matched" if best else "unknown",
        "message": best["message"] if best else "Unknown face",
        "frame": frame,
        "faces": results,
        "processing_ms": int((clock() - started) * 1000),
    }
    if best:
        response.update({key: best[key] for key in ("person_id", "person_code", "person_name", "person_type", "confidence_score")})
    return response
