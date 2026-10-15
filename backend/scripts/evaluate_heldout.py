"""Choose the face settings on some people and judge them on others, and see how head angle matters.

    python scripts/evaluate_heldout.py DATASET [--angles] [--target-outsider 0.10]

Runs after scripts/evaluate_recognition.py on the same DATASET (it reuses that script's selection,
seed and cached embeddings, so the photos and vectors are the same). The enrolled people are split in
two halves by a fixed seed: settings are searched on the validation half only (threshold x
confirmation score, margin 0.05) and the chosen setting and the current one are then measured on the
test half, whose people never influenced the choice. This is what makes the numbers honest: a
setting tuned and judged on the same people looks better than it is.

--angles groups every probe by how far its head is turned (face_service.head_turn) and reports
recognition per group, plus whether the turn measure is symmetric (a mirrored photo should read the
opposite turn). Nothing is written to any database.
"""
import argparse
import itertools
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import evaluate_recognition as er  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import face_service  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / "eval_data" / "cache")
    parser.add_argument("--target-outsider", type=float, default=0.10, help="largest acceptable share (percent) of non-members marked, worst case, on the validation half")
    parser.add_argument("--angles", action="store_true")
    cli = parser.parse_args()

    # The same selection as evaluate_recognition.py with its defaults.
    args = SimpleNamespace(enroll=5, pool=0, max_probes=10, min_images=10, unknown=500, classes=20, class_size=30, seed=0)
    rows = er.select(cli.dataset, args)
    usable = er.embed_rows(rows, cli.cache / f"{cli.dataset.resolve().name}-{face_service.model_label()}.pkl")
    print(f"photos with a face: {len(usable)}")

    people = sorted({row["person"] for row in usable if row["role"] == "enroll"})
    random.Random(1).shuffle(people)
    halves = {"validation": set(people[: len(people) // 2]), "test": set(people[len(people) // 2:])}
    unknowns = [row for row in usable if row["role"] == "unknown"]
    unknown_halves = {"validation": unknowns[0::2], "test": unknowns[1::2]}

    def part(name):
        return [row for row in usable if row["role"] in ("enroll", "probe", "spare") and row["person"] in halves[name]] + unknown_halves[name]

    def decision(data, threshold, confirm):
        probes = [row for row in data if row["role"] in ("probe", "unknown")]
        return er.attendance_decision(data, probes, args, threshold, 0.05, confirm)

    validation, test = part("validation"), part("test")
    print(f"validation: {len(halves['validation'])} people, {len(unknown_halves['validation'])} unknown; test: {len(halves['test'])} people, {len(unknown_halves['test'])} unknown")
    print("\n== Validation half: members marked / non-members marked, worst case ('one photo') and best case ('different photos') ==")
    grid = []
    for threshold, confirm in itertools.product((0.55, 0.60, 0.65, 0.70), [round(0.70 + 0.01 * i, 2) for i in range(13)]):
        numbers = decision(validation, threshold, confirm)
        grid.append((threshold, confirm, numbers))
        current = "  <- current" if (threshold, confirm) == (settings.face_match_threshold, settings.face_confirm_score) else ""
        print(f" threshold {threshold:.2f} confirm {confirm:.2f} | one photo {numbers['one photo']['member']:6.2f}% / {numbers['one photo']['outsider']:6.3f}% | different {numbers['different photos']['member']:6.2f}% / {numbers['different photos']['outsider']:6.3f}%{current}")
    ok = [item for item in grid if item[2]["one photo"]["outsider"] <= cli.target_outsider]
    best = max(ok, key=lambda item: (item[2]["one photo"]["member"], item[2]["different photos"]["member"])) if ok else None

    print("\n== Test half (people never used for the choice) ==")
    choices = [("current", settings.face_match_threshold, settings.face_confirm_score)]
    if best:
        choices.append((f"best on validation with non-members <= {cli.target_outsider}%", best[0], best[1]))
    for label, threshold, confirm in choices:
        items, matrix = er.gallery_for(test)
        probes = [row for row in test if row["role"] in ("probe", "unknown")]
        known = np.array([row["role"] == "probe" for row in probes])
        truth = np.array([row["person"] for row in probes])
        named, _, accepted = er.outcomes(items, matrix, probes, threshold, 0.05)
        correct, wrong = accepted & (named == truth), accepted & (named != truth)
        tp, fp = int(correct[known].sum()), int(wrong[known].sum() + accepted[~known].sum())
        print(f"-- {label}: threshold {threshold:.2f}, confirm {confirm:.2f}")
        print(f"   one frame: recall {100 * correct[known].mean():.2f}%, named as another {100 * wrong[known].mean():.2f}%, unknown named {100 * accepted[~known].mean():.2f}%, precision {100 * tp / max(tp + fp, 1):.2f}% ({int(known.sum())} probes, {int((~known).sum())} unknown)")
        for kind, n in decision(test, threshold, confirm).items():
            tp = n["member"] / 100 * n["member_tries"]
            fp = n["wrong"] / 100 * n["member_tries"] + n["outsider"] / 100 * n["outsider_tries"]
            print(f"   attendance ({kind}): members marked {n['member']:.2f}%, as someone else {n['wrong']:.3f}%, non-members marked {n['outsider']:.3f}% "
                  f"of {n['outsider_tries']} tries, precision {100 * tp / max(tp + fp, 1e-9):.2f}%")

    if cli.angles:
        angles(usable)


def angles(usable):
    def centre_face(image):
        faces = face_service.locate_faces(image)
        if not faces:
            return None
        h, w = image.shape[:2]
        return min(faces, key=lambda f: (f["box"][0] + f["box"][2] / 2 - w / 2) ** 2 + (f["box"][1] + f["box"][3] / 2 - h / 2) ** 2)

    print("\n== By head angle (every probe, everyone enrolled, current settings, one frame) ==")
    items, matrix = er.gallery_for(usable)
    probes = [row for row in usable if row["role"] in ("probe", "unknown")]
    turns, aspects = [], []
    for row in probes:
        face = centre_face(cv2.imread(str(row["path"])))
        turns.append(face["turn"] if face and face["turn"] is not None else np.nan)
        aspects.append(face["box"][2] / max(face["box"][3], 1) if face else np.nan)
    turns, aspects = np.array(turns), np.array(aspects)
    known = np.array([row["role"] == "probe" for row in probes])
    truth = np.array([row["person"] for row in probes])
    named, _, accepted = er.outcomes(items, matrix, probes, settings.face_match_threshold, settings.face_match_margin)
    correct = accepted & (named == truth)
    for low, high in ((0, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.20), (0.20, 0.30)):
        band = (np.abs(turns) >= low) & (np.abs(turns) < high)
        k, u = band & known, band & ~known
        print(f" |turn| {low:.2f}-{high:.2f}: {int(k.sum())} probes, named correctly {100 * correct[k].mean() if k.any() else float('nan'):.2f}%, "
              f"as another {100 * (accepted & (named != truth))[k].mean() if k.any() else float('nan'):.2f}%, {int(u.sum())} unknown, unknown named {100 * accepted[u].mean() if u.any() else float('nan'):.2f}%, "
              f"face box w/h {np.nanmedian(aspects[band]) if band.any() else float('nan'):.3f}")
    pairs = []
    for row in random.Random(3).sample(probes, min(300, len(probes))):
        image = cv2.imread(str(row["path"]))
        a, b = centre_face(image), centre_face(cv2.flip(image, 1))
        if a and b and a["turn"] is not None and b["turn"] is not None:
            pairs.append((a["turn"], b["turn"]))
    pairs = np.array(pairs)
    print(f" mirror test, {len(pairs)} photos: correlation {np.corrcoef(pairs[:, 0], pairs[:, 1])[0, 1]:.3f} (ideal -1), mean of the two {pairs.sum(axis=1).mean():+.4f} (ideal 0)")


if __name__ == "__main__":
    main()
