# ==============================================================================
# MAIN API APPLICATION
# ==============================================================================
# This module defines the FastAPI application, including all API endpoints.
# It serves as the main entrypoint for the microservice.
#

# ------------------------------------------------------------------------------

# --- Imports ---
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session

# Import our own modules.
# Corrected the import for create_db_and_tables to point to models.py
from database import get_db
from models import Recommendation as RecommendationModel, create_db_and_tables
from processing import generate_and_save_recommendations

# --- Initial Application Setup ---

# Create the FastAPI app instance.
app = FastAPI(
    title="Song Suggestion Microservice",
    description="A REST API to get song suggestions based on content-based filtering using Spotify's audio features.",
    version="2.0.0"
)

# This event handler runs once when the application starts up.
@app.on_event("startup")
def on_startup():
    """
    Creates the database and tables if they don't already exist.
    """
    print("INFO: Application starting up. Creating database tables...")
    create_db_and_tables()
    print("INFO: Database tables created successfully.")


# --- Pydantic Models for Request and Response ---
# These models define the expected data shape for API requests and responses.
# FastAPI uses them for automatic validation and documentation.

class SuggestionRequest(BaseModel):
    """Defines the structure for a POST /suggestions request."""
    user_id: str
    songs: List[str]

class SuggestionResponse(BaseModel):
    """Defines the structure for a successful POST /suggestions response."""
    message: str
    user_id: str

class Recommendation(BaseModel):
    """Defines the structure for a single recommended song in the response."""
    song_name: str
    artist_name: str
    score: float

    # This class allows Pydantic to read data from ORM models (like our
    # RecommendationModel) directly.
    class Config:
        orm_mode = True

class ResultResponse(BaseModel):
    """Defines the structure for a GET /suggestions/result/{user_id} response."""
    status: str
    recommendations: List[Recommendation]


# --- API Endpoints ---

@app.post("/suggestions", response_model=SuggestionResponse, status_code=202)
def create_suggestions_task(
    request: SuggestionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Endpoint to request new song suggestions.

    This endpoint accepts a user ID and a list of liked songs. It returns an
    immediate response and queues the heavy processing to run in the background.
    This non-blocking approach ensures a great user experience.

    - **status_code=202**: "Accepted" indicates that the request has been
      accepted for processing, but the processing has not been completed.
    """
    if not request.songs:
        raise HTTPException(status_code=400, detail="The 'songs' list cannot be empty.")

    # Add the core logic function to be executed in the background.
    # FastAPI will run this function *after* the response has been sent.
    background_tasks.add_task(
        generate_and_save_recommendations,
        request.user_id,
        request.songs,
        db
    )

    # Return an immediate response to the client.
    return {
        "message": "Recommendation request received. Processing in the background.",
        "user_id": request.user_id
    }


@app.get("/suggestions/result/{user_id}", response_model=ResultResponse)
def get_suggestion_results(user_id: str, db: Session = Depends(get_db)):
    """
    Endpoint to poll for and retrieve the results of a suggestion request.

    The frontend can call this endpoint periodically to check if the background
    task has finished and the recommendations are ready.
    """
    # Query the database for recommendations matching the user_id.
    # Order by score in descending order to get the best matches first.
    results = db.query(RecommendationModel)\
                .filter(RecommendationModel.user_id == user_id)\
                .order_by(RecommendationModel.score.desc())\
                .all()

    if not results:
        # If no results are found, it means the task is either still running
        # or it failed to produce any recommendations.
        return {"status": "pending", "recommendations": []}

    # If results are found, return them.
    return {"status": "complete", "recommendations": results}


@app.get("/health", summary="Health Check")
def health_check():
    """
    A simple endpoint to verify that the API is running and responsive.
    """
    return {"status": "healthy"}

