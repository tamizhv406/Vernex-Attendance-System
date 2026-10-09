from datetime import date, datetime, time
from pydantic import BaseModel


class AttendanceSessionCreate(BaseModel):
    session_name: str
    session_type: str
    course_id: int
    batch_id: int
    category_program: str | None = None
    batch_name: str | None = None
    timing_id: int | None = None
    session_date: date | None = None
    start_time: time | None = None
    grace_time: time | None = None
    end_time: time | None = None


class AttendanceMark(BaseModel):
    session_id: int | None = None
    person_id: int | None = None
    person_code: str | None = None
    course_id: int | None = None
    batch_id: int | None = None
    confidence_score: float | None = None
    recognition_method: str = "face_ai"
    device_name: str | None = None
    marked_by: str | None = None
    notes: str | None = None


class AttendanceOut(BaseModel):
    id: int
    session_id: int | None
    person_id: int | None
    person_code: str | None
    person_name: str | None
    person_type: str | None
    course_id: int | None
    batch_id: int | None
    attendance_date: date
    marked_time: datetime
    status: str
    sync_status: str

    class Config:
        from_attributes = True
