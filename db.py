from __future__ import annotations
import os
from datetime import datetime
from typing import Optional, Dict, List, Iterator
from sqlalchemy import create_engine, String, Integer, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session
from contextlib import contextmanager

# --- Dual database configuration ---
LEGACY_DB_URL = os.getenv("DATABASE_URL")
SQLITE_DATABASE_URL = os.getenv("SQLITE_DATABASE_URL", "sqlite:///app.db")
POSTGRES_DATABASE_URL = os.getenv("POSTGRES_DATABASE_URL") or (
    LEGACY_DB_URL if (LEGACY_DB_URL or "").startswith("postgres") else None
)
DB_READ_PREFERENCE = os.getenv("DB_READ_PREFERENCE", "postgres").lower()

engines: Dict[str, object] = {}
sessions: Dict[str, sessionmaker] = {}

if SQLITE_DATABASE_URL:
    sqlite_connect_args = {"check_same_thread": False} if SQLITE_DATABASE_URL.startswith("sqlite") else {}
    engines["sqlite"] = create_engine(SQLITE_DATABASE_URL, echo=False, future=True, connect_args=sqlite_connect_args)
    sessions["sqlite"] = sessionmaker(bind=engines["sqlite"], autoflush=False, autocommit=False, future=True)

if POSTGRES_DATABASE_URL:
    engines["postgres"] = create_engine(POSTGRES_DATABASE_URL, echo=False, future=True)
    sessions["postgres"] = sessionmaker(bind=engines["postgres"], autoflush=False, autocommit=False, future=True)


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
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    view_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db() -> None:
    for eng in engines.values():
        Base.metadata.create_all(bind=eng)

@contextmanager
def get_read_session() -> Iterator[Session]:
    session = None
    try:
        # Prefer configured read DB, fallback to available
        if DB_READ_PREFERENCE == "postgres" and "postgres" in sessions:
            session = sessions["postgres"]()
        elif DB_READ_PREFERENCE == "sqlite" and "sqlite" in sessions:
            session = sessions["sqlite"]()
        elif "postgres" in sessions:
            session = sessions["postgres"]()
        else:
            session = sessions["sqlite"]()
        yield session
    finally:
        if session:
            session.close()

@contextmanager
def get_write_sessions() -> Iterator[List[Session]]:
    sessions_list = []
    try:
        if "sqlite" in sessions:
            sessions_list.append(sessions["sqlite"]())
        if "postgres" in sessions:
            sessions_list.append(sessions["postgres"]())
        yield sessions_list
    finally:
        for s in sessions_list:
            s.close()
