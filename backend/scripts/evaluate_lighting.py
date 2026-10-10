"""How lighting changes what the scanner sees, and whether brightening the picture first would help.

    python scripts/evaluate_lighting.py DATASET [--people 40] [--strangers 40]

An experiment, not a change to the application: nothing here is used by the running system and no
stored face is touched.

People are enrolled from three photos each as they are (taken in ordinary light). A fourth photo of
each, and photos of people who are not enrolled, are then relit in software:

  normal    as photographed
  dim       35% of the light
  very_dim  15% of the light
  bright    190% of the light, burnt out where it clips
  backlit   face in shadow (30%), surroundings brighter (150%)
  uneven    light falling from one side (25% on the dark side)

and identified three ways:

  none   the picture as it is (what the application does today)
  gamma  brightened or darkened towards mid-grey before detection (the same step on enrollment photos)
  clahe  local contrast equalised (CLAHE on the lightness channel), also on enrollment photos

For every combination: was a face found, did the scanner's quality gate accept it, was the person
named correctly, wrongly, or not at all, and how many strangers were given somebody's name.

What this is and is not: relighting a photo in software is not a dark classroom. A real camera in
poor light also adds noise and motion blur, which this does not. It shows the direction and rough
size of the effect on these models; a decision about preprocessing needs real camera frames.
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["FACE_SCAN_LOG"] = "false"
os.environ["FACE_TIMING_LOG"] = "false"

import cv2
import numpy as np

from app.config import settings
from app.services import face_service, quality_service

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def scaled(image, factor):
    return np.clip(image.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def backlit(image):
    height, width = image.shape[:2]
    mask = np.zeros((height, width), np.float32)
    cv2.ellipse(mask, (width // 2, height // 2), (int(width * 0.28), int(height * 0.36)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), width * 0.04)[..., None]
    return np.clip(image.astype(np.float32) * (0.3 * mask + 1.5 * (1 - mask)), 0, 255).astype(np.uint8)


def uneven(image):
    ramp = np.linspace(0.25, 1.0, image.shape[1], dtype=np.float32)[None, :, None]
    return np.clip(image.astype(np.float32) * ramp, 0, 255).astype(np.uint8)


CONDITIONS = {
    "normal": lambda image: image,
    "dim": lambda image: scaled(image, 0.35),
    "very_dim": lambda image: scaled(image, 0.15),
    "bright": lambda image: scaled(image, 1.9),
    "backlit": backlit,
    "uneven": uneven,
}


def gamma_to_mid_grey(image):
    mean = float(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).mean()) / 255
    if mean <= 0.01 or mean >= 0.99:
        return image
    gamma = float(np.clip(np.log(0.47) / np.log(mean), 0.4, 2.5))
    table = (np.linspace(0, 1, 256) ** gamma * 255).astype(np.uint8)
    return cv2.LUT(image, table)


def clahe(image):
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


VARIANTS = {"none": lambda image: image, "gamma": gamma_to_mid_grey, "clahe": clahe}


def photos_of(folder):
    return sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_TYPES)


def main_face(image):
    faces = face_service.detect_faces(image)
    if not faces:
        return None
    height, width = image.shape[:2]
    return min(faces, key=lambda face: (face["box"][0] + face["box"][2] / 2 - width / 2) ** 2 + (face["box"][1] + face["box"][3] / 2 - height / 2) ** 2)


class Stored:
    def __init__(self, person_id, vector):
        self.person_id, self.embedding_vector = person_id, json.dumps(vector)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--people", type=int, default=40)
    parser.add_argument("--strangers", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    folders = sorted(path for path in args.dataset.iterdir() if path.is_dir())
    rich = [folder for folder in folders if len(photos_of(folder)) >= 4]
    single = [folder for folder in folders if len(photos_of(folder)) == 1]
    rng.shuffle(rich)
    rng.shuffle(single)
    face_service.warm_up()
    print(f"threshold {settings.face_match_threshold}, margin {settings.face_match_margin}; quality gate brightness {quality_service.BRIGHTNESS_SCAN}, focus >= {quality_service.MIN_FOCUS_SCAN}")

    report = {}
    for variant, prepare in VARIANTS.items():
        # The same preparation on the enrollment photos as on the scanned ones.
        rows, probes = [], {}
        for folder in rich:
            if len(probes) == args.people:
                break
            photos = photos_of(folder)
            faces = [main_face(prepare(cv2.imread(str(path)))) for path in photos[:3]]
            if any(face is None for face in faces):
                continue
            person_id = len(probes) + 1
            rows += [Stored(person_id, face["embedding"]) for face in faces]
            probes[person_id] = photos[3]
        gallery = face_service.build_gallery(rows)
        strangers = [photos_of(folder)[0] for folder in single[:args.strangers]]
        report[variant] = {}
        for condition, relight in CONDITIONS.items():
            tally = {"enrolled": 0, "found": 0, "gate_ok": 0, "correct": 0, "wrong": 0, "ambiguous": 0, "unknown": 0, "correct_and_gate_ok": 0, "wrong_and_gate_ok": 0, "gate": {}, "strangers": 0, "strangers_named": 0, "strangers_named_and_gate_ok": 0, "brightness": [], "focus": [], "confidence": [], "score": []}
            for person_id, path in list(probes.items()) + [(None, path) for path in strangers]:
                image = prepare(relight(cv2.imread(str(path))))
                tally["enrolled" if person_id else "strangers"] += 1
                face = main_face(image)
                if face is None:
                    continue
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                x, y, w, h = face["box"]
                brightness, _, focus = quality_service.face_measures(gray[max(y, 0): y + h, max(x, 0): x + w])
                problem = quality_service.scan_problem(gray, face["box"])
                answer = face_service.identify(face["embedding"], gallery)
                named = answer["embedding"].person_id if answer["status"] == "matched" else None
                if person_id is None:
                    tally["strangers_named"] += named is not None
                    tally["strangers_named_and_gate_ok"] += named is not None and problem is None
                    continue
                tally["found"] += 1
                tally["gate_ok"] += problem is None
                tally["gate"][problem or "ok"] = tally["gate"].get(problem or "ok", 0) + 1
                outcome = "correct" if named == person_id else "wrong" if named is not None else answer["status"]
                tally[outcome] += 1
                if problem is None and outcome in ("correct", "wrong"):
                    tally[f"{outcome}_and_gate_ok"] += 1
                tally["brightness"].append(brightness)
                tally["focus"].append(focus)
                tally["confidence"].append(face["detection_confidence"])
                if named == person_id:
                    tally["score"].append(answer["confidence"])
            for name in ("brightness", "focus", "confidence", "score"):
                tally[name] = round(float(np.median(tally[name])), 4) if tally[name] else None
            report[variant][condition] = tally
            print(f"{variant:6s} {condition:9s} found {tally['found']}/{tally['enrolled']}  gate ok {tally['gate_ok']}  named right {tally['correct']} (of gate-ok: {tally['correct_and_gate_ok']})  wrong {tally['wrong']}  ambiguous {tally['ambiguous']}  unknown {tally['unknown']}  strangers named {tally['strangers_named']}/{tally['strangers']} (gate-ok {tally['strangers_named_and_gate_ok']})  median brightness {tally['brightness']} focus {tally['focus']} detector confidence {tally['confidence']} score {tally['score']}  gate {tally['gate']}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
