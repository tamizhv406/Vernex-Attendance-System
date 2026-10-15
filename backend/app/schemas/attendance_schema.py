from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.timing_schema import text


class AttendanceSessionCreate(BaseModel):
    session_name: text(140)
    session_type: text(40)
    course_id: int
    batch_id: int
    category_program: text(120) | None = None
    batch_name: text(120) | None = None
    timing_id: int | None = None
    session_date: date | None = None
    start_time: time | None = None
    grace_time: time | None = None
    end_time: time | None = None


class AttendanceMark(BaseModel):
    session_id: int | None = None
    person_id: int | None = None
    person_code: text(80) | None = None
    course_id: int | None = None
    batch_id: int | None = None
    confidence_score: float | None = None
    # The scanner says "face_ai" itself. The routes for marking by hand store "manual" (or
    # "auto_absent" for absent) whatever is sent, and never a score sent by the browser.
    recognition_method: text(40) = "manual"
    device_name: text(120) | None = None
    marked_by: text(120) | None = None
    # A reason for a correction; the column has no limit, a request does.
    notes: text(1000) | None = None
    # Marking by hand only: the status the teacher chose. Without it the session decides (see
    # attendance_service.write_attendance); with it, a record that already exists is corrected.
    status: Literal["present", "late", "absent", "visited"] | None = None


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

    model_config = ConfigDict(from_attributes=True)
