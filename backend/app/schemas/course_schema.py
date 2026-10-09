from pydantic import BaseModel


class CourseCreate(BaseModel):
    course_code: str
    course_name: str
    description: str | None = None
    status: str = "active"


class CourseUpdate(BaseModel):
    course_code: str | None = None
    course_name: str | None = None
    description: str | None = None
    status: str | None = None


class BatchCreate(BaseModel):
    course_id: int
    batch_name: str
    batch_level: str | None = None
    timing_id: int | None = None
    status: str = "active"


class BatchUpdate(BaseModel):
    course_id: int | None = None
    batch_name: str | None = None
    batch_level: str | None = None
    timing_id: int | None = None
    status: str | None = None
