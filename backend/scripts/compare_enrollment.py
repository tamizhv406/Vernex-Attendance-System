"""Quick enrollment against five-pose enrollment: how long each costs and how well each recognizes.

    python scripts/compare_enrollment.py DATASET

DATASET is a folder with one sub-folder of photos per person (as for evaluate_recognition.py).

Part 1 times the stages of one enrollment frame with the real models on this machine and adds up
what each enrollment flow costs at the least (a student who gets every frame right first time).

Part 2 enrolls the same people from 1, 2, 3 and 5 photos and judges every variant on exactly the
same probe photos with the application's own matching rule and settings.

What the photos can and cannot tell: the photos of one person in such a dataset were taken on
different days. Five of them are a richer enrollment than five poses captured in one minute, and one
of them picked at random is a worse enrollment than one frame that passed the enrollment quality
checks. The real difference between the two flows is therefore likely smaller than the 1-versus-5
gap shown here; "1 photo, the most frontal and sharpest" is the closest stand-in for the quick flow.
Nothing is written to the database.
"""
import argparse
import os
import pickle
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import cv2
import numpy as np

import evaluate_recognition as evaluation
from app.config import settings
from app.services import face_service
from app.services.quality_service import check_pose, check_quality, face_measures

# What the browser loop adds around each request (frontend/src/main.jsx), in seconds.
OLD_LOOP = {"before_pose": 2.5, "between_frames": 0.25, "after_last": 1.2}
NEW_LOOP = {"before_first_pose": 0.0, "before_pose": 1.2, "between_frames": 0.08, "after_last": 0.6}


def camera_frame(photo, size=(960, 540), face_share=0.52):
    # The photo in the middle of a camera-sized frame, large enough to pass the "front" size check.
    width, height = size
    side = int(height * face_share / 0.56)
    side = min(side, height - 4)
    frame = np.full((height, width, 3), 110, dtype=np.uint8)
    picture = cv2.resize(photo, (side, side), interpolation=cv2.INTER_CUBIC)
    x, y = (width - side) // 2, (height - side) // 2
    frame[y:y + side, x:x + side] = picture
    return frame


def median_ms(function, repeats):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        samples.append(time.perf_counter() - started)
    return 1000 * statistics.median(samples)


