from pydantic import BaseModel, ConfigDict


# What a super admin sends to create or change an account. There is no password field: a new
# account and a reset get a temporary password made by the backend. No status either: disabling and
# enabling have routes of their own, with their own checks. Anything else sent is refused (422).
# The values themselves are checked by app/services/admin_service.py, which words its own refusals.
class AdminCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    full_name: str
    role: str = "admin"


class AdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    full_name: str | None = None
    role: str | None = None
