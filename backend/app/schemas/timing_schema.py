from datetime import datetime, time
from pydantic import BaseModel


class TimingBase(BaseModel):
    name: str
    timing_type: str
    category_program: str | None = None
    batch_name: str | None = None
    start_time: time | None = None
    grace_time: time | None = None
    end_time: time | None = None
    late_after_time: time | None = None
    auto_absent_after_time: time | None = None
    working_days: str | None = None
    status: str = "active"


class TimingCreate(TimingBase):
    pass


class TimingUpdate(BaseModel):
    name: str | None = None
    timing_type: str | None = None
    category_program: str | None = None
    batch_name: str | None = None
    start_time: time | None = None
    grace_time: time | None = None
    end_time: time | None = None
    late_after_time: time | None = None
    auto_absent_after_time: time | None = None
    working_days: str | None = None
    status: str | None = None


class TimingOut(TimingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
