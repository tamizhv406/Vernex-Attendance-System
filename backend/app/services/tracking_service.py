import secrets
import time

import numpy as np

from app.config import settings
from app.services.quality_service import MIN_HEAD_TURN

# A face seen again within this distance of where a track last was (as a share of the face's width)
# and at a similar size continues that track.
TRACK_MAX_SHIFT = 0.6
TRACK_SIZE_RANGE = (0.6, 1.67)
# A face can drop out for a frame or two (a blink of the detector, a hand passing). After this long
# without it the track is over, and whatever it had collected is thrown away with it.
TRACK_LOST_SECONDS = 2.0
SCANNER_IDLE_SECONDS = 60
MAX_TRACKS = 60
CONFIRM_WINDOW_SECONDS = 10
# Frames closer together than this show the same instant twice, so they count as one observation.
CONFIRM_GAP_SECONDS = 0.5
SPOOF_COOLDOWN_SECONDS = 3

# One entry per scanner (a camera looking at one attendance session). Tracks never cross scanners.
scanners = {}


def reset():
    scanners.clear()
    challenges.clear()


def scanner_state(key, now):
    for other in [name for name, state in scanners.items() if now - state["seen"] > SCANNER_IDLE_SECONDS]:
        del scanners[other]
    state = scanners.setdefault(key, {"tracks": [], "next_id": 1, "seen": now, "blocked": {}})
    state["seen"] = now
    return state


def assign_tracks(key, boxes, now=None):
    # Gives every box of this frame a track: the nearest live track it plausibly continues, or a new
    # one. Returns the tracks in the order of the boxes.
    #
    # A track never says who a face is. Every frame is identified on its own; the track only decides
    # which observations may be added up. So a wrong hand-over between two people who cross paths
    # cannot give one the other's name: the next frame names a different person and the count restarts.
    now = time.monotonic() if now is None else now
    state = scanner_state(key, now)
    state["tracks"] = [track for track in state["tracks"] if now - track["seen"] <= TRACK_LOST_SECONDS]
    state["blocked"] = {person: until for person, until in state["blocked"].items() if until > now}

    pairs = []
    for index, box in enumerate(boxes):
        for track in state["tracks"]:
            shift = distance(track["box"], box)
            if shift is not None:
                pairs.append((shift, index, track["id"]))
    assigned, taken = {}, set()
    for shift, index, track_id in sorted(pairs):
        if index in assigned or track_id in taken:
            continue
        assigned[index] = track_id
        taken.add(track_id)

    by_id = {track["id"]: track for track in state["tracks"]}
    result = []
    for index, box in enumerate(boxes):
        track = by_id.get(assigned.get(index))
        if track is None:
            track = {"id": state["next_id"], "person_id": None, "hits": [], "born": now}
            state["next_id"] += 1
            state["tracks"].append(track)
        track["box"] = [float(value) for value in box]
        track["seen"] = now
        result.append(track)
    # Far more tracks than faces a camera can show means something is wrong; the oldest go first.
    state["tracks"] = state["tracks"][-MAX_TRACKS:]
    return result


def distance(previous, box):
    # How far a box is from where a track last was, in face widths. None when it cannot be the same face.
    px, py, pw, ph = previous
    x, y, w, h = box
    size = max(pw, w, 1)
    if not TRACK_SIZE_RANGE[0] <= (w + 1) / (pw + 1) <= TRACK_SIZE_RANGE[1]:
        return None
    shift = float(np.hypot((x + w / 2) - (px + pw / 2), (y + h / 2) - (py + ph / 2))) / size
    return shift if shift <= TRACK_MAX_SHIFT else None


def clear(track):
    track["person_id"] = None
    track["hits"] = []
    track["challenge"] = None


