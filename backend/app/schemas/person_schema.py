from datetime import date, datetime
from pydantic import BaseModel


class PersonBase(BaseModel):
    person_code: str
    full_name: str
    phone: str | None = None
    email: str | None = None
    person_type: str
    gender: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None
    course_id: int | None = None
    batch_id: int | None = None
    category_program: str | None = None
    batch_name: str | None = None
    level_class: str | None = None
    designation: str | None = None
    department: str | None = None
    membership_type: str | None = None
    plan_name: str | None = None
    timing_id: int | None = None
    joining_date: date | None = None
    status: str = "active"
    face_enrollment_status: str = "not_started"
    notes: str | None = None


class PersonCreate(PersonBase):
    pass


class PersonUpdate(BaseModel):
    person_code: str | None = None
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    person_type: str | None = None
    gender: str | None = None
    guardian_name: str | None = None
    guardian_phone: str | None = None
    course_id: int | None = None
    batch_id: int | None = None
    category_program: str | None = None
    batch_name: str | None = None
    level_class: str | None = None
    designation: str | None = None
    department: str | None = None
    membership_type: str | None = None
    plan_name: str | None = None
    timing_id: int | None = None
    joining_date: date | None = None
    status: str | None = None
    face_enrollment_status: str | None = None
    notes: str | None = None


class PersonOut(PersonBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
