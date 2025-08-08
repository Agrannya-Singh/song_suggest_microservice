# ==============================================================================
# MAIN API APPLICATION (WITH DISCOVER & HEALTH CHECK)
# ==============================================================================
# This is the final version of the main application. It includes the /discover
# endpoint and the Spotify API health check on startup.
# ------------------------------------------------------------------------------

# --- Imports ---
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal
from sqlalchemy.orm import Session

# Import our own modules.
from database import get_db
from models import Recommendation as RecommendationModel, create_db_and_tables
from processing import generate_and_save_recommendations
import spotify_client

# --- Initial Application Setup ---
app = FastAPI(
    title="Song Suggestion Microservice",
    description="A REST API to get song suggestions and discover new music.",
    version="3.2.1" # Version bump for fix
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    """
    Performs startup tasks:
    1. Creates the database and tables if they don't already exist.
    2. Runs a health check on the Spotify API connection.
    """
    print("INFO: Application starting up...")

    # --- Task 1: Initialize Database ---
    print("INFO: Creating database tables...")
    create_db_and_tables()
    print("INFO: Database tables created successfully.")

    # --- Task 2: Spotify API Health Check (The Rickroll Test) ---
    print("INFO: Performing Spotify API health check...")
    try:
        rick_astley_song = spotify_client.search_for_song(
            song_name="Never Gonna Give You Up",
            artist="Rick Astley"
        )
        if rick_astley_song:
            print("✅ SUCCESS: Spotify health check passed. We're never gonna let you down!")
        else:
            print("❌ FAILED: Spotify health check failed. Check API credentials or network.")
    except Exception as e:
        print(f"❌ FAILED: An exception occurred during Spotify health check: {e}")


# --- Pydantic Models ---
class SuggestionRequest(BaseModel):
    user_id: str
    songs: List[str]

class SuggestionResponse(BaseModel):
    message: str
    user_id: str

class Recommendation(BaseModel):
    song_name: str
    artist_name: str
    score: float
    youtube_video_id: str
    class Config:
        orm_mode = True

class ResultResponse(BaseModel):
    status: str
    recommendations: List[Recommendation]

class DiscoverSong(BaseModel):
    song_name: str
    artist_name: str
    spotify_track_id: str

# --- API Endpoints ---

@app.get("/discover", response_model=List[DiscoverSong])
def get_discover_songs(
    genres: List[str] = Query(None, description="A list of genres to seed recommendations."),
    moods: List[str] = Query(None, description="A list of moods to tailor audio features.")
):
    songs = []
    if genres:
        print(f"INFO: /discover called with genres: {genres} and moods: {moods}")
        songs = spotify_client.get_vibe_recommendations(genres=genres, moods=moods)
    else:
        print("INFO: /discover called with no parameters. Fetching default playlist.")
        songs = spotify_client.get_discover_playlist()

    if not songs:
        raise HTTPException(status_code=404, detail="Could not find any songs matching your criteria.")
    
    return songs


@app.post("/suggestions", response_model=SuggestionResponse, status_code=202)
def create_suggestions_task(
    request: SuggestionRequest,
    background_tasks: BackgroundTasks
):
    if not request.songs:
        raise HTTPException(status_code=400, detail="The 'songs' list cannot be empty.")
    background_tasks.add_task(
        generate_and_save_recommendations,
        request.user_id,
        request.songs
    )
    return {
        "message": "Recommendation request received. Processing in background.",
        "user_id": request.user_id
    }


@app.get("/suggestions/result/{user_id}", response_model=ResultResponse)
def get_suggestion_results(user_id: str, db: Session = Depends(get_db)):
    results = db.query(RecommendationModel)\
                .filter(RecommendationModel.user_id == user_id)\
                .order_by(RecommendationModel.score.desc())\
                .all()
    if not results:
        return {"status": "pending", "recommendations": []}
    return {"status": "complete", "recommendations": results}


@app.get("/health", summary="Health Check")
def health_check():
    return {"status": "healthy"}
