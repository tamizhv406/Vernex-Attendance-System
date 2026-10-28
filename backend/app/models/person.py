from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Person(Base):
    __tablename__ = "user_management"
    # One person per attendance code (migration 010). Rows without a code yet (NULL) do not conflict.
    __table_args__ = (Index("uq_user_management_attendance_code", "attendance_code", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    person_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(160))
    person_type: Mapped[str] = mapped_column(String(30), index=True)
    gender: Mapped[str | None] = mapped_column(String(30))
    guardian_name: Mapped[str | None] = mapped_column(String(160))
    guardian_phone: Mapped[str | None] = mapped_column(String(20))
    course_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), index=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    category_program: Mapped[str | None] = mapped_column(String(120), index=True)
    batch_name: Mapped[str | None] = mapped_column(String(120), index=True)
    level_class: Mapped[str | None] = mapped_column(String(120))
    designation: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    membership_type: Mapped[str | None] = mapped_column(String(120))
    plan_name: Mapped[str | None] = mapped_column(String(120))
    timing_id: Mapped[int | None] = mapped_column(Integer)
    joining_date: Mapped[Date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="active")
    face_enrollment_status: Mapped[str] = mapped_column(String(40), default="not_started")
    notes: Mapped[str | None] = mapped_column(Text)
    # The random code a QR card holds (app/services/attendance_code_service.py), stored uppercase without
    # the hyphen. Never chosen by a client. NULL only until a row made before migration 010 is given one.
    attendance_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # A person's reference faces are deleted with them; without the cascade SQLAlchemy tries to blank person_id.
    embeddings = relationship("FaceEmbedding", back_populates="person", cascade="all, delete-orphan")
