# ==============================================================================
# DATABASE MODELS (SCHEMA DEFINITION)
# ==============================================================================
# This module defines the structure of the database tables using SQLAlchemy's
# Object-Relational Mapper (ORM). Each class represents a table in the
# database, and each class attribute represents a column.
# ------------------------------------------------------------------------------

# --- Imports ---
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import datetime

# --- Database Configuration ---

# The URL for our database file. For this project, we use SQLite, which is a
# simple file-based database. The file will be named 'music_recommender.db'.
DATABASE_URL = "sqlite:///./music_recommender.db"

# The `create_engine` function is the entrypoint to the database.
# The `connect_args` is needed specifically for SQLite to allow the database
# to be accessed by multiple threads, which is necessary for FastAPI's
# background tasks.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# `SessionLocal` is a factory that will create our database session objects.
# Each instance of SessionLocal will be a new database session.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# `Base` is a declarative base class. Our model classes will inherit from this
# class to be registered with SQLAlchemy.
Base = declarative_base()


# --- Table Definitions ---

class Song(Base):
    """
    Represents the 'songs' table in the database.

    This table acts as a cache for song data fetched from Spotify, including
    the audio features that are crucial for our recommendation logic.
    """
    __tablename__ = 'songs'

    # The primary key for the song in our database.
    id = Column(Integer, primary_key=True, index=True)

    # The unique identifier for the song on Spotify.
    spotify_id = Column(String, unique=True, index=True, nullable=False)

    # The name of the song.
    name = Column(String, nullable=False)

    # The primary artist of the song.
    artist = Column(String, nullable=False)

    # --- Spotify Audio Features ---
    # These columns store the "gold standard" data from Spotify.
    danceability = Column(Float)
    energy = Column(Float)
    valence = Column(Float) # A measure of musical positiveness.
    tempo = Column(Float)   # Beats Per Minute (BPM).


class Recommendation(Base):
    """
    Represents the 'recommendations' table.

    This table stores the final computed recommendations for a given user,
    allowing the frontend to poll for results.
    """
    __tablename__ = 'recommendations'

    # The primary key for the recommendation entry.
    id = Column(Integer, primary_key=True, index=True)

    # The user ID this recommendation belongs to. This links the result
    # back to the user who made the original request.
    user_id = Column(String, index=True, nullable=False)

    # The name of the recommended song.
    song_name = Column(String, nullable=False)

    # The artist of the recommended song.
    artist_name = Column(String, nullable=False)

    # The similarity score calculated by our model.
    score = Column(Float, nullable=False)

    # Timestamp for when the recommendation was created.
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


def create_db_and_tables():
    """
    Initializes the database by creating all tables defined in this file.
    This function should be called once when the application starts up.
    """
    # Base.metadata.create_all() uses the engine to create all tables
    # that inherit from the Base class.
    Base.metadata.create_all(bind=engine)
