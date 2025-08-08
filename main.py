# ==============================================================================
# MAIN API APPLICATION
# ==============================================================================
# This module defines the FastAPI application, including all API endpoints.
# It serves as the main entrypoint for the microservice.
#
# To run this application:
# uvicorn main:app --reload
# ------------------------------------------------------------------------------

# --- Imports ---
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session

# Import our own modules.
from database import get_db
from models import Recommendation as RecommendationModel, create_db_and_tables
from processing import generate_and_save_recommendations
# Import the spotify client to perform the startup check
import spotify_client

# --- Initial Application Setup ---

# Create the FastAPI app instance.
app = FastAPI(
    title="Song Suggestion Microservice",
    description="A REST API to get song suggestions based on content-based filtering using Spotify's audio features.",
    version="2.1.0" # Version bump for new feature
)

# --- CORS Middleware ---
# For development, we allow all origins. For production, you should restrict
# this to your frontend's specific domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# This event handler runs once when the application starts up.
@app.on_event("startup")
def on_startup():
    """
    Performs startup tasks:
    1. Creates the database and tables if they don't exist.
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
        # We search for a known song to verify that our API credentials
        # and connection to Spotify are working correctly.
        rick_astley_song = spotify_client.search_for_song(
            song_name="Never Gonna Give You Up",
            artist="Rick Astley"
        )
        if rick_astley_song:
            # If the search is successful, we log a success message.
            print("✅ SUCCESS: Spotify health check passed. We're never gonna let you down!")
        else:
            # If the search fails, it indicates a problem with credentials or connection.
            print("❌ FAILED: Spotify health check failed. We've been let down. Check API credentials.")
    except Exception as e:
        # Catch any other exceptions during the API call.
        print(f"❌ FAILED: An exception occurred during Spotify health check: {e}")


# --- Pydantic Models for Request and Response ---

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
    class Config:
        orm_mode = True

class ResultResponse(BaseModel):
    status: str
    recommendations: List[Recommendation]


# --- API Endpoints ---

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
        "message": "Recommendation request received. Processing in the background.",
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
    """
    A simple endpoint to verify that the API is running and responsive.
    """
    return {"status": "healthy"}