def observe(key, track, person_id, score=1.0, live=True, now=None, count=True):
    # One usable look at the face on this track: who it was identified as (None when it could not be
    # named: unknown or ambiguous) and whether it looked live.
    # Returns True once the evidence on THIS track is enough to mark that person.
    #
    # The rule: the last face_confirm_frames separate observations of this one face must all name the
    # same person, all look live, and their average score must reach face_confirm_score. Anything that
    # contradicts the run (another name, no name, a photo) ends it and counting starts again.
    now = time.monotonic() if now is None else now
    state = scanner_state(key, now)
    if person_id is None:
        clear(track)
        return False
    if not live:
        # A photo must not collect hits a lucky frame at a time. The pause is per person as well as
        # per track, so moving the photo to get a fresh track does not help.
        clear(track)
        state["blocked"][person_id] = now + SPOOF_COOLDOWN_SECONDS
        return False
    if state["blocked"].get(person_id, 0) > now:
        clear(track)
        return False
    if track["person_id"] != person_id:
        clear(track)
        track["person_id"] = person_id
    hits = [hit for hit in track["hits"] if now - hit[0] <= CONFIRM_WINDOW_SECONDS]
    if not count:
        # A look that is checked against the run (same person, live) without adding to it:
        # a head turned for the challenge scores lower than a straight face and would only
        # drag the average down.
        pass
    elif hits and now - hits[-1][0] < CONFIRM_GAP_SECONDS:
        # The same instant seen twice is one observation. It keeps the weaker score, so sending
        # frames faster can never make a match look better than it is.
        hits[-1] = (hits[-1][0], min(hits[-1][1], score))
    else:
        hits.append((now, score))
    track["hits"] = hits
    return len(hits) >= settings.face_confirm_frames and track_score(track) >= settings.face_confirm_score


def track_score(track):
    # Average score of the latest observations: the confidence stored with the attendance record.
    scores = [score for _, score in track["hits"][-settings.face_confirm_frames:]]
    return float(np.mean(scores)) if scores else 0.0


def progress(track):
    return min(len(track["hits"]), settings.face_confirm_frames)


# ---- The head-turn challenge: is the person in front of the camera answering right now? ----
#
# A still picture cannot turn its head, and a recording cannot know which way it will be asked to
# turn. Each student gets one direction per session, picked at random; the answer has to come from
# the same tracked face that is being identified, while it keeps matching that student and keeps
# looking live. It is a second, separate question from "who is this": passing it marks nobody
# whose identity has not been confirmed, and it is asked of every face on its own.

# Eye shift inside the face box (see face_service.head_turn). A turn is measured from the face's own
# starting pose, not from zero: a student who reads the screen beside the camera faces the camera at
# an angle all the time, and an absolute "straight" was never reached by the one real student tested
# (turn 0.17 to 0.24 for the whole attempt, 15 October 2026). The starting pose is wherever the face
# holds still (within CHALLENGE_STEADY for CHALLENGE_STEADY_SECONDS) after the instruction appears,
# provided it roughly faces the camera (CHALLENGE_START_MAX); the answer is a further turn of at least
# CHALLENGE_TURN from there. A face turned the wrong way only fails once it points past
# CHALLENGE_STRAIGHT to the wrong side; coming back towards the camera is simply a new starting pose.
CHALLENGE_STRAIGHT = 0.04
CHALLENGE_TURN = 0.08
CHALLENGE_START_MAX = 0.25
CHALLENGE_STEADY = 0.03
CHALLENGE_STEADY_SECONDS = 0.4
# A real head that turns keeps the shape of its face box. A flat photo that is tilted to shift the
# eyes gets a visibly narrower box. A "turn" whose box changed by more than this is not a head turning.
# It never passes. It is not counted as a wrong answer either: a real person who leans in or moves
# while turning changes the box too (the real test of 28 October 2026 locked a genuine, enrolled
# person that way), so it is answered "retry", with the same wipe and pause as a wrong answer.
CHALLENGE_BOX_CHANGE = 0.10
# So that a flat picture cannot be tilted again and again without end, this many retries in one
# session lock the student exactly as CHALLENGE_MAX_FAILURES wrong answers do.
CHALLENGE_MAX_RETRIES = 6
# Time to answer after the instruction appears. Running out of time is not held against anyone:
# the same instruction simply starts again (with the direction fixed, waiting gains an attacker nothing).
CHALLENGE_SECONDS = 10
# How long a passed challenge stays good while the identity looks are still being collected.
CHALLENGE_PASS_SECONDS = 15
# Wrong answers (turning the other way, or a tilted flat picture) before the student is locked,
# and for how long. A locked student is marked by the teacher.
CHALLENGE_MAX_FAILURES = 3
CHALLENGE_LOCK_SECONDS = 120
CHALLENGE_FORGET_SECONDS = 12 * 3600

# (session, person) -> the direction asked of that student in that session, and their wrong answers.
# Shared by all scanners, so a second camera does not hand out a second chance at another direction.
challenges = {}


def pick_direction():
    return secrets.choice(("left", "right"))


def challenge_entry(session_id, person_id, now):
    for stale in [name for name, entry in challenges.items() if now - entry["created"] > CHALLENGE_FORGET_SECONDS]:
        del challenges[stale]
    entry = challenges.get((session_id, person_id))
    if entry is None:
        entry = challenges[(session_id, person_id)] = {"direction": pick_direction(), "failures": 0, "retries": 0, "locked_until": 0.0, "created": now}
    return entry


