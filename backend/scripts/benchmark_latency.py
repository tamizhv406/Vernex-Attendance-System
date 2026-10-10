"""Where the time of a scanner frame and of an enrollment frame goes on this machine, stage by stage.

    python scripts/benchmark_latency.py DATASET [--json OUT.json]

DATASET is a folder with one sub-folder of photos per person (the layout evaluate_recognition.py
and benchmark_multiface.py use). A class is enrolled from five photos per person. Camera-sized
frames are then built, JPEG-encoded the way the browser uploads them, and sent through the same
code the endpoints run: decode, detector, quality gate, crop, embedding, matching, liveness,
tracking and the attendance write. The stage times come from app/utils/timing.py, the same
instrumentation the running server writes to logs/timing.log.

The first frame is sent before any model is loaded and is reported on its own as the cold start.
Everything after it is the warm path: median, p95 and p99 per stage.

Everything is written to a temporary database that is deleted afterwards.

What this is and is not: models, code and timings are real. The frames are photos pasted on a grey
background, so this measures computation on this machine. It does not measure a real camera, a
real network, room lighting, or how long a person needs to follow an instruction.
"""
import argparse
import asyncio
import json
import os
import random
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def early_options():
    # Thread settings must be in place before TensorFlow and PyTorch are imported.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--omp-threads", type=int)
    parser.add_argument("--tf-threads", type=int)
    known, _ = parser.parse_known_args()
    if known.omp_threads:
        os.environ["OMP_NUM_THREADS"] = str(known.omp_threads)
    if known.tf_threads is not None:
        os.environ["FACE_TF_THREADS"] = str(known.tf_threads)
    return known


EARLY = early_options()

# Sets up the temporary database and the import path, and brings the frame builders with it.
import benchmark_multiface as bench

import cv2
import numpy as np

from app.config import settings
from app.database import SessionLocal, engine
from app.models.attendance import AttendanceRecord
from app.models.person import Person
from app.routes import face_routes
from app.schema import init_database_schema
from app.services import face_service, tracking_service
from app.utils import timing

settings.face_timing_log = False
JPEG_QUALITY = 80
server_loop = None


def run_async(coroutine):
    # Frames run on one event loop that lives as long as the process, under one long-lived root
    # task, exactly as they do in the server. The models are called from worker threads that belong
    # to that root task and are reused from frame to frame. Running each frame with asyncio.run (or
    # run_until_complete) instead ends the worker thread after every frame; every new thread that
    # calls the detector gets its own team of OpenMP threads, and after a few hundred frames
    # thousands of them compete for the processor. That slows the harness, not the server.
    global server_loop
    if server_loop is None:
        server_loop = asyncio.new_event_loop()

        async def forever():
            await asyncio.Event().wait()

        threading.Thread(target=lambda: server_loop.run_until_complete(forever()), daemon=True).start()
    timer = timing.current.get()

    async def in_request():
        # The request's timer travels with it onto the loop, as a request's context does in the server.
        timing.current.set(timer)
        return await coroutine

    return asyncio.run_coroutine_threadsafe(in_request(), server_loop).result()


def os_threads():
    # Threads of this process as the operating system counts them (OpenMP and TensorFlow threads included).
    import ctypes

    class Entry(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("usage", ctypes.c_ulong), ("pid", ctypes.c_ulong), ("heap", ctypes.c_void_p), ("module", ctypes.c_ulong), ("threads", ctypes.c_ulong), ("parent", ctypes.c_ulong), ("priority", ctypes.c_long), ("flags", ctypes.c_ulong), ("name", ctypes.c_char * 260)]

    try:
        kernel = ctypes.windll.kernel32
        kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        entry = Entry()
        entry.size = ctypes.sizeof(Entry)
        found = kernel.Process32First(ctypes.c_void_p(snapshot), ctypes.byref(entry))
        while found:
            if entry.pid == os.getpid():
                return int(entry.threads)
            found = kernel.Process32Next(ctypes.c_void_p(snapshot), ctypes.byref(entry))
    except Exception:
        pass
    return None


def upload(frame):
    # The bytes the browser would send for this frame.
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])[1].tobytes()


def scan(db, session, raw, scanner="benchmark"):
    # One scanner frame, timed like the /face/recognize endpoint times it (without HTTP itself).
    timer = timing.start("scan")
    with timing.stage("decode"):
        image = face_routes.decode_image_bytes(raw)
    payload = {"session_id": session.id, "course_id": None, "batch_id": None, "device_name": "benchmark", "scanner_id": scanner}
    response = run_async(face_routes.scan_frame(db, payload, image))
    return timing.finish(timer, face_routes.scan_outcome(response))


def enroll_frame(db, person, raw):
    # One enrollment frame through the real capture code. Whether it is accepted is reported, not forced.
    timer = timing.start("enroll")
    with timing.stage("decode"):
        image = face_routes.decode_image_bytes(raw)
    state = face_routes.pending_enrollments[person.id]
    enrollment = face_routes.latest_enrollment(db, person.id)
    payload = {"image": image, "has_specs": False, "current_step": state["step"]}
    result = run_async(face_routes.capture_pose(db, person, enrollment, state, payload))
    outcome = "accepted" if result.get("accepted") else "holding" if result.get("holding") else str(result.get("quality_status"))
    return timing.finish(timer, outcome)


