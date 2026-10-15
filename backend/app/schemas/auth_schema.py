from pydantic import BaseModel


# No length or pattern rules here on purpose. FastAPI answers a broken rule by sending the value
# back in the error, and a password must never be echoed. The service checks both and words its own
# refusals.
class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
