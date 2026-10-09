from sqlalchemy import DateTime, Integer, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Timing(Base):
    __tablename__ = "timings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(140), index=True)
    timing_type: Mapped[str] = mapped_column(String(40))
    category_program: Mapped[str | None] = mapped_column(String(120))
    batch_name: Mapped[str | None] = mapped_column(String(120))
    start_time: Mapped[Time | None] = mapped_column(Time)
    grace_time: Mapped[Time | None] = mapped_column(Time)
    end_time: Mapped[Time | None] = mapped_column(Time)
    late_after_time: Mapped[Time | None] = mapped_column(Time)
    auto_absent_after_time: Mapped[Time | None] = mapped_column(Time)
    working_days: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
