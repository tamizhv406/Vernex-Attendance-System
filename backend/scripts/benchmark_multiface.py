"""Run the real scanner on frames with 1, 2, 5 and 10 faces and report what it did and how long it took.

    python scripts/benchmark_multiface.py DATASET

DATASET is a folder with one sub-folder of photos per person (the same layout evaluate_recognition.py
uses). A class is "enrolled" from five photos per person; another photo of each is pasted into a
camera-sized frame, several people side by side, and the frame is sent through the same code the
/face/recognize endpoint runs: detector, quality gate, embedding, matching, tracking, liveness,
confirmation and the attendance write.

Everything is written to a temporary database that is deleted afterwards. The application's own
database is never opened.

What this is and is not: the models, the code and the timings are real. The "camera frames" are
photos pasted on a grey background, shifted a few pixels from frame to frame. That measures
multi-face processing and its speed on this machine. It does not measure a real classroom camera
(motion blur, people overlapping, faces turned away, room lighting), and the liveness model's
verdict on pasted photos says nothing about how it treats real faces.
"""
import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
# Set before the app is imported, so the app's own database is never touched.
workspace = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(workspace.name) / 'benchmark.db'}"
os.environ["FACE_SCAN_LOG"] = "false"

import cv2
import numpy as np

from app.config import settings
from app.database import SessionLocal, engine
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding
from app.models.person import Person
from app.routes import face_routes
from app.schema import init_database_schema
from app.services import face_service, tracking_service
from app.utils.time_utils import today_local

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COUNTS = (1, 2, 5, 10)


class CameraClock:
    # The scanner's clock. Frames are spaced like a camera loop would space them, whatever the
    # speed of this machine, so the "observations must be half a second apart" rule behaves as live.
    now = 5000.0

    def __call__(self):
        return self.now


def main_face(image):
    faces = face_service.detect_faces(image)
    if not faces:
        return None
    height, width = image.shape[:2]
    return min(faces, key=lambda face: (face["box"][0] + face["box"][2] / 2 - width / 2) ** 2 + (face["box"][1] + face["box"][3] / 2 - height / 2) ** 2)


def enroll_class(db, dataset, args, rng):
    # Returns (session, {name: person}, {name: probe photo}, [photos of people who are not enrolled]).
    folders = sorted(path for path in dataset.iterdir() if path.is_dir())
    rich = [folder for folder in folders if len(photos_of(folder)) >= 7]
    single = [folder for folder in folders if len(photos_of(folder)) == 1]
    rng.shuffle(rich)
    rng.shuffle(single)
    course = Course(course_code="BENCH", course_name="Benchmark")
    db.add(course)
    db.commit()
    batch = CourseBatch(course_id=course.id, batch_name="Benchmark batch")
    db.add(batch)
    db.commit()
    people, probes = {}, {}
    for folder in rich:
        if len(people) == args.class_size:
            break
        photos = photos_of(folder)
        rng.shuffle(photos)
        vectors = [main_face(cv2.imread(str(path))) for path in photos[:5]]
        if any(face is None for face in vectors):
            continue
        person = Person(person_code=f"B{len(people) + 1}", full_name=folder.name, person_type="student", course_id=course.id, batch_id=batch.id, face_enrollment_status="completed")
        db.add(person)
        db.commit()
        for pose, face in zip(face_routes.REQUIRED_STEPS, vectors):
            db.add(FaceEmbedding(person_id=person.id, embedding_vector=json.dumps(face["embedding"]), pose_type=pose, model_name=face_service.model_label(), is_active=True))
        people[folder.name], probes[folder.name] = person, photos[5]
    session = AttendanceSession(session_name="Benchmark", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
    db.add(session)
    db.commit()
    return session, people, probes, [photos_of(folder)[0] for folder in single[:200]]


def photos_of(folder):
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_TYPES)