def verify(key, track, person_id, score, now, turn=None, box=None, challenge=True):
    # One look at a face that was identified as person_id and judged live. Returns where this face
    # stands: "confirmed" (may be marked), "pending" (identity looks still being collected),
    # "straight" / "turn" (what the face has to do next for the challenge), "retry", "failed" or "locked".
    session_id = key[0]
    if not challenge:
        return "confirmed" if observe(key, track, person_id, score, True, now) else "pending"
    entry = challenge_entry(session_id, person_id, now)
    if entry["locked_until"] > now:
        clear(track)
        return "locked"
    # A look counts towards the identity unless it is the turn that answers the challenge: turned
    # away from this face's starting pose, not merely turned. A student who faces the camera at an
    # angle all the time is still identified.
    state = track.get("challenge")
    start = state["base"] if state and state["person_id"] == person_id and state.get("base") is not None else None
    turned = turn is not None and start is not None and abs(turn - start) >= MIN_HEAD_TURN
    identity = observe(key, track, person_id, score, True, now, count=not turned)
    if track["person_id"] != person_id:
        # Paused after a photo or a wrong answer: nothing is collected for now.
        return "pending"
    answer = respond(key, track, entry, person_id, turn, box, now)
    if answer == "passed":
        return "confirmed" if identity else "pending"
    return answer


def respond(key, track, entry, person_id, turn, box, now):
    state = track.get("challenge")
    if state is None or state["person_id"] != person_id or now - state["started"] > (CHALLENGE_PASS_SECONDS if state["passed_at"] else CHALLENGE_SECONDS):
        state = track["challenge"] = {"person_id": person_id, "stage": "straight", "started": now, "base": None, "shape": None, "steady": None, "passed_at": None}
    if state["passed_at"] is not None:
        return "passed"
    if turn is None or box is None:
        # The detector gave no eye points, so a turn cannot be seen. Nothing is assumed.
        return state["stage"]
    shape = box[2] / max(box[3], 1)
    if state["stage"] == "straight":
        # The answer must begin from a pose held still after the instruction was given, so a head
        # that is already turned, or still moving, is not an answer: it only becomes the start.
        steady = state["steady"]
        if abs(turn) > CHALLENGE_START_MAX:
            state["steady"] = None
        elif steady is None or abs(turn - steady["turn"]) > CHALLENGE_STEADY:
            state["steady"] = {"turn": turn, "shape": shape, "since": now}
        elif now - steady["since"] >= CHALLENGE_STEADY_SECONDS:
            # The time to answer runs from the moment the turn is asked for.
            state.update(stage="turn", base=steady["turn"], shape=steady["shape"], started=now)
        return state["stage"]
    # How far the face has turned from its starting pose in the direction asked for (negative: the
    # other way), and where it points now, measured the same way.
    sign = 1 if entry["direction"] == "left" else -1
    wanted, pointing = sign * (turn - state["base"]), sign * turn
    box_change = abs(shape / state["shape"] - 1)
    if wanted >= CHALLENGE_TURN and box_change <= CHALLENGE_BOX_CHANGE:
        state.update(passed_at=now, started=now)
        return "passed"
    if wanted <= -CHALLENGE_TURN and pointing > -CHALLENGE_STRAIGHT:
        # Back towards the camera from a starting pose that was turned the way asked for: not the
        # wrong way yet. This becomes the new starting pose once it is held still.
        state.update(stage="straight", base=None, shape=None, steady={"turn": turn, "shape": shape, "since": now}, started=now)
        return "straight"
    if abs(wanted) < CHALLENGE_TURN:
        return "turn"
    # Why this answer did not count, in numbers only, for the scanner's log (face_routes).
    track["challenge_note"] = {"reason": "wrong_direction" if wanted < 0 else "box_changed", "turned": round(float(wanted), 4), "box_change": round(float(box_change), 4)}
    # Turned the other way: a wrong answer. Turned the right way but the box changed shape: not an
    # answer at all (see CHALLENGE_BOX_CHANGE). Either way what was collected is wiped and paused.
    counter, limit, result = ("failures", CHALLENGE_MAX_FAILURES, "failed") if wanted < 0 else ("retries", CHALLENGE_MAX_RETRIES, "retry")
    entry[counter] = entry.get(counter, 0) + 1
    scanner_state(key, now)["blocked"][person_id] = now + SPOOF_COOLDOWN_SECONDS
    clear(track)
    if entry[counter] >= limit:
        entry.update(failures=0, retries=0, locked_until=now + CHALLENGE_LOCK_SECONDS)
        return "locked"
    return result
