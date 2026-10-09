import json
import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sync_log import SheetSyncLog
from app.utils.time_utils import now_local


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
    log = SheetSyncLog(attendance_record_id=record.id, sheet_name="attendance", sync_status="pending", request_payload=json.dumps(payload), last_attempt_at=now_local())
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
