from pydantic import BaseModel

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    login: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    id: int
    login: str
    org_name: str
    department: str
    role: UserRole
    is_active: bool

    class Config:
        from_attributes = True
