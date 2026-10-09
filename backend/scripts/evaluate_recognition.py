"""Measure face recognition accuracy with the app's own code and settings.

    python scripts/evaluate_recognition.py DATASET            # accuracy report
    python scripts/evaluate_recognition.py DATASET --quality  # how small / blurred / dark faces behave

DATASET is a folder with one sub-folder of photos per person:

    DATASET/alice/1.jpg, 2.jpg, ...      DATASET/bob/1.jpg, ...

People with at least --min-images photos are "enrolled" with --enroll of them (like the 5 enrollment
poses); their other photos are genuine probes. People with a single photo are never enrolled: they are
the unknown faces that must stay "Unknown". Every face goes through face_service.detect_faces, the
gallery through build_gallery and the decision through best_match, so the numbers describe the code
that runs in production. Nothing is written to the database.

Set FACE_PIPELINE, FACE_GALLERY, FACE_MATCH_THRESHOLD ... in the environment to compare settings.
"""
import argparse
import itertools
import json
import os
import pickle
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import cv2
import numpy as np

from app.config import settings
from app.services import face_service
from app.services.quality_service import scan_problem

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def select(dataset, args):
    # One row per photo: person, role (enroll / probe / unknown), path. Seeded, so runs are comparable.
    # With --pool larger than --enroll the photos between the two are set aside ("spare"), so runs
    # with different --enroll values are judged on exactly the same probe photos.
    rng = random.Random(args.seed)
    pool = max(getattr(args, "pool", 0) or 0, args.enroll)
    rows, singles = [], []
    for folder in sorted(path for path in dataset.iterdir() if path.is_dir()):
        photos = sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_TYPES)
        if len(photos) >= args.min_images:
            rng.shuffle(photos)
            for index, path in enumerate(photos[:pool + args.max_probes]):
                rows.append({"person": folder.name, "role": "enroll" if index < args.enroll else "spare" if index < pool else "probe", "path": path})
        elif len(photos) == 1:
            singles.append({"person": folder.name, "role": "unknown", "path": photos[0]})
    rng.shuffle(singles)
    return rows + singles[:args.unknown]


def main_face(image):
    # The photo's subject: the detected face nearest the centre. None when the app finds no face.
    faces = face_service.detect_faces(image)
    if not faces:
        return None
    height, width = image.shape[:2]
    return min(faces, key=lambda face: (face["box"][0] + face["box"][2] / 2 - width / 2) ** 2 + (face["box"][1] + face["box"][3] / 2 - height / 2) ** 2)


def embed_rows(rows, cache_file):
    # Embeddings are slow on a CPU, so they are kept per pipeline label and reused between runs.
    cache = pickle.loads(cache_file.read_bytes()) if cache_file.exists() else {}
    missing = [row for row in rows if str(row["path"]) not in cache]
    for index, row in enumerate(missing):
        face = main_face(cv2.imread(str(row["path"])))
        cache[str(row["path"])] = None if face is None else np.asarray(face["embedding"], dtype=np.float32)
        if index % 100 == 0:
            print(f"  embedding {index}/{len(missing)}", flush=True)
            cache_file.write_bytes(pickle.dumps(cache))
    if missing:
        cache_file.write_bytes(pickle.dumps(cache))
    for row in rows:
        row["embedding"] = cache[str(row["path"])]
    return [row for row in rows if row["embedding"] is not None]


def unit(vectors):
    vectors = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def gallery_for(rows, people=None):
    # The app's gallery, built by the app, from the enrollment photos of the chosen people.
    stored = [SimpleNamespace(person_id=row["person"], embedding_vector=json.dumps(row["embedding"].tolist()))
              for row in rows if row["role"] == "enroll" and (people is None or row["person"] in people)]
    return face_service.build_gallery(stored)


