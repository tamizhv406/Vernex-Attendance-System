from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SheetSyncLog(Base):
    __tablename__ = "sheet_sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attendance_record_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("attendance_records.id"))
    sheet_name: Mapped[str | None] = mapped_column(String(140))
    sync_status: Mapped[str] = mapped_column(String(30))
    request_payload: Mapped[str | None] = mapped_column(Text)
    response_message: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[DateTime | None] = mapped_column(DateTime)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
