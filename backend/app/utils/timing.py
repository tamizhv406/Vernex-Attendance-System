import json
import logging
import math
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings
from app.utils.time_utils import now_local

# Where the time of one face request goes, stage by stage. One JSON line per request in
# logs/timing.log and the latest requests in memory for /face/timings. Durations, sizes, counts and
# outcomes only: never a camera frame, a face vector, a name or a person id.
LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "timing.log"
logger = None
recent = deque(maxlen=5000)
current = ContextVar("face_timer", default=None)
# Stages that have run at least once in this process. A request that runs one for the first time
# paid for loading a model, so it is reported as a cold request and kept out of the warm numbers.
warmed = set()


class Timer:
    def __init__(self, kind):
        self.kind = kind
        self.started = time.perf_counter()
        self.stages = {}
        self.fields = {}
        self.cold = []

    def add(self, name, seconds):
        self.stages[name] = self.stages.get(name, 0.0) + seconds


def start(kind):
    timer = Timer(kind)
    current.set(timer)
    return timer


@contextmanager
def stage(name, model=False):
    # Times a block for the request being handled. Outside a request it does nothing.
    # model=True marks a stage that runs a model, so its first run is known to include the loading.
    timer = current.get()
    if timer is None:
        # Not a request (the warm-up at startup, a script). Nothing is timed, but a model that ran
        # here is loaded, so the first real request is not mistaken for a cold one.
        yield
        if model:
            warmed.add(name)
        return
    if model and name not in warmed:
        timer.cold.append(name)
    began = time.perf_counter()
    try:
        yield
        if model:
            warmed.add(name)
    finally:
        timer.add(name, time.perf_counter() - began)


def note(**fields):
    timer = current.get()
    if timer is not None:
        timer.fields.update(fields)


def finish(timer, outcome):
    # Closes the request's record. Returns it (milliseconds), so a caller can show or test it.
    current.set(None)
    record = {
        "time": now_local().isoformat(timespec="seconds"),
        "kind": timer.kind,
        "outcome": outcome,
        "cold": timer.cold,
        "total_ms": round((time.perf_counter() - timer.started) * 1000, 1),
        "stages_ms": {name: round(seconds * 1000, 1) for name, seconds in timer.stages.items()},
        **timer.fields,
    }
    recent.append(record)
    write(record)
    return record


def write(record):
    global logger
    if not settings.face_timing_log:
        return
    try:
        if logger is None:
            LOG_FILE.parent.mkdir(exist_ok=True)
            handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger = logging.getLogger("vernex.timing")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            logger.addHandler(handler)
        logger.info(json.dumps(record))
    except OSError as exc:
        # A full disk or a locked file must never stop attendance.
        print("timing log unavailable:", exc)


def percentile(values, share):
    # Nearest-rank percentile: a value that was really measured, never an interpolated one.
    ordered = sorted(values)
    return ordered[min(len(ordered), max(1, math.ceil(share * len(ordered)))) - 1]


def summarize(records):
    # {kind: {"requests": n, "cold_requests": n, "total_ms": {p50, p95, p99, max}, "stages_ms": {stage: {...}}}}
    # Cold requests (a model was loaded during them) are counted and left out of the percentiles.
    summary = {}
    for kind in sorted({record["kind"] for record in records}):
        rows = [record for record in records if record["kind"] == kind]
        warm = [record for record in rows if not record["cold"]]
        stages = {}
        for name in sorted({name for record in warm for name in record["stages_ms"]}):
            stages[name] = spread([record["stages_ms"][name] for record in warm if name in record["stages_ms"]])
        summary[kind] = {
            "requests": len(rows),
            "cold_requests": len(rows) - len(warm),
            "cold_total_ms": [record["total_ms"] for record in rows if record["cold"]],
            "total_ms": spread([record["total_ms"] for record in warm]),
            "stages_ms": stages,
        }
    return summary


def spread(values):
    if not values:
        return None
    return {"n": len(values), "p50": percentile(values, 0.50), "p95": percentile(values, 0.95), "p99": percentile(values, 0.99), "max": max(values)}
