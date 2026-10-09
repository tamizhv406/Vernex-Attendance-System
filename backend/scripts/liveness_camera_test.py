"""Measure the liveness check with YOUR camera, real faces and real attacks.

Nobody can tell you how well the liveness model works in your room without this. Run it on the
computer the backend runs on, with the camera you use for attendance (or one like it), and with
people who have agreed to take part.

    python scripts/liveness_camera_test.py record live     # a real person in front of the camera
    python scripts/liveness_camera_test.py record print    # a printed photo of a person
    python scripts/liveness_camera_test.py record screen   # a photo shown on a phone or tablet
    python scripts/liveness_camera_test.py record video    # a video of a person played on a screen
    python scripts/liveness_camera_test.py report

Each "record" run watches the camera for --seconds (default 20) and writes one line per frame to
logs/liveness_test.csv: the label you gave, the liveness score, the face size and the eye shift.
Move the way a real attempt would: different distances, angles and lighting; for attacks, hold the
photo or screen the way someone trying to cheat would. Do several runs per kind, with different
people and different photos, phones and prints. Use --note to say what a run was ("A4 print",
"phone, full brightness").

"report" reads everything recorded so far and shows, for each kind of attack, how many frames the
current settings would have accepted, and what other thresholds would have done.

Only numbers are written. No picture is saved and nothing leaves this computer. The application's
database is not opened.
"""
import argparse
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

LOG_FILE = ROOT / "logs" / "liveness_test.csv"
FIELDS = ["time", "run", "label", "note", "score", "face_px", "turn", "faces_in_frame"]
ATTACKS = ("print", "screen", "video")


def record(args):
    import cv2

    from app.services import face_service

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        sys.exit(f"Camera {args.camera} could not be opened. Close other programs using it, or try --camera 1.")
    print("loading models...")
    face_service.warm_up()
    LOG_FILE.parent.mkdir(exist_ok=True)
    new_file = not LOG_FILE.exists()
    run = time.strftime("%Y%m%d-%H%M%S")
    print(f"Recording '{args.label}' for {args.seconds} s. Only scores are saved, no pictures. Ctrl+C stops early.")
    frames = judged = 0
    with LOG_FILE.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        started = time.monotonic()
        try:
            while time.monotonic() - started < args.seconds:
                ok, frame = camera.read()
                if not ok:
                    continue
                frames += 1
                # The same size the browser uploads, so faces reach the models at the same scale.
                scale = min(1.0, 960 / frame.shape[1])
                if scale < 1:
                    frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                faces = face_service.detect_faces(frame)
                if not faces:
                    print("  no face", end="\r")
                    continue
                face = max(faces, key=lambda item: item["box"][2] * item["box"][3])
                scores = face_service.liveness_scores(frame, [tuple(face["box"])])
                if scores is None:
                    sys.exit("FACE_LIVENESS is switched off in .env; there is nothing to measure.")
                judged += 1
                writer.writerow({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "run": run, "label": args.label, "note": args.note,
                    "score": round(scores[0], 4), "face_px": min(face["box"][2], face["box"][3]),
                    "turn": "" if face["turn"] is None else round(face["turn"], 4), "faces_in_frame": len(faces),
                })
                print(f"  score {scores[0]:.3f} -> {face_service.liveness_verdict(scores[0]):9s} face {min(face['box'][2], face['box'][3])} px   ", end="\r")
        except KeyboardInterrupt:
            pass
    camera.release()
    print(f"\n{judged} frames with a face recorded ({frames} read) to {LOG_FILE}")


def load():
    if not LOG_FILE.exists():
        sys.exit(f"Nothing recorded yet ({LOG_FILE} does not exist). Run 'record' first.")
    with LOG_FILE.open(newline="", encoding="utf-8") as handle:
        return [dict(row, score=float(row["score"])) for row in csv.DictReader(handle)]


def summarize(rows, threshold, confident):
    # Per label: frames, runs, and the share of frames that are "live" / "uncertain" / "spoof".
    summary = {}
    for label in sorted({row["label"] for row in rows}):
        scores = sorted(row["score"] for row in rows if row["label"] == label)
        count = len(scores)
        summary[label] = {
            "frames": count,
            "runs": len({row["run"] for row in rows if row["label"] == label}),
            "live": sum(score >= confident for score in scores) / count,
            "uncertain": sum(threshold <= score < confident for score in scores) / count,
            "spoof": sum(score < threshold for score in scores) / count,
            "median": scores[count // 2],
            "p5": scores[int(0.05 * (count - 1))],
            "p95": scores[int(0.95 * (count - 1))],
        }
    return summary


def report(args):
    from app.config import settings

    rows = load()
    summary = summarize(rows, settings.face_liveness_threshold, settings.face_liveness_confident)
    print(f"{len(rows)} frames in {LOG_FILE}")
    print(f"Current settings: below {settings.face_liveness_threshold} = photo or screen, from {settings.face_liveness_confident} = live, between = uncertain (never counted)\n")
    print(f"{'kind':8s}{'frames':>8s}{'runs':>6s}{'score p5':>10s}{'median':>8s}{'p95':>7s}   {'judged live':>12s}{'uncertain':>11s}{'photo/screen':>14s}")
    for label, item in summary.items():
        print(f"{label:8s}{item['frames']:8d}{item['runs']:6d}{item['p5']:10.3f}{item['median']:8.3f}{item['p95']:7.3f}   {100 * item['live']:11.1f}%{100 * item['uncertain']:10.1f}%{100 * item['spoof']:13.1f}%")
    print("\n'judged live' is the number that matters: for print / screen / video it is the share of attack")
    print("frames the passive check let through; for live it is the share of real frames it accepted.")
    live = [row["score"] for row in rows if row["label"] == "live"]
    attacks = {label: [row["score"] for row in rows if row["label"] == label] for label in ATTACKS if label in summary}
    if live and attacks:
        print("\nWhat other 'live from' scores (FACE_LIVENESS_CONFIDENT) would do, frame by frame:")
        print("  live from   real faces accepted   " + "   ".join(f"{label} accepted" for label in attacks))
        for cut in (0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.98):
            line = f"    {cut:.2f}        {100 * sum(score >= cut for score in live) / len(live):12.1f}%     "
            line += "   ".join(f"{100 * sum(score >= cut for score in scores) / len(scores):{len(label) + 8}.1f}%" for label, scores in attacks.items())
            print(line)
        print("\nPick the lowest value at which the attacks you care about are (nearly) never accepted, and check")
        print("that real faces are still accepted often enough. Then set FACE_LIVENESS_CONFIDENT in backend/.env.")
    for label, need in (("live", 3), *((attack, 3) for attack in ATTACKS)):
        have = summary.get(label, {}).get("runs", 0)
        if have < need:
            print(f"NOT ENOUGH DATA for '{label}': {have} run(s). Record at least {need}, with different people and materials, before trusting these numbers.")
    print("\nThis measures single frames of the passive check only. The head-turn challenge is tested in the")
    print("scanner itself: an attack that the passive check accepts still has to answer the instruction.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    recorder = commands.add_parser("record")
    recorder.add_argument("label", choices=("live", *ATTACKS))
    recorder.add_argument("--seconds", type=int, default=20)
    recorder.add_argument("--camera", type=int, default=0)
    recorder.add_argument("--note", default="")
    commands.add_parser("report")
    args = parser.parse_args()
    record(args) if args.command == "record" else report(args)


if __name__ == "__main__":
    main()