def frame_with(photos, size, shift=0):
    # A camera frame with the photos side by side (two rows from six faces up).
    # Returns the frame and the centre of each pasted photo.
    width, height = size
    columns = min(len(photos), 5)
    rows = (len(photos) + columns - 1) // columns
    cell_w, cell_h = width // columns, height // rows
    side = min(cell_w, cell_h) - 8
    frame = np.full((height, width, 3), 110, dtype=np.uint8)
    centers = []
    for index, path in enumerate(photos):
        photo = cv2.resize(cv2.imread(str(path)), (side, side), interpolation=cv2.INTER_AREA)
        x = (index % columns) * cell_w + (cell_w - side) // 2
        y = (index // columns) * cell_h + (cell_h - side) // 2
        frame[y:y + side, x:x + side] = photo
        centers.append((x + side / 2, y + side / 2, side))
    if shift:
        frame = cv2.warpAffine(frame, np.float32([[1, 0, shift], [0, 1, shift // 2]]), (width, height), borderValue=(110, 110, 110))
        centers = [(x + shift, y + shift // 2, side) for x, y, side in centers]
    return frame, centers


def face_for(centers, faces):
    # Which returned face belongs to which pasted photo: the one nearest the photo's centre. (A photo
    # can show other people in its background; they are counted as extra faces, not as the subject.)
    def offset(item, x, y):
        return max(abs(item["box"]["x"] + item["box"]["w"] / 2 - x), abs(item["box"]["y"] + item["box"]["h"] / 2 - y))

    found = []
    for x, y, side in centers:
        inside = [item for item in faces if offset(item, x, y) < side / 4]
        found.append(min(inside, key=lambda item: offset(item, x, y)) if inside else None)
    return found


def run_scenario(db, session, cast, size, args, clock):
    # cast: [(name or None for a stranger, photo)]. Sends args.frames frames and returns what happened.
    tracking_service.reset()
    face_routes.marked_today.clear()
    db.query(AttendanceRecord).delete()
    db.commit()
    timings, first, last, tracks = [], None, None, []
    for index in range(args.frames):
        frame, centers = frame_with([photo for _, photo in cast], size, shift=3 * index)
        clock.now += 0.7
        payload = {"session_id": session.id, "course_id": None, "batch_id": None, "device_name": "benchmark", "scanner_id": "benchmark"}
        started = time.perf_counter()
        answer = asyncio.run(face_routes.scan_frame(db, payload, frame))
        timings.append(time.perf_counter() - started)
        placed = face_for(centers, answer.get("faces", []))
        tracks.append([item["track_id"] if item else None for item in placed])
        first = first or placed
        last = placed
    return {"timings": timings, "first": first, "last": last, "tracks": tracks, "extra_faces": len(answer.get("faces", [])) - sum(item is not None for item in last)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--class-size", type=int, default=30)
    parser.add_argument("--rounds", type=int, default=6, help="different frames tried for each number of faces")
    parser.add_argument("--frames", type=int, default=5, help="consecutive frames sent per round")
    parser.add_argument("--width", type=int, default=960, help="frame size the browser uploads (960x540 from a 720p camera)")
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    size = (args.width, args.height)

    init_database_schema()
    clock = CameraClock()
    face_routes.clock = clock
    print(f"pipeline {face_service.model_label()}; detector {settings.face_detector}; frame {args.width}x{args.height}; liveness {'on' if settings.face_liveness else 'off'}")
    print(f"threshold {settings.face_match_threshold}, margin {settings.face_match_margin}, {settings.face_confirm_frames} observations averaging >= {settings.face_confirm_score}")
    face_service.warm_up()
    with SessionLocal() as db:
        session, people, probes, strangers = enroll_class(db, args.dataset, args, rng)
        print(f"enrolled {len(people)} people from 5 photos each; {len(strangers)} photos of people who are not enrolled\n")
        names = sorted(people)

        def report(title, casts):
            placed = found = named_right = named_wrong = marked_right = marked_wrong = spoof = unsure = low = steady = strangers_marked = strangers_named = strangers_seen = 0
            timings = []
            for cast in casts:
                outcome = run_scenario(db, session, cast, size, args, clock)
                timings += outcome["timings"][1:] if len(outcome["timings"]) > 1 else outcome["timings"]
                for index, (name, _) in enumerate(cast):
                    first, last = outcome["first"][index], outcome["last"][index]
                    placed += 1
                    found += first is not None
                    ids = {frame_tracks[index] for frame_tracks in outcome["tracks"]}
                    steady += len(ids) == 1 and None not in ids
                    if last is None:
                        continue
                    low += last["result"] == "low_quality"
                    spoof += last["result"] == "liveness_failed"
                    unsure += last["result"] == "liveness_uncertain"
                    is_marked = last["result"] in ("verified", "already_marked")
                    if name is None:
                        strangers_seen += 1
                        strangers_named += first is not None and first.get("person_name") is not None
                        strangers_marked += is_marked
                        continue
                    if first is not None and first.get("person_name"):
                        named_right += first["person_name"] == name
                        named_wrong += first["person_name"] != name
                    marked_right += is_marked and last.get("person_name") == name
                    marked_wrong += is_marked and last.get("person_name") != name
            enrolled = placed - strangers_seen
            records = db.query(AttendanceRecord).count()
            line = f"{title:34s} faces found {found}/{placed}  track kept {steady}/{placed}  "
            if enrolled:
                line += f"named right on frame 1: {named_right}/{enrolled} (wrong {named_wrong})  marked after {args.frames} frames: {marked_right}/{enrolled} (as someone else {marked_wrong})  "
            if strangers_seen:
                line += f"strangers named on frame 1: {strangers_named}/{strangers_seen}  strangers marked: {strangers_marked}/{strangers_seen}  "
            line += f"liveness refused {spoof}, liveness unsure {unsure}, too poor to judge {low}"
            print(line)
            print(f"{'':34s} time per frame: median {1000 * statistics.median(timings):.0f} ms, slowest {1000 * max(timings):.0f} ms -> about {statistics.median(timings) * settings.face_confirm_frames:.1f} s of standing in view to be marked (records in last round: {records})")
            return statistics.median(timings)

        print("== Still pictures against the default settings (head-turn challenge on) ==")
        print("   The pasted photos never turn their heads, so none of them may be marked, whatever the liveness model says.")
        for count in (1, 10):
            casts = [[(name, probes[name]) for name in rng.sample(names, count)] for _ in range(args.rounds)]
            report(f"{count} still face(s), challenge on", casts)

        settings.face_challenge = "off"
        print("\n== Enrolled students only (challenge off from here on, to measure detection, identity and speed) ==")
        for count in COUNTS:
            casts = [[(name, probes[name]) for name in rng.sample(names, count)] for _ in range(args.rounds)]
            report(f"{count} face(s) in the frame", casts)

        print("\n== Enrolled students and strangers together (10 faces: 7 enrolled, 3 not) ==")
        casts = []
        for _ in range(args.rounds):
            cast = [(name, probes[name]) for name in rng.sample(names, 7)] + [(None, photo) for photo in rng.sample(strangers, 3)]
            rng.shuffle(cast)
            casts.append(cast)
        report("7 enrolled + 3 strangers", casts)

        print("\n== The same pipeline with the liveness check switched off (to separate its cost and its verdicts) ==")
        settings.face_liveness = False
        for count in (1, 10):
            casts = [[(name, probes[name]) for name in rng.sample(names, count)] for _ in range(args.rounds)]
            report(f"{count} face(s), liveness off", casts)
    engine.dispose()
    workspace.cleanup()


if __name__ == "__main__":
    main()
