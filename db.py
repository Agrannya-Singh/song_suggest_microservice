from __future__ import annotations
import os
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, String, Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

# Database URL (SQLite by default). Can be overridden with DATABASE_URL env var (e.g., postgres://...)
DB_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")

# Create engine. For SQLite, enable check_same_thread=False to allow usage across threads in FastAPI.
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, echo=False, future=True, connect_args=connect_args)

# Session factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    likes: Mapped[list[UserLikedSong]] = relationship("UserLikedSong", back_populates="user", cascade="all, delete-orphan")


class UserLikedSong(Base):
    __tablename__ = "user_liked_songs"
    __table_args__ = (
        UniqueConstraint("user_id", "song_name", name="uq_user_song"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    song_name: Mapped[str] = mapped_column(String(512), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship("User", back_populates="likes")


class QueryCache(Base):
    __tablename__ = "query_cache"
    __table_args__ = (
        UniqueConstraint("query", name="uq_query"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(String(512), index=True)
    best_video_id: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoFeature(Base):
    __tablename__ = "video_features"
    __table_args__ = (
        UniqueConstraint("video_id", name="uq_video_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    channel_title: Mapped[str] = mapped_column(String(256))
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # comma-joined
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    view_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # ISO 8601 PT#M#S
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    return SessionLocal()
