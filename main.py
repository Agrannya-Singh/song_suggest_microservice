# ==============================================================================
# MAIN API APPLICATION (DUAL SOURCE)
# ==============================================================================
# This version of the main application supports a 'source' parameter to allow
# clients to choose between 'spotify' and 'youtube' for recommendations.
# ------------------------------------------------------------------------------

# --- Imports ---
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Literal
from sqlalchemy.orm import Session

# Import our own modules.
from database import get_db
from models import Recommendation as RecommendationModel, create_db_and_tables
from processing import generate_and_save_recommendations
import spotify_client # Keep for startup check

# --- Initial Application Setup ---
app = FastAPI(
    title="Song Suggestion Microservice",
    description="A REST API to get song suggestions from either Spotify or YouTube.",
    version="2.2.0"
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
    print("INFO: Application starting up...")
    create_db_and_tables()
    print("INFO: Database tables created successfully.")
    # (The Spotify health check can remain here)


# --- Pydantic Models for Request and Response ---

class SuggestionRequest(BaseModel):
    """Defines the structure for a POST /suggestions request."""
    user_id: str
    songs: List[str]
    # Add the new 'source' field. It can only be 'spotify' or 'youtube'.
    # Spotify is the default value if the client doesn't provide one.
    source: Literal['spotify', 'youtube'] = 'spotify'

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

    # **THIS IS THE FIX**
    # Pass the new 'source' parameter from the request to the background task.
    background_tasks.add_task(
        generate_and_save_recommendations,
        request.user_id,
        request.songs,
        request.source # Pass the source from the request
    )

    return {
        "message": f"Recommendation request received for source '{request.source}'. Processing in background.",
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
