from datetime import datetime, time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


def text(limit):
    # At most as long as the database column. SQLite keeps a longer value; PostgreSQL refuses it with
    # a database error, which used to come back as a server error (500) instead of a 422.
    return Annotated[str, Field(max_length=limit)]


class TimingBase(BaseModel):
    name: text(140)
    timing_type: text(40)
    category_program: text(120) | None = None
    batch_name: text(120) | None = None
    start_time: time | None = None
    grace_time: time | None = None
    end_time: time | None = None
    late_after_time: time | None = None
    auto_absent_after_time: time | None = None
    working_days: text(160) | None = None
    status: text(30) = "active"


class TimingCreate(TimingBase):
    pass


class TimingUpdate(BaseModel):
    name: text(140) | None = None
    timing_type: text(40) | None = None
    category_program: text(120) | None = None
    batch_name: text(120) | None = None
    start_time: time | None = None
    grace_time: time | None = None
    end_time: time | None = None
    late_after_time: time | None = None
    auto_absent_after_time: time | None = None
    working_days: text(160) | None = None
    status: text(30) | None = None


class TimingOut(TimingBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