def show(title, records):
    summary = timing.summarize(records)
    for kind, data in summary.items():
        total = data["total_ms"]
        if not total:
            continue
        outcomes = {}
        for record in records:
            outcomes[record["outcome"]] = outcomes.get(record["outcome"], 0) + 1
        print(f"\n{title}  [{kind}, {total['n']} warm frames]  outcomes: {outcomes}")
        print(f"  {'stage':10s} {'p50':>8s} {'p95':>8s} {'p99':>8s} {'max':>8s}  share of p50")
        for name, values in sorted(data["stages_ms"].items(), key=lambda entry: -entry[1]["p50"]):
            print(f"  {name:10s} {values['p50']:8.1f} {values['p95']:8.1f} {values['p99']:8.1f} {values['max']:8.1f}  {100 * values['p50'] / max(total['p50'], 0.001):5.1f}%")
        print(f"  {'TOTAL':10s} {total['p50']:8.1f} {total['p95']:8.1f} {total['p99']:8.1f} {total['max']:8.1f}   (threads in this process: {os_threads()})")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--class-size", type=int, default=30)
    parser.add_argument("--frames", type=int, default=60, help="warm frames measured per scenario")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--omp-threads", type=int, help="OMP_NUM_THREADS (PyTorch detector)")
    parser.add_argument("--tf-threads", type=int, help="FACE_TF_THREADS for this run (0 = TensorFlow's default)")
    parser.add_argument("--json", type=Path, help="write the summaries here")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    size = (args.width, args.height)
    report = {"settings": {"frame": list(size), "omp_threads": EARLY.omp_threads, "tf_threads": settings.face_tf_threads, "cpu_count": os.cpu_count(), "pipeline": face_service.model_label(), "detector": settings.face_detector, "challenge": settings.face_challenge, "liveness": settings.face_liveness}}
    print(json.dumps(report["settings"]))

    init_database_schema()
    clock = bench.CameraClock()
    face_routes.clock = clock
    folders = sorted(path for path in args.dataset.iterdir() if path.is_dir())
    first_photo = next(bench.photos_of(folder)[0] for folder in folders if bench.photos_of(folder))

    with SessionLocal() as db:
        # Cold start: the very first frame of the process, with no model loaded yet. It needs a
        # session to exist, so an empty one is made for it and the class is enrolled afterwards.
        began = time.perf_counter()
        timer = timing.start("scan")
        with timing.stage("decode"):
            image = face_routes.decode_image_bytes(upload(bench.frame_with([first_photo], size)[0]))
        face_service.detect_faces(image)
        face_service.judge_liveness(image, [(40, 40, 80, 80)])
        cold = timing.finish(timer, "cold_start")
        report["cold_start"] = cold
        print(f"\nCOLD START (first frame of the process, models loading): {cold['total_ms'] / 1000:.1f} s  stages {cold['stages_ms']}  loaded during it: {cold['cold']}")
        print(f"  wall time including imports already done: {time.perf_counter() - began:.1f} s")

        session, people, probes, strangers = bench.enroll_class(db, args.dataset, args, rng)
        names = sorted(people)
        print(f"enrolled {len(people)} people from 5 photos each")

        def scanner_scenario(title, cast_of):
            records = []
            tracking_service.reset()
            face_routes.marked_today.clear()
            db.query(AttendanceRecord).delete()
            db.commit()
            for index in range(args.frames):
                if index % 5 == 0:
                    cast = cast_of()
                frame, _ = bench.frame_with(cast, size, shift=3 * (index % 5)) if cast else (np.full((size[1], size[0], 3), 110, dtype=np.uint8), [])
                clock.now += 0.7
                records.append(scan(db, session, upload(frame)))
            report[title] = show(title, records)

        scanner_scenario("scanner, no face in view", lambda: [])
        for count in (1, 2, 5):
            scanner_scenario(f"scanner, {count} enrolled face(s), not yet marked", lambda count=count: [probes[name] for name in rng.sample(names, count)])
        scanner_scenario("scanner, 1 unknown face", lambda: [rng.choice(strangers)])

        # Two scanners sending frames at the same moment: the models run one frame at a time, so the
        # second waits. This measures that wait.
        records = []
        tracking_service.reset()
        raws = [[upload(bench.frame_with([probes[rng.choice(names)]], size, shift=3 * (index % 5))[0]) for index in range(args.frames // 2)] for _ in range(2)]

        def worker(frames, name):
            with SessionLocal() as own:
                for raw in frames:
                    clock.now += 0.35
                    records.append(scan(own, session, raw, scanner=name))

        threads = [threading.Thread(target=worker, args=(frames, f"scanner-{number}")) for number, frames in enumerate(raws)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        report["two scanners at once"] = show("scanner, 2 cameras sending 1 face each at the same moment", records)

        # Enrollment frames: a new, unenrolled person looking straight at the camera.
        person = Person(person_code="NEW", full_name="New student", person_type="student", course_id=session.course_id, batch_id=session.batch_id)
        db.add(person)
        db.commit()
        records = []
        for index in range(args.frames):
            if person.id not in face_routes.pending_enrollments:
                face_routes.start_enrollment(person.id, db, mode="quick")
            frame, _ = bench.frame_with([strangers[index // 6 % len(strangers)]], size)
            clock.now += 0.4
            try:
                records.append(enroll_frame(db, person, upload(frame)))
            except Exception as exc:
                timing.current.set(None)
                print("enrollment frame raised:", exc)
        report["enrollment"] = show("enrollment frame (front pose, one face)", records)

    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    engine.dispose()
    bench.workspace.cleanup()


if __name__ == "__main__":
    main()