def outcomes(items, matrix, probes, threshold, margin):
    # best_match's rule for many probes at once: the best gallery row must clear the threshold and
    # lead every row of another person by the margin. Returns (named person, score, accepted).
    owners = np.array([item.person_id for item in items])
    scores = unit(np.stack([row["embedding"] for row in probes])) @ matrix.T
    best = scores.argmax(axis=1)
    top = scores[np.arange(len(scores)), best]
    rival = np.where(owners[None, :] != owners[best][:, None], scores, -1.0).max(axis=1) if len(set(owners)) > 1 else np.full(len(probes), -1.0)
    accepted = (top >= threshold) & (top - rival >= margin)
    return owners[best], top, accepted


def rates(genuine, impostor, threshold):
    return float((impostor >= threshold).mean()), float((genuine < threshold).mean())


def report(rows, args):
    usable = rows
    persons = np.array([row["person"] for row in usable])
    vectors = unit(np.stack([row["embedding"] for row in usable]))

    print("\n== 1. Same person or not (every pair of photos, cosine similarity of unit vectors) ==")
    scores = vectors @ vectors.T
    upper = np.triu_indices(len(usable), 1)
    same = (persons[:, None] == persons[None, :])[upper]
    genuine, impostor = np.sort(scores[upper][same]), np.sort(scores[upper][~same])
    print(f"genuine pairs {len(genuine)}, impostor pairs {len(impostor)}")
    for name, values in (("genuine", genuine), ("impostor", impostor)):
        print(f"  {name:9s} mean {values.mean():.3f}  p1 {np.percentile(values, 1):.3f}  p5 {np.percentile(values, 5):.3f}  median {np.median(values):.3f}  p95 {np.percentile(values, 95):.3f}  p99 {np.percentile(values, 99):.3f}  p99.9 {np.percentile(values, 99.9):.3f}")
    grid = np.linspace(-0.2, 1.0, 2401)
    frr = np.searchsorted(genuine, grid, side="left") / len(genuine)
    far = 1 - np.searchsorted(impostor, grid, side="left") / len(impostor)
    cross = int(np.argmin(np.abs(far - frr)))
    print(f"  EER {100 * (far[cross] + frr[cross]) / 2:.2f}% at threshold {grid[cross]:.3f}")
    for target in (1e-2, 1e-3, 1e-4):
        at = int(np.argmax(far <= target))
        print(f"  FAR <= {target:g}: threshold {grid[at]:.3f}, TAR {100 * (1 - frr[at]):.2f}%")
    print("  threshold    FAR        FRR      accuracy (balanced)")
    for threshold in (0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        a, r = rates(genuine, impostor, threshold)
        marker = "  <- FACE_MATCH_THRESHOLD" if abs(threshold - settings.face_match_threshold) < 1e-9 else ""
        print(f"    {threshold:.2f}    {100 * a:7.3f}%  {100 * r:7.2f}%  {100 * (1 - (a + r) / 2):7.2f}%{marker}")

    print(f"\n== 2. Who is it? (gallery: {args.enroll} photos per person, FACE_GALLERY={settings.face_gallery}) ==")
    items, matrix = gallery_for(usable)
    probes = [row for row in usable if row["role"] in ("probe", "unknown")]
    known = np.array([row["role"] == "probe" for row in probes])
    truth = np.array([row["person"] for row in probes])
    named, top, accepted = outcomes(items, matrix, probes, settings.face_match_threshold, settings.face_match_margin)
    print(f"enrolled people {len(set(item.person_id for item in items))}, probes of enrolled people {int(known.sum())}, probes of unknown people {int((~known).sum())}")
    print(f"  top-1 (closest person is the right one, threshold ignored): {100 * (named[known] == truth[known]).mean():.2f}%")
    print(f"  one frame at threshold {settings.face_match_threshold} / margin {settings.face_match_margin}:")
    correct = accepted & (named == truth)
    print(f"    enrolled face named correctly   {100 * correct[known].mean():6.2f}%")
    print(f"    enrolled face named as another  {100 * (accepted & (named != truth))[known].mean():6.2f}%")
    print(f"    enrolled face left 'Unknown'    {100 * (~accepted)[known].mean():6.2f}%")
    print(f"    unknown face given a name       {100 * accepted[~known].mean():6.2f}%" if (~known).any() else "    (no unknown faces in this dataset)")
    print("  threshold   named correctly   named as another   unknown given a name")
    for threshold in (0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        named_t, _, accepted_t = outcomes(items, matrix, probes, threshold, settings.face_match_margin)
        unknown_rate = f"{100 * accepted_t[~known].mean():8.2f}%" if (~known).any() else "     n/a"
        print(f"    {threshold:.2f}       {100 * (accepted_t & (named_t == truth))[known].mean():8.2f}%        {100 * (accepted_t & (named_t != truth))[known].mean():8.2f}%            {unknown_rate}")

    print("\n== 3. Confusion cases at the current settings (strongest first) ==")
    wrong = [(top[i], probes[i], named[i]) for i in np.flatnonzero(accepted & (named != truth))]
    for score, row, name in sorted(wrong, key=lambda entry: -entry[0])[:args.cases]:
        kind = "unknown person" if row["role"] == "unknown" else "enrolled"
        print(f"  {score:.3f}  {row['path'].parent.name}/{row['path'].name} ({kind}) named as {name}")
    missed = [(top[i], probes[i]) for i in np.flatnonzero(known & ~accepted)]
    print(f"  wrongly named: {len(wrong)}; enrolled faces left unknown: {len(missed)} (weakest: " + ", ".join(f"{row['path'].name} {score:.2f}" for score, row in sorted(missed, key=lambda entry: entry[0])[:5]) + ")")

    print(f"\n== 4. Attendance decision: {settings.face_confirm_frames} observations in a row, all named the same, average score >= {settings.face_confirm_score} ==")
    print(f"   {args.classes} random classes of {args.class_size} enrolled people; every other multi-photo person walks past as a non-member.")
    print("   'different photos': each observation is another photo of the person (the best case: independent looks).")
    print("   'one photo': all observations are the same photo (the worst case: video frames that are nearly identical).")
    print("   A real scan lies between the two.")
    current = attendance_decision(usable, probes, args, settings.face_match_threshold, settings.face_match_margin, settings.face_confirm_score)
    if current is None:
        print("   not enough multi-photo people for this part")
        return
    for label, numbers in current.items():
        print(f"   {label:16s} member marked present {numbers['member']:6.2f}%   member marked as someone else {numbers['wrong']:6.3f}%   non-member marked present {numbers['outsider']:6.3f}%   (of {numbers['member_tries']} / {numbers['outsider_tries']} tries)")

    print("\n== 5. Calibration: the same decision at other settings (choose from here, never by feel) ==")
    print("   threshold  margin  confirm |  different photos: member   non-member |  one photo: member   non-member")
    for threshold, margin, confirm in itertools.product((0.55, 0.60, 0.65), (0.05, 0.10), (0.65, 0.70, 0.75, 0.80)):
        numbers = attendance_decision(usable, probes, args, threshold, margin, confirm)
        mark = "  <- current" if (threshold, margin, confirm) == (settings.face_match_threshold, settings.face_match_margin, settings.face_confirm_score) else ""
        print(f"     {threshold:.2f}     {margin:.2f}    {confirm:.2f}   |  {numbers['different photos']['member']:17.2f}%  {numbers['different photos']['outsider']:10.3f}% |  {numbers['one photo']['member']:13.2f}%  {numbers['one photo']['outsider']:10.3f}%{mark}")

    print(f"\n== 6. Enrolling a face that is already enrolled (FACE_ENROLL_DUPLICATE_SCORE={settings.face_enroll_duplicate_score}) ==")
    print("   A second set of 5 photos is 'enrolled' and its average face compared with everyone's stored average face.")
    centroids, names = [], []
    for person in sorted({row["person"] for row in usable if row["role"] == "enroll"}):
        second = [row["embedding"] for row in probes if row["person"] == person][:args.enroll]
        first = [row["embedding"] for row in usable if row["person"] == person and row["role"] == "enroll"]
        if len(second) == args.enroll and len(first) == args.enroll:
            centroids.append((unit(unit(first).mean(axis=0)), unit(unit(second).mean(axis=0))))
            names.append(person)
    stored = np.stack([first for first, _ in centroids])
    fresh = np.stack([second for _, second in centroids])
    scores = fresh @ stored.T
    same = np.diag(scores)
    other = np.where(np.eye(len(names), dtype=bool), -1.0, scores).max(axis=1)
    print(f"   {len(names)} people. Same person again: median {np.median(same):.3f}, lowest {same.min():.3f}. Closest OTHER person: median {np.median(other):.3f}, p99 {np.percentile(other, 99):.3f}, highest {other.max():.3f}")
    print("   score    same face caught   different person wrongly refused (against all the others)")
    for score in (0.65, 0.70, 0.75, 0.80, 0.85, 0.90):
        mark = "  <- current" if abs(score - settings.face_enroll_duplicate_score) < 1e-9 else ""
        print(f"    {score:.2f}      {100 * (same >= score).mean():7.2f}%          {100 * (other >= score).mean():7.2f}%{mark}")


def attendance_decision(usable, probes, args, threshold, margin, confirm_score):
    # The scanner's marking rule (tracking_service.observe) replayed on photos: the last N observations
    # must all be accepted, all name the same person, and average at least confirm_score.
    rng = np.random.default_rng(args.seed)
    frames = settings.face_confirm_frames
    by_person = {}
    for row in probes:
        if row["role"] == "probe":
            by_person.setdefault(row["person"], []).append(row)
    everyone = sorted(name for name, group in by_person.items() if len(group) >= frames)
    if len(everyone) <= args.class_size:
        return None
    counts = {"different photos": [0, 0, 0, 0, 0], "one photo": [0, 0, 0, 0, 0]}
    for _ in range(args.classes):
        members = set(rng.choice(everyone, args.class_size, replace=False))
        class_items, class_matrix = gallery_for(usable, members)
        for person in everyone:
            group = by_person[person]
            named_c, top_c, accepted_c = outcomes(class_items, class_matrix, group, threshold, margin)
            combos = list(itertools.combinations(range(len(group)), frames))
            if len(combos) > 20:
                combos = [combos[i] for i in rng.choice(len(combos), 20, replace=False)]
            tries = {"different photos": [list(combo) for combo in combos], "one photo": [[index] * frames for index in range(len(group))]}
            for label, groups in tries.items():
                for combo in groups:
                    marked = accepted_c[combo].all() and len(set(named_c[combo])) == 1 and top_c[combo].mean() >= confirm_score
                    if person in members:
                        counts[label][0] += int(marked and named_c[combo][0] == person)
                        counts[label][1] += int(marked and named_c[combo][0] != person)
                        counts[label][2] += 1
                    else:
                        counts[label][3] += int(marked)
                        counts[label][4] += 1
    return {label: {
        "member": 100 * c[0] / c[2], "wrong": 100 * c[1] / c[2], "member_tries": c[2],
        "outsider": 100 * c[3] / c[4], "outsider_tries": c[4],
    } for label, c in counts.items()}


def degradations():
    def shrink(face_px):
        def apply(image, box):
            scale = face_px / max(box[2], 1)
            small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            return cv2.imdecode(cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1], cv2.IMREAD_COLOR)
        return apply

    def motion(size):
        kernel = np.zeros((size, size), np.float32)
        kernel[size // 2, :] = 1.0 / size
        return lambda image, box: cv2.filter2D(image, -1, kernel)

    def gain(factor):
        return lambda image, box: np.clip(image.astype(np.float32) * factor, 0, 255).astype(np.uint8)

    conditions = {"original": lambda image, box: image}
    conditions.update({f"face {px}px wide": shrink(px) for px in (60, 45, 35, 25)})
    conditions.update({f"blur sigma {sigma}": (lambda image, box, s=sigma: cv2.GaussianBlur(image, (0, 0), s)) for sigma in (1.5, 3, 5)})
    conditions.update({f"motion {size}px": motion(size) for size in (9, 17)})
    conditions.update({f"light x{factor}": gain(factor) for factor in (0.5, 0.3, 0.2, 0.15, 1.7, 2.0, 2.5)})
    return conditions


def quality_report(rows, args):
    # Clean gallery, degraded probes. Shows what the scanner's quality gate (scan_problem) turns away
    # and how recognition holds up for what it lets through.
    items, matrix = gallery_for(rows)
    rng = random.Random(args.seed)
    probes = [row for row in rows if row["role"] in ("probe", "unknown")]
    rng.shuffle(probes)
    probes = probes[:args.quality_probes]
    images = [cv2.imread(str(row["path"])) for row in probes]
    boxes = [main_face(image)["box"] for image in images]
    known = np.array([row["role"] == "probe" for row in probes])
    truth = np.array([row["person"] for row in probes])
    print(f"\n{int(known.sum())} probes of enrolled people, {int((~known).sum())} of unknown people; threshold {settings.face_match_threshold}, margin {settings.face_match_margin}")
    print(f"{'condition':18s}{'no face':>9s}{'gated':>8s}   gate reasons{'':14s}{'named correctly: all':>22s}{'  let through':>14s}{'unknown named':>15s}")
    for name, degrade in degradations().items():
        usable, reasons, kept = [], {}, np.zeros(len(probes), dtype=bool)
        found = np.zeros(len(probes), dtype=bool)
        vectors = np.zeros((len(probes), matrix.shape[1]))
        for index, (image, box) in enumerate(zip(images, boxes)):
            degraded = degrade(image, box)
            face = main_face(degraded)
            if face is None:
                continue
            found[index] = True
            problem = scan_problem(cv2.cvtColor(degraded, cv2.COLOR_BGR2GRAY), face["box"])
            if problem:
                reasons[problem] = reasons.get(problem, 0) + 1
            kept[index] = problem is None
            vectors[index] = face["embedding"]
        scored = [dict(row, embedding=vectors[i]) for i, row in enumerate(probes)]
        named, top, accepted = outcomes(items, matrix, scored, settings.face_match_threshold, settings.face_match_margin)
        accepted &= found
        correct = accepted & (named == truth)
        through = kept & known
        reason_text = ", ".join(f"{key} {value}" for key, value in sorted(reasons.items())) or "-"
        print(f"{name:18s}{100 * (~found).mean():8.1f}%{100 * (found & ~kept).mean():7.1f}%   {reason_text:26s}{100 * correct[known].mean():21.1f}%{(100 * correct[through].mean() if through.any() else float('nan')):13.1f}%{100 * (accepted & kept)[~known].mean():14.1f}%", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--enroll", type=int, default=5, help="photos per person used as enrollment")
    parser.add_argument("--pool", type=int, default=0, help="photos per person set aside for enrollment; --enroll of them are used (see select)")
    parser.add_argument("--max-probes", type=int, default=10)
    parser.add_argument("--min-images", type=int, default=10, help="photos a person needs to be enrolled")
    parser.add_argument("--unknown", type=int, default=500, help="single-photo people used as unknown faces")
    parser.add_argument("--classes", type=int, default=20)
    parser.add_argument("--class-size", type=int, default=30)
    parser.add_argument("--cases", type=int, default=15, help="confusion cases to list")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--quality", action="store_true", help="run the degraded-face experiment instead of the accuracy report")
    parser.add_argument("--quality-probes", type=int, default=400)
    parser.add_argument("--cache", type=Path, default=ROOT / "eval_data" / "cache")
    args = parser.parse_args()

    rows = select(args.dataset, args)
    if not any(row["role"] == "enroll" for row in rows):
        sys.exit(f"No person in {args.dataset} has {args.min_images} photos. Lower --min-images.")
    args.cache.mkdir(parents=True, exist_ok=True)
    label = face_service.model_label()
    print(f"pipeline {label}; detector {settings.face_detector}; photos {len(rows)}")
    usable = embed_rows(rows, args.cache / f"{args.dataset.resolve().name}-{label}.pkl")
    print(f"face found in {len(usable)} of {len(rows)} photos ({len(rows) - len(usable)} without a detectable face are left out)")
    if args.quality:
        quality_report(usable, args)
    else:
        report(usable, args)


if __name__ == "__main__":
    main()
