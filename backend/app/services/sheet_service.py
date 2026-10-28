import json
import queue
import threading

import requests
from sqlalchemy.orm import Session

from app import database
from app.config import settings
from app.models.attendance import AttendanceRecord
from app.models.sync_log import SheetSyncLog
from app.utils.time_utils import now_local

# New marks waiting to be written to the sheet, by record id. One thread sends them, one at a time.
# A mark never waits for the sheet: until October 2026 it did, for up to 8 seconds, and a face scan
# held up every other request of the backend while it waited.
MAX_WAITING = 1000
_waiting = queue.Queue(maxsize=MAX_WAITING)
_sender = None
_sender_lock = threading.Lock()
# Records being sent right now, by the worker or by POST /sheet/sync-pending. A record is claimed under
# the lock before it is sent, so two senders never send the same one at once (until October 2026 an
# admin's "sync pending" during the worker's send wrote it to the sheet twice). In memory, because the
# backend is one process; a status in the database would leave a record stuck if the backend stopped mid-send.
_sending = set()
_sending_lock = threading.Lock()


def send_if_pending(db: Session, record) -> bool:
    """Sends one record to the sheet, unless another sender has it right now or it is no longer pending.

    True when it was sent (whatever the sheet answered). The one way the worker and the route send.
    """
    with _sending_lock:
        if record.id in _sending:
            return False
        _sending.add(record.id)
    try:
        # Read again once claimed: the other sender may have finished with it just before.
        db.refresh(record)
        if record.sync_status != "pending":
            return False
        sync_attendance_record(db, record)
        return True
    finally:
        with _sending_lock:
            _sending.discard(record.id)


def queue_attendance_record(db: Session, record):
    """After a new mark: the sheet is written in the background, and the mark is answered at once.

    The record stays "pending" until the sheet answers, as when the sheet could not be reached. One
    that never gets an answer (more than MAX_WAITING waiting, or the backend stopped) is sent again by
    POST /sheet/sync-pending, like every record the sheet could not take.
    """
    if not settings.google_script_url:
        sync_attendance_record(db, record)
        return
    try:
        _waiting.put_nowait(record.id)
    except queue.Full:
        print("sheet sync: more than", MAX_WAITING, "marks waiting; record", record.id, "stays pending")
        return
    _start_sender()


def _start_sender():
    global _sender
    with _sender_lock:
        if _sender is None or not _sender.is_alive():
            _sender = threading.Thread(target=_send_waiting, name="sheet-sync", daemon=True)
            _sender.start()


def _send_waiting():
    while True:
        record_id = _waiting.get()
        try:
            # A session of its own: the request that made the mark has long been answered.
            with database.SessionLocal() as db:
                record = db.get(AttendanceRecord, record_id)
                if record is not None:
                    send_if_pending(db, record)
        except Exception as exc:
            # The record stays pending; the reason is in the backend's output.
            print("sheet sync of record", record_id, "failed:", type(exc).__name__, exc)
        finally:
            _waiting.task_done()


def wait_until_sent(timeout: float = 30) -> bool:
    """True once every queued mark has had its answer from the sheet. For tests and tools."""
    finished = threading.Event()
    threading.Thread(target=lambda: (_waiting.join(), finished.set()), daemon=True).start()
    return finished.wait(timeout)


def sync_attendance_record(db: Session, record):
    if not settings.google_script_url:
        record.sync_status = "not_required"
        db.commit()
        return {"success": True, "message": "Google Script URL not configured"}
    payload = {
        "action": f"update_{record.person_type}_attendance",
        "record": {
            "person_code": record.person_code,
            "person_name": record.person_name,
            "person_type": record.person_type,
            "category_program": record.category_program,
            "batch_name": record.batch_name,
            "attendance_date": str(record.attendance_date),
            "marked_time": record.marked_time.isoformat() if record.marked_time else None,
            "status": record.status,
        },
    }
    log = SheetSyncLog(attendance_record_id=record.id, sheet_name="attendance", sync_status="pending", request_payload=json.dumps(payload), last_attempt_at=now_local().replace(tzinfo=None))
    try:
        response = requests.post(settings.google_script_url, json=payload, timeout=8)
        record.sync_status = "synced" if response.ok else "failed"
        log.sync_status = record.sync_status
        log.response_message = response.text[:1000]
    except Exception as exc:
        record.sync_status = "pending"
        log.sync_status = "failed"
        log.error_message = str(exc)
    db.add(log)
    db.commit()
    return {"success": record.sync_status == "synced", "message": record.sync_status}