def timing_report(rows, args):
    print("== 1. Where the time of one enrollment frame goes (medians, this machine, real models) ==")
    face_service.warm_up()
    frames = []
    for row in rows:
        frame = camera_frame(cv2.imread(str(row["path"])))
        faces = face_service.locate_faces(frame)
        if len(faces) != 1:
            continue
        quality = check_quality(frame, [faces[0]["box"]])
        if quality["ok"] and check_pose(frame, quality, "front", faces[0]["turn"])[0]:
            frames.append(frame)
        if len(frames) == args.timing_frames:
            break
    print(f"   {len(frames)} frames of 960x540 that pass the front-pose checks; each stage run on every one of them")
    stage = {}
    encoded = [cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1] for frame in frames]
    located = [face_service.locate_faces(frame) for frame in frames]
    index = {"value": 0}

    def each(function):
        def run():
            position = index["value"] % len(frames)
            index["value"] += 1
            function(position)
        return median_ms(run, len(frames) * 2)

    stage["decode the uploaded JPEG"] = each(lambda i: cv2.imdecode(encoded[i], cv2.IMREAD_COLOR))
    stage["find the face (detector)"] = each(lambda i: face_service.locate_faces(frames[i]))
    stage["quality and pose checks"] = each(lambda i: check_pose(frames[i], check_quality(frames[i], [located[i][0]["box"]]), "front", located[i][0]["turn"]))
    stage["liveness (MiniFASNet x2)"] = each(lambda i: face_service.liveness_scores(frames[i], [tuple(located[i][0]["box"])]))
    stage["embedding (FaceNet512)"] = each(lambda i: face_service.embed_faces(frames[i], face_service.locate_faces(frames[i]))) - stage["find the face (detector)"]
    blank = np.full((540, 960, 3), 110, dtype=np.uint8)
    stage["find the face, empty frame"] = median_ms(lambda: face_service.locate_faces(blank), 20)
    for name, value in stage.items():
        print(f"   {name:30s}{value:7.0f} ms")
    good = stage["decode the uploaded JPEG"] + stage["find the face (detector)"] + stage["quality and pose checks"] + stage["liveness (MiniFASNet x2)"] + stage["embedding (FaceNet512)"]
    refused_old = stage["decode the uploaded JPEG"] + stage["find the face (detector)"] + stage["embedding (FaceNet512)"] + stage["quality and pose checks"]
    refused_new = stage["decode the uploaded JPEG"] + stage["find the face (detector)"] + stage["quality and pose checks"]
    print(f"   a frame that is kept:                    {good:5.0f} ms of model and image work")
    print(f"   a frame that is refused, before:         {refused_old:5.0f} ms (the embedding was computed for every frame, then thrown away)")
    print(f"   a frame that is refused, now:            {refused_new:5.0f} ms (the embedding is only computed for frames that pass)")

    burst = settings.face_enroll_burst_frames
    pose_seconds, enrolled = measured_pose(frames, burst)
    print(f"\n   One pose through the real enrollment endpoint ({burst} frames uploaded as JPEG, checked, embedded, the best kept,")
    print(f"   saved to a temporary SQLite database): median {pose_seconds:.2f} s over {enrolled} enrollments, {1000 * pose_seconds / burst:.0f} ms per frame")

    def floor(poses, loop, first_wait):
        return first_wait + (poses - 1) * loop["before_pose"] + poses * (pose_seconds + (burst - 1) * loop["between_frames"]) + loop["after_last"]

    quick_steps = ["front"] + [step for step in ("left", "right", "close", "far") if step in settings.face_enroll_quick_steps]
    print("\n   The least an enrollment can take once the camera is on: every frame good at the first try, no time for")
    print("   the student to move into a pose, no network delay. Real enrollments are longer than this floor: add the")
    print("   time the student needs to turn (left, right) or move (close, far), which was not measured here.")
    print(f"     five poses, as it was (pause of {OLD_LOOP['before_pose']} s before every pose)   {floor(5, OLD_LOOP, OLD_LOOP['before_pose']):5.1f} s")
    print(f"     five poses, now                                          {floor(5, NEW_LOOP, 0):5.1f} s")
    print(f"     quick ({', '.join(quick_steps)}), now{'':{max(1, 30 - len(', '.join(quick_steps)))}s}{floor(len(quick_steps), NEW_LOOP, 0):5.1f} s")
    print(f"     quick (front only), if FACE_ENROLL_QUICK_STEPS=front      {floor(1, NEW_LOOP, 0):5.1f} s")
    return stage


def measured_pose(frames, burst):
    # Sends each frame `burst` times to the enrollment endpoint's own code, as the browser does, and
    # times the whole pose. Uses a temporary database; the application's database is never opened.
    import asyncio
    import base64
    import tempfile

    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.models.person import Person
    from app.routes import face_routes

    class Upload:
        headers = {}

        def __init__(self, body):
            self.body = body

        async def json(self):
            return self.body

    times = []
    with tempfile.TemporaryDirectory() as folder:
        engine = create_engine(f"sqlite:///{Path(folder) / 'enrollment.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        quick_steps, settings.face_enroll_quick_steps = settings.face_enroll_quick_steps, ["front"]
        with sessionmaker(bind=engine)() as db:
            for number, frame in enumerate(frames):
                person = Person(person_code=f"T{number}", full_name=f"Timing {number}", person_type="student")
                db.add(person)
                db.commit()
                body = {"person_id": person.id, "current_step": "front", "image_base64": base64.b64encode(cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()).decode()}
                face_routes.start_enrollment(person.id, db, "quick")
                started = time.perf_counter()
                try:
                    answers = [asyncio.run(face_routes.enrollment_frame(Upload(body), db)) for _ in range(burst)]
                except HTTPException:
                    continue
                if answers[-1].get("completed"):
                    times.append(time.perf_counter() - started)
                else:
                    face_routes.cancel_enrollment(person.id, db)
        settings.face_enroll_quick_steps = quick_steps
        engine.dispose()
    if not times:
        sys.exit("No timing frame completed an enrollment (the liveness model refused all of them). Try --timing-frames 40.")
    return statistics.median(times), len(times)


def measures_for(rows, cache_file):
    # Head turn and sharpness of each enrollment-pool photo, to pick "the most frontal and sharpest".
    cache = pickle.loads(cache_file.read_bytes()) if cache_file.exists() else {}
    for row in rows:
        key = str(row["path"])
        if key not in cache:
            image = cv2.imread(key)
            faces = face_service.locate_faces(image)
            if not faces:
                cache[key] = None
                continue
            height, width = image.shape[:2]
            face = min(faces, key=lambda item: (item["box"][0] + item["box"][2] / 2 - width / 2) ** 2 + (item["box"][1] + item["box"][3] / 2 - height / 2) ** 2)
            x, y, w, h = face["box"]
            crop = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)[max(y, 0): y + h, max(x, 0): x + w]
            cache[key] = (face["turn"], face_measures(crop)[2] if crop.size else 0.0)
    cache_file.write_bytes(pickle.dumps(cache))
    return cache


