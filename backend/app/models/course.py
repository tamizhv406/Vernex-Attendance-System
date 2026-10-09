from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    course_name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    batches = relationship("CourseBatch", back_populates="course")


class CourseBatch(Base):
    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("course_id", "batch_name", name="uq_batches_course_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id", ondelete="RESTRICT"), index=True)
    batch_name: Mapped[str] = mapped_column(String(120), index=True)
    batch_level: Mapped[str | None] = mapped_column(String(120))
    timing_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("timings.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    course = relationship("Course", back_populates="batches")
