from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings


def utc_now() -> datetime:
    # UTC without a time zone, which is what a DateTime column holds. Anything compared with a
    # stored time (an account's lock, a login's expiry) uses this one clock, so SQLite and
    # PostgreSQL behave the same and the database's own idea of "now" never comes into it.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.default_timezone))


def today_local() -> date:
    return now_local().date()
