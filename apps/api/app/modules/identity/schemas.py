import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

PASSWORD = Field(min_length=8, max_length=200)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = PASSWORD
    name: str = Field(min_length=1, max_length=120)
    preferred_locale: str = Field(default="en", max_length=10)
    invite_code: str | None = Field(default=None, max_length=40)


class AuthOptionsOut(BaseModel):
    registration: str  # open | invite


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = PASSWORD


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = PASSWORD


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


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
    email_verified: bool = False


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


class InviteIn(BaseModel):
    email: EmailStr | None = None
    role: str = Field(default="learner", pattern="^(learner|reviewer)$")
    note: str = Field(default="", max_length=200)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: int | None = Field(default=30, ge=1, le=365)
    send_email: bool = False


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str | None
    role: str
    note: str
    max_uses: int
    uses: int
    status: str  # active | used | expired | revoked
    expires_at: datetime | None
    created_at: datetime


class InviteCreatedOut(InviteOut):
    code: str  # shown once; only its hash is stored
    link: str
    emailed: bool
