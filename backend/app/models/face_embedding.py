from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FaceEnrollment(Base):
    __tablename__ = "face_enrollments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_management.id"), index=True)
    enrollment_status: Mapped[str] = mapped_column(String(50), default="not_started")
    current_step: Mapped[str | None] = mapped_column(String(40))
    total_steps: Mapped[int] = mapped_column(Integer, default=5)
    completed_steps: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float | None] = mapped_column(Float)
    has_specs_reference: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_management.id"), index=True)
    embedding_vector: Mapped[str] = mapped_column(Text)
    pose_type: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str] = mapped_column(String(80), default="DeepFace")
    quality_score: Mapped[float | None] = mapped_column(Float)
    brightness_score: Mapped[float | None] = mapped_column(Float)
    blur_score: Mapped[float | None] = mapped_column(Float)
    face_angle: Mapped[float | None] = mapped_column(Float)
    has_specs: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # JSON: how this reference face was captured (detector, sizes, focus, how it compares with the
    # other poses). Numbers only, for judging a stored face later. No image is kept.
    capture_meta: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    person = relationship("Person", back_populates="embeddings")
