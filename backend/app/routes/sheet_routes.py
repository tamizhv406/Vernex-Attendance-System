from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.attendance import AttendanceRecord
from app.services.sheet_service import sync_attendance_record

router = APIRouter(prefix="/sheet", tags=["Google Sheet"])


@router.post("/sync-pending")
def sync_pending(db: Session = Depends(get_db)):
    rows = db.query(AttendanceRecord).filter(AttendanceRecord.sync_status == "pending").all()
    for row in rows:
        sync_attendance_record(db, row)
    return {"success": True, "message": f"Sync attempted for {len(rows)} records", "data": {"count": len(rows)}}


@router.get("/status")
def sheet_status():
    return {"success": True, "message": "Sheet status fetched", "data": {"configured": bool(settings.google_script_url), "url_set": bool(settings.google_script_url)}}
