# Face recognition evaluation

How the recognition numbers in the reports were measured, how to repeat them, and what they do and do
not say. Measured on 15 October 2026 with the code and settings of this branch (threshold 0.60,
margin 0.05, three agreeing looks averaging at least 0.75), Facenet512 with the YOLOv8n-face detector.

## What was measured, and what was not

- **Measured:** the app's own detector, crop, embedding model, gallery averaging and decision rules,
  on LFW (Labeled Faces in the Wild), a public research dataset of 13,233 press photos of 5,749 people.
- **Not measured:** this system on your camera, your rooms or your students. LFW photos are sharper,
  better lit and more varied than webcam frames of one classroom. Real-camera results need
  `docs/REAL_CAMERA_TEST.md`; until then the numbers below describe the model and the rules, not the
  deployment.

## Method (reproducible)

1. Download LFW (`lfw.tgz`, 180 MB, from https://ndownloader.figshare.com/files/5976018) and unpack it
   outside the repository. One folder per person, as `scripts/evaluate_recognition.py` expects.
2. Selection, fixed by `--seed 0`: every person with at least 10 photos (158 people) is enrolled from
   5 of them, the way enrollment stores 5 poses; up to 10 other photos of each are the genuine probes
   (1,379); 500 people with a single photo are the unknown faces that must never be named.
3. Accuracy report:

   ```powershell
   cd backend
   .venv\Scripts\python scripts\evaluate_recognition.py <path>\lfw --cache <scratch folder>
   ```

   Running it twice gives byte-identical output (checked).
4. Held-out choice of settings: `scripts\evaluate_heldout.py <path>\lfw --cache <same folder> --angles`.
   The 158 people are split in two by a fixed seed; settings are searched on one half and judged on
   the other, whose people never influenced the choice.
5. Conditions: `evaluate_recognition.py --quality` (light, blur, face size) and
   `scripts\benchmark_multiface.py <path>\lfw` (1 to 10 faces per frame, real models).

## Results

### Accuracy (enrolled people)

| Measure | All 158 people | Held-out half (79) |
| --- | --- | --- |
| Named correctly from one frame (recall) | 99.13% | 99.57% |
| Named as another enrolled person | 0.00% | 0.00% |
| Marked present by the attendance rule (independent looks) | 96.13% | 96.17% |
| Marked present by the attendance rule (nearly identical frames, worst case) | 93.24% | 92.36% |
| Marked present as someone else | 0.000% | 0.000% |

### False rejects (an enrolled person not recognized)

| Measure | Value |
| --- | --- |
| One frame left "unknown" | 0.87% (all), 0.43% (held-out) |
| Not marked by the attendance rule | 3.9% (all, independent looks) to 7.6% (held-out, worst case) of attempts |
| Pairs of photos of the same person refused at 0.60 | 5.94% |

A student who is not marked can be marked by hand; the scanner says so.

### False accepts (a person who is not enrolled)

| Measure | Value |
| --- | --- |
| One frame given a name | 6.20% (all), 3.60% (held-out) |
| Marked present by the attendance rule, classes of 30 | 0.33% to 0.43% of walk-pasts (all); 0 of 27,137 (held-out) |
| Pairs of photos of different people accepted at 0.60 | 0.071% |
| Equal error rate (pairs) | 0.96% |

One frame naming a stranger is not a mark: a mark needs three agreeing looks, a live verdict on each
and the head-turn challenge. Precision of the attendance rule on the held-out half: 100%.

### Trade-off of the settings

On the validation half, raising the confirmation score from 0.75 to 0.80 cut non-members marked from
0.70% to 0.13% (worst case) and members marked from 93% to 86%. On the held-out half the stricter
setting gained nothing measurable (no non-member marked either way) and cost 12 to 14 points of
members, so 0.75 stays. `FACE_CONFIRM_SCORE=0.80` is the measured stricter option if a pilot shows
strangers being marked.

### Conditions (302 enrolled and 98 unknown probes, simulated on the LFW photos)

| Condition | Named correctly | Unknown named |
| --- | --- | --- |
| Original | 99.3% | 6.1% |
| Darker x0.5 / x0.3 / x0.2 | 99.3% / 98.7% / 93.4% | 6.1% / 3.1% / 1.0% |
| Brighter x1.7 / x2.0 / x2.5 | 96.0% / 90.4% / 71.9% | 5.1% / 3.1% / 1.0% |
| Face 60 / 45 / 35 / 25 px | 99.3% / 98.0% / 96.4% / 87.4% | up to 8.2% |
| Blur sigma 1.5 / 3 / 5 | 98.3% / 78.1% / 7.0% | up to 6.1% |
| Motion blur 9 / 17 px | 92.7% / 49.0% | up to 6.1% |
| Head turned 0 to 0.30 | 98.7% to 100% | 1.3% to 17.6% (17 photos in the last band) |
| 1, 2, 5, 10 faces per frame | 60 of 60 at 10 faces | 0 of 18 strangers named |

Degraded frames never raised the share of unknown faces given a name; very dark, bright or blurred
faces are turned away by the quality gate instead. The head-turn measure is unbiased (a mirrored photo
reads the opposite turn: correlation -0.992).

## Limitations

- LFW is not this camera, these students or these rooms. Children, uniforms, classroom lighting and a
  fixed webcam angle are not represented.
- Look-alikes and twins: two enrolled people who look alike may be refused as "unable to verify" or,
  in the worst case, confused; a duplicate check refuses enrolling the same face twice (98.1% caught,
  no different person refused, on LFW).
- Liveness (photo and screen detection) is not measured here and is not calibrated; see
  `docs/REAL_CAMERA_TEST.md` and `scripts/liveness_camera_test.py`. A prepared video fed into the
  browser can pass the head-turn challenge.
- No result here is 100%, and none should be claimed.
