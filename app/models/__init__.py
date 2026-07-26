import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
import enum

from app.database import Base


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    CREATOR = "creator"


class VoiceType(str, enum.Enum):
    BUILTIN = "builtin"
    CUSTOM = "custom"
    CLONED = "cloned"


class ProjectType(str, enum.Enum):
    VOICEOVER = "voiceover"
    AUDIOBOOK = "audiobook"
    PODCAST = "podcast"
    VIDEO = "video"
    AUTOMATION = "automation"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(Enum(UserRole), default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    credits = Column(Integer, default=999999)
    total_credits_used = Column(Integer, default=0)
    referral_code = Column(String(20), unique=True, index=True)
    referred_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    voices = relationship("Voice", back_populates="owner", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    audio_files = relationship("AudioFile", back_populates="owner", cascade="all, delete-orphan")
    referrals = relationship("User", backref="referrer", remote_side=[id])


class Voice(Base):
    __tablename__ = "voices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    voice_type = Column(Enum(VoiceType), default=VoiceType.BUILTIN)
    voice_key = Column(String(100), index=True)
    language = Column(String(10), default="en")
    gender = Column(String(20))
    accent = Column(String(50))
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_public = Column(Boolean, default=True)
    settings = Column(JSON, default={"temperature": 0.7, "speed": 1.0})
    sample_url = Column(String(500))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="voices")
    audio_files = relationship("AudioFile", back_populates="voice")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    project_type = Column(Enum(ProjectType), default=ProjectType.VOICEOVER)
    settings = Column(JSON, default={})
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="projects")
    audio_files = relationship("AudioFile", back_populates="project")


class AudioFile(Base):
    __tablename__ = "audio_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    duration = Column(Integer)
    text_content = Column(Text)
    voice_id = Column(Integer, ForeignKey("voices.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    language = Column(String(10), default="en")
    settings = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    voice = relationship("Voice", back_populates="audio_files")
    project = relationship("Project", back_populates="audio_files")
    owner = relationship("User", back_populates="audio_files")
