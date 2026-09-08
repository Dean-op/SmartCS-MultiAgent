from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ecommerce_ai_agent.models.enums import UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserProfileResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
