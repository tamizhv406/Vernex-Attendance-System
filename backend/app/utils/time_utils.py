from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.default_timezone))


def today_local() -> date:
    return now_local().date()
