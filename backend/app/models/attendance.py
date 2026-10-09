from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_name: Mapped[str] = mapped_column(String(140))
    session_type: Mapped[str] = mapped_column(String(40))
    course_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), index=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    category_program: Mapped[str | None] = mapped_column(String(120))
    batch_name: Mapped[str | None] = mapped_column(String(120))
    timing_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("timings.id"))
    session_date: Mapped[Date] = mapped_column(Date, index=True)
    start_time: Mapped[Time | None] = mapped_column(Time)
    grace_time: Mapped[Time | None] = mapped_column(Time)
    end_time: Mapped[Time | None] = mapped_column(Time)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    # The database itself refuses a second record for the same person, session and day, whichever
    # scanner or request tries to write it. (Existing databases get the index in schema.py.)
    __table_args__ = (
        Index("uq_attendance_session_person_date", "session_id", "person_id", "attendance_date", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("attendance_sessions.id"), index=True)
    person_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user_management.id", ondelete="SET NULL"), index=True)
    person_code: Mapped[str | None] = mapped_column(String(80))
    person_name: Mapped[str | None] = mapped_column(String(160))
    person_type: Mapped[str | None] = mapped_column(String(30))
    course_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), index=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    category_program: Mapped[str | None] = mapped_column(String(120))
    batch_name: Mapped[str | None] = mapped_column(String(120))
    level_class: Mapped[str | None] = mapped_column(String(120))
    attendance_date: Mapped[Date] = mapped_column(Date, index=True)
    marked_time: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(40))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    recognition_method: Mapped[str] = mapped_column(String(40), default="face_ai")
    device_name: Mapped[str | None] = mapped_column(String(120))
    marked_by: Mapped[str | None] = mapped_column(String(120))
    duplicate_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_status: Mapped[str] = mapped_column(String(30), default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
