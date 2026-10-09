from pydantic import BaseModel


class FaceFrameRequest(BaseModel):
    person_id: int
    current_step: str
    image_base64: str | None = None
    has_specs: bool = False


class FaceRecognizeRequest(BaseModel):
    image_base64: str | None = None
    session_id: int | None = None
    device_name: str | None = None
