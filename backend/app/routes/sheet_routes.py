from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.services.sheet_service import send_if_pending

router = APIRouter(prefix="/sheet", tags=["Google Sheet"])


@router.post("/sync-pending")
def sync_pending(db: Session = Depends(get_db)):
    rows = db.query(AttendanceRecord).filter(AttendanceRecord.sync_status == "pending").all()
    # count: records this request sent. skipped: pending when listed, but being sent by the worker or
    # another request at that moment, or already sent by it.
    sent = sum(send_if_pending(db, row) for row in rows)
    return {"success": True, "message": f"Sync attempted for {sent} records", "data": {"count": sent, "skipped": len(rows) - sent}}


@router.get("/status")
def sheet_status():
    return {"success": True, "message": "Sheet status fetched", "data": {"configured": bool(settings.google_script_url), "url_set": bool(settings.google_script_url)}}
