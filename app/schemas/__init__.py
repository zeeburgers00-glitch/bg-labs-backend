from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field
from app.models import UserRole, VoiceType, ProjectType


# User schemas
class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None


class UserResponse(UserBase):
    id: int
    role: UserRole
    is_active: bool
    credits: int
    total_credits_used: int
    referral_code: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None


# Voice schemas
class VoiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    voice_type: VoiceType = VoiceType.BUILTIN
    is_public: bool = True
    language: str = "en"
    gender: Optional[str] = None
    accent: Optional[str] = None
    settings: Dict[str, Any] = {"temperature": 0.7, "speed": 1.0}


class VoiceCreate(VoiceBase):
    voice_key: Optional[str] = None
    sample_url: Optional[str] = None


class VoiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


class VoiceResponse(VoiceBase):
    id: int
    voice_key: Optional[str]
    owner_id: int
    sample_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# Project schemas
class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    project_type: ProjectType = ProjectType.VOICEOVER
    settings: Dict[str, Any] = {}


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    project_type: Optional[ProjectType] = None
    settings: Optional[Dict[str, Any]] = None


class ProjectResponse(ProjectBase):
    id: int
    owner_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Audio schemas
class AudioGenerateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    voice_id: Optional[int] = None
    voice_key: Optional[str] = "aria"
    project_id: Optional[int] = None
    language: str = "en"
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    speed: float = Field(1.0, ge=0.5, le=2.0)


class AudioFileResponse(BaseModel):
    id: int
    filename: str
    url: str
    duration: Optional[int]
    text_content: str
    voice_id: int
    project_id: Optional[int]
    language: str
    settings: Dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


# Voice List response
class VoiceListResponse(BaseModel):
    voices: List[Dict[str, Any]]
    total: int
    languages: Dict[str, str]


# Admin schemas
class AdminUserResponse(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str]
    role: UserRole
    is_active: bool
    credits: int
    total_credits_used: int
    created_at: datetime
    referrals_count: int = 0

    class Config:
        from_attributes = True


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_voices: int
    total_projects: int
    total_audio_generated: int
    total_credits_used: int
