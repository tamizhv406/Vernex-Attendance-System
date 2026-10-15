# Real-camera acceptance test

What no automated test can show: how the scanner does with **your camera, your room and your
students**. Run this before a pilot, and again after any change of camera, room or face settings.
It takes about an hour with 5 to 8 people. Everything in it stays on the computer.

## Before you start

- Every person in the test has agreed to it, in writing if your school requires that. Use test
  students in a test course and batch; delete them afterwards if they are not real students.
- The backend runs as it will in use (one process), with `FACE_SCAN_LOG=true` (the default), so
  that `backend/logs/recognition.log` records what the scanner decided.
- The console is opened over HTTPS (`npm run dev:https`, or the production setup in `deploy/`).
- Put the camera where it will be used, at the height and angle it will have.
- Have a clock everyone can see, and a copy of `docs/real_camera_attempts_template.csv` to fill in.

## 1. Enroll

Enroll 5 to 8 people with Face Enrollment, quick mode, on the camera that will be used. Note any
person who needed more than a minute, and what the screen said while they struggled.

## 2. Scan, one attempt at a time

Start a session for the test batch on Live Attendance. For every attempt write one row in the
attempts file: what kind it is, whose face it shows, and the clock time it started and ended.

| Kind | What to do | Must happen |
| --- | --- | --- |
| `enrolled` | An enrolled student walks up, holds still facing the camera, turns as the box says | Marked within about 30 s, as that student |
| `enrolled` (again, other people) | Glasses, a cap, a window behind, dim light, standing further back | Marked, or clearly asked to move; never marked as someone else |
| `stranger` | Someone who is not enrolled does everything the box says | Never named, never marked |
| `print` | A printed photo of a student who is **not marked yet** | Never marked |
| `screen` | A photo of such a student on a phone or tablet | Never marked |
| `video` | A video of such a student on a screen; try one where they turn their head | Never marked. If it is, note it: this is the attack the challenge cannot stop |
| `pair` | Two enrolled students side by side | Both marked, each as themselves |

A student is marked once per session, so a spoof attempt must show a student who is not marked
yet (or start a new session for it). Aim for at least 20 `enrolled`, 10 `stranger` and 5 of each
spoof kind: with fewer, a result of "none seen" still allows a real rate of 15% or more.

Finally restart the backend while the session runs and check that scanning carries on and an
enrolled student is still recognized.

## 3. Report

```powershell
cd backend
.venv\Scripts\python scripts\real_camera_report.py ..\docs\my_attempts.csv --session <session id>
```

It reads the session's records (read-only) and the scanner log, and prints for each attempt whether
the right student was marked and how long it took, then the totals: students marked, strangers
marked, each kind of attack marked, anyone marked as someone else, and how many attempts could not
be measured. For a kind with no failures it says the most the real rate can be (95% confidence).

## 4. Liveness calibration

Run `scripts\liveness_camera_test.py` (see its own help) with real faces and with the print,
screen and video attacks, and set `FACE_LIVENESS_THRESHOLD` and `FACE_LIVENESS_CONFIDENT` in
`backend\.env` from its report. Repeat step 2 for the attacks afterwards.

## Pass

- Every enrolled attempt marked as the right student, or (if not) the screen said why and a teacher
  could mark them by hand.
- No stranger marked. No print or screen marked. Nobody marked as someone else.
- Videos: any that got through are written down with the scanner log lines for them.
