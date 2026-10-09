import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings
from app.utils.time_utils import now_local

LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "recognition.log"
logger = None


def log_decision(**fields):
    # One JSON line per scanner decision, enough to work out afterwards why a face was (or was not)
    # marked. It holds ids, scores and sizes. It never holds a camera frame or a face vector.
    global logger
    if not settings.face_scan_log:
        return
    try:
        if logger is None:
            LOG_FILE.parent.mkdir(exist_ok=True)
            handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger = logging.getLogger("vernex.recognition")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            logger.addHandler(handler)
        logger.info(json.dumps({"time": now_local().isoformat(timespec="seconds"), **fields}))
    except OSError as exc:
        # A full disk or a locked file must never stop attendance.
        print("recognition log unavailable:", exc)
