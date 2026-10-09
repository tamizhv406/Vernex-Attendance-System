from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.timing import Timing
from app.schemas.timing_schema import TimingCreate, TimingUpdate
from app.serializers import timing_data

router = APIRouter(prefix="/timings", tags=["Timings"])


@router.post("/create")
def create_timing(payload: TimingCreate, db: Session = Depends(get_db)):
    item = Timing(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"success": True, "message": "Created successfully", "data": timing_data(item)}


@router.get("")
def list_timings(db: Session = Depends(get_db)):
    rows = db.query(Timing).all()
    return {"success": True, "message": "Timings fetched", "data": [timing_data(row) for row in rows]}


@router.get("/{timing_id}")
def get_timing(timing_id: int, db: Session = Depends(get_db)):
    item = db.get(Timing, timing_id)
    if not item:
        raise HTTPException(404, "Timing not found")
    return {"success": True, "message": "Timing fetched", "data": timing_data(item)}


@router.put("/{timing_id}")
def update_timing(timing_id: int, payload: TimingUpdate, db: Session = Depends(get_db)):
    item = db.get(Timing, timing_id)
    if not item:
        raise HTTPException(404, "Timing not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return {"success": True, "message": "Updated successfully", "data": timing_data(item)}


@router.delete("/{timing_id}")
def delete_timing(timing_id: int, db: Session = Depends(get_db)):
    item = db.get(Timing, timing_id)
    if not item:
        raise HTTPException(404, "Timing not found")
    db.delete(item)
    db.commit()
    return {"success": True, "message": "Deleted successfully", "data": None}
