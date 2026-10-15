from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The values the database's CHECK constraints allow (app/models/issue.py), checked here first so that
# a wrong one is refused before anything is looked up. tests/test_issues_schema.py keeps the two equal.
Category = Literal["bug", "face_recognition", "attendance_data", "camera_device", "login_access", "other"]
Severity = Literal["low", "medium", "high", "critical"]
Status = Literal["open", "in_progress", "resolved", "closed"]

# How much of each value is read at all. The real limits (a title of 5 to 120 characters...) are
# applied by app/services/issue_service.py to the text once it is trimmed, and worded there.
LONG_TEXT = 20000
# The largest number an id column holds (PostgreSQL's INTEGER). A larger one is refused (422) instead
# of reaching the database, which would fail on it.
LARGEST_ID = 2_147_483_647


# Anything else sent is refused (422): there is no field for who reported an issue, who wrote a
# comment or, for a reporter, what status an issue has. Those come from the login, never the request.
class DeviceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    browser: str | None = Field(None, max_length=500)
    os: str | None = Field(None, max_length=500)
    screen: str | None = Field(None, max_length=500)


class IssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=1000)
    description: str = Field(max_length=LONG_TEXT)
    category: Category
    severity: Severity
    page_url: str | None = Field(None, max_length=1000)
    device_info: DeviceInfo | None = None


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=LONG_TEXT)


# What a super admin changes on an issue. Only what is sent is changed: assigned_to null takes the
# issue off whoever had it, and a resolution note goes with making (or keeping) the issue resolved.
class IssueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    resolution_note: str | None = Field(None, max_length=LONG_TEXT)
    assigned_to: int | None = Field(None, ge=1, le=LARGEST_ID)