def burst_embedding(path, rng):
    # Three frames of one moment, as a webcam would deliver them: the same picture, a few pixels
    # apart, slightly different light, sensor noise and JPEG compression. Returns their vectors.
    image = cv2.imread(str(path))
    vectors = []
    for _ in range(3):
        height, width = image.shape[:2]
        scale = 1 + rng.uniform(-0.02, 0.02)
        matrix = np.float32([[scale, 0, rng.uniform(-4, 4)], [0, scale, rng.uniform(-4, 4)]])
        frame = cv2.warpAffine(image, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        frame = frame * rng.uniform(0.95, 1.05) + rng.normal(0, 2.0, frame.shape)
        frame = cv2.imdecode(cv2.imencode(".jpg", np.clip(frame, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 80])[1], cv2.IMREAD_COLOR)
        face = evaluation.main_face(frame)
        if face is not None:
            vectors.append(np.asarray(face["embedding"], dtype=np.float32))
    return vectors


def recognition_report(rows, args):
    print(f"\n== 2. Recognition with 1, 2, 3 and 5 enrollment photos, same probes (threshold {settings.face_match_threshold}, margin {settings.face_match_margin}, "
          f"{settings.face_confirm_frames} looks averaging >= {settings.face_confirm_score}) ==")
    pool = [row for row in rows if row["role"] == "enroll"]
    probes = [row for row in rows if row["role"] in ("probe", "unknown")]
    known = np.array([row["role"] == "probe" for row in probes])
    truth = np.array([row["person"] for row in probes])
    by_person = {}
    for row in pool:
        by_person.setdefault(row["person"], []).append(row)
    print(f"   {len(by_person)} people, {int(known.sum())} probe photos of them, {int((~known).sum())} photos of people who are not enrolled")
    measures = measures_for(pool, args.cache / f"{args.dataset.resolve().name}-enrollment-measures.pkl")

    def frontal_first(group):
        def badness(row):
            measure = measures.get(str(row["path"]))
            return (1.0, 0.0) if measure is None or measure[0] is None else (abs(measure[0]), -measure[1])
        return sorted(group, key=badness)

    rng = np.random.default_rng(args.seed)
    burst_cache_file = args.cache / f"{args.dataset.resolve().name}-{face_service.model_label()}-burst.pkl"
    bursts = pickle.loads(burst_cache_file.read_bytes()) if burst_cache_file.exists() else {}
    for person, group in by_person.items():
        best = frontal_first(group)[0]
        if str(best["path"]) not in bursts:
            bursts[str(best["path"])] = burst_embedding(best["path"], rng)
    burst_cache_file.write_bytes(pickle.dumps(bursts))

    def turn_of(row):
        measure = measures.get(str(row["path"]))
        return 0.0 if measure is None or measure[0] is None else measure[0]

    def front_left_right(group):
        # The pool photo looking straightest, the one turned furthest one way and the one turned
        # furthest the other way: three different views, as the front, left and right poses are.
        front = frontal_first(group)[0]
        others = sorted((row for row in group if row is not front), key=turn_of)
        return [front, others[0], others[-1]]

    def resized(path, factor):
        key = f"{path}@{factor}"
        if key not in bursts:
            image = cv2.imread(str(path))
            face = evaluation.main_face(cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC))
            bursts[key] = None if face is None else np.asarray(face["embedding"], dtype=np.float32)
        return bursts[key]

    def front_close_far(group):
        # One view at three sizes, as the front, close and far poses are when the head does not turn.
        front = frontal_first(group)[0]
        sizes = [dict(front, embedding=vector) for vector in (resized(front["path"], 0.6), resized(front["path"], 1.5)) if vector is not None]
        return [front] + sizes

    variants = {
        "1 photo, random": lambda group: group[:1],
        "1 photo, most frontal + sharpest": lambda group: frontal_first(group)[:1],
        "same, average of a 3-frame burst": "burst",
        "same view at 3 sizes (close/far)": front_close_far,
        "2 photos": lambda group: group[:2],
        "2 photos: frontal + most turned": lambda group: front_left_right(group)[:1] + [max(front_left_right(group)[1:], key=lambda row: abs(turn_of(row)))],
        "3 photos": lambda group: group[:3],
        "3 photos: frontal, left, right": front_left_right,
        "5 photos (five-pose stand-in)": lambda group: group[:5],
    }
    print(f"   {'enrollment':34s}{'one frame:':>11s}{'':30s}{'marking decision, class of ' + str(args.class_size) + ':':>44s}")
    print(f"   {'':34s}{'named right':>12s}{'left unknown':>13s}{'stranger named':>15s}   {'member marked':>20s}{'non-member marked':>22s}   genuine score (median)")
    results = {}
    for label, choose in variants.items():
        gallery_rows = []
        for person, group in by_person.items():
            if choose == "burst":
                best = frontal_first(group)[0]
                vectors = bursts[str(best["path"])] or [best["embedding"]]
                gallery_rows += [dict(best, embedding=vector, role="enroll") for vector in vectors]
            else:
                gallery_rows += [dict(row, role="enroll") for row in choose(group)]
        usable = gallery_rows + probes
        items, matrix = evaluation.gallery_for(usable)
        named, top, accepted = evaluation.outcomes(items, matrix, probes, settings.face_match_threshold, settings.face_match_margin)
        decision = evaluation.attendance_decision(usable, probes, args, settings.face_match_threshold, settings.face_match_margin, settings.face_confirm_score)
        right = 100 * (accepted & (named == truth))[known].mean()
        wrong = 100 * (accepted & (named != truth))[known].mean()
        genuine = np.median(top[known & (named == truth)])
        results[label] = (right, decision)
        member = f"{decision['different photos']['member']:.1f}% / {decision['one photo']['member']:.1f}%"
        outsider = f"{decision['different photos']['outsider']:.2f}% / {decision['one photo']['outsider']:.2f}%"
        burst_cache_file.write_bytes(pickle.dumps(bursts))
        print(f"   {label:34s}{right:11.2f}%{100 * (~accepted)[known].mean():12.2f}%{100 * accepted[~known].mean():14.2f}%   {member:>20s}{outsider:>22s}   {genuine:.3f}" + (f"   (named as another: {wrong:.2f}%)" if wrong else ""))
    print("   The two figures under 'marking decision' are for three different photos / the same photo three times (see evaluate_recognition.py).")
    print("   'member marked' missing from 100% is the false rejection rate per attempt; 'non-member marked' is the false acceptance rate per attempt.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--min-images", type=int, default=10)
    parser.add_argument("--max-probes", type=int, default=10)
    parser.add_argument("--unknown", type=int, default=500)
    parser.add_argument("--classes", type=int, default=20)
    parser.add_argument("--class-size", type=int, default=30)
    parser.add_argument("--timing-frames", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cache", type=Path, default=ROOT / "eval_data" / "cache")
    parser.add_argument("--skip-timing", action="store_true")
    args = parser.parse_args()
    args.enroll = args.pool = 5

    rows = evaluation.select(args.dataset, args)
    args.cache.mkdir(parents=True, exist_ok=True)
    label = face_service.model_label()
    print(f"pipeline {label}; detector {settings.face_detector}; photos {len(rows)}")
    usable = evaluation.embed_rows(rows, args.cache / f"{args.dataset.resolve().name}-{label}.pkl")
    if not args.skip_timing:
        timing_report([row for row in usable if row["role"] == "probe"], args)
    recognition_report(usable, args)


if __name__ == "__main__":
    main()
