import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    preferred_locale: str = Field(default="en", max_length=10)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: str
    preferred_locale: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_exams: list[str] = []
    exam_date: datetime | None = None
    daily_minutes_goal: int = 60
    education_level: str = ""
    languages: list[str] = []
    career_goal: str = ""


class MeOut(UserOut):
    profile: ProfileOut


class MePatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    preferred_locale: str | None = Field(default=None, max_length=10)
    target_exams: list[str] | None = None
    exam_date: datetime | None = None
    daily_minutes_goal: int | None = Field(default=None, ge=10, le=720)
    education_level: str | None = Field(default=None, max_length=60)
    languages: list[str] | None = None
    career_goal: str | None = Field(default=None, max_length=255)


class AdminUserPatch(BaseModel):
    role: str | None = Field(default=None, pattern="^(learner|reviewer|admin)$")
    status: str | None = Field(default=None, pattern="^(active|suspended)$")
