import os
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from functools import lru_cache
from ratelimit import limits, sleep_and_retry
import logging
import re
from collections import Counter

# Initialize FastAPI app
app = FastAPI(
    title="Enhanced Music Suggestion API",
    description="API to manage liked songs and get music suggestions based on multiple liked songs using YouTube Data API",
    version="1.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variable for YouTube API key
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# In-memory store for liked songs (user_id -> list of songs)
liked_songs_store: Dict[str, List[str]] = {}

# Pydantic models
class Song(BaseModel):
    song_name: str

class SongSuggestion(BaseModel):
    title: str
    artist: str
    youtube_video_id: str
    score: float

class SuggestionResponse(BaseModel):
    suggestions: List[SongSuggestion]

class LikedSongsResponse(BaseModel):
    liked_songs: List[str]

class LikedSongsRequest(BaseModel):
    user_id: str
    songs: List[str]

# Cache and rate limit settings
CACHE_TTL = 3600  # Cache results for 1 hour
RATE_LIMIT_CALLS = 100  # API calls per minute
RATE_LIMIT_PERIOD = 60  # Seconds

@sleep_and_retry
@limits(calls=RATE_LIMIT_CALLS, period=RATE_LIMIT_PERIOD)
@lru_cache(maxsize=100)
def get_youtube_suggestions(song_name: str) -> Optional[List[dict]]:
    """
    Fetch music suggestions from YouTube based on a song name with improved filtering.
    """
    try:
        # Step 1: Search for the song
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={song_name}&type=video&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url, timeout=5)
        if resp.status_code != 200:
            logger.error(f"Search API error: {resp.status_code} - {resp.text}")
            return None
        items = resp.json().get('items', [])
        if not items:
            logger.warning(f"No search results for song: {song_name}")
            return None

        original_video = items[0]
        original_video_id = original_video["id"]["videoId"]
        original_title = original_video["snippet"]["title"].lower()

        # Step 2: Find related videos
        related_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&relatedToVideoId={original_video_id}"
            f"&type=video&maxResults=10&key={YOUTUBE_API_KEY}"
        )
        related_resp = requests.get(related_url, timeout=5)
        if related_resp.status_code != 200:
            logger.error(f"Related videos API error: {related_resp.status_code} - {related_resp.text}")
            return None
        related_items = related_resp.json().get('items', [])
        if not related_items:
            logger.warning(f"No related videos found for video ID: {original_video_id}")
            return None

        # Step 3: Filter and score suggestions
        suggestions = []
        unwanted_keywords = ['live', 'cover', 'remix', 'karaoke', 'instrumental']
        for item in related_items:
            title = item["snippet"]["title"].lower()
            # Skip irrelevant videos
            if any(keyword in title for keyword in unwanted_keywords):
                continue
            # Simple scoring based on title similarity and channel
            score = 1.0
            if any(word in title for word in original_title.split()):
                score += 0.5  # Boost for title similarity
            if item["snippet"]["channelTitle"].lower() == original_video["snippet"]["channelTitle"].lower():
                score += 0.3  # Boost for same artist/channel
            suggestions.append({
                "title": item["snippet"]["title"],
                "artist": item["snippet"]["channelTitle"],
                "youtube_video_id": item["id"]["videoId"],
                "score": score
            })
        return suggestions

    except Exception as e:
        logger.error(f"Error fetching suggestions for {song_name}: {str(e)}")
        return None

def combine_suggestions(song_names: List[str]) -> List[dict]:
    """
    Combine suggestions from multiple songs and rank by score.
    """
    all_suggestions = []
    video_id_set = set()  # Track unique suggestions
    for song in song_names:
        suggestions = get_youtube_suggestions(song)
        if suggestions:
            for suggestion in suggestions:
                if suggestion["youtube_video_id"] not in video_id_set:
                    all_suggestions.append(suggestion)
                    video_id_set.add(suggestion["youtube_video_id"])

    # Rank suggestions by score and limit to 5
    ranked_suggestions = sorted(all_suggestions, key=lambda x: x["score"], reverse=True)[:5]
    return ranked_suggestions

@app.get(
    "/liked-songs",
    response_model=LikedSongsResponse,
    summary="Get liked songs",
    description="Returns the list of liked songs for a given user ID"
)
async def get_liked_songs(user_id: str = Query(..., min_length=1, description="User ID to fetch liked songs")):
    """
    Fetch the list of liked songs for a user.
    """
    liked_songs = liked_songs_store.get(user_id, [])
    return JSONResponse(content={"liked_songs": liked_songs})

@app.post(
    "/suggestions",
    response_model=SuggestionResponse,
    summary="Get suggestions based on liked songs",
    description="Returns suggestions based on a list of liked songs for a user"
)
async def post_suggestions(request: LikedSongsRequest):
    """
    Post liked songs and get combined suggestions.
    """
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")

    # Store liked songs
    liked_songs_store[request.user_id] = request.songs

    # Get combined suggestions
    suggestions = combine_suggestions(request.songs)
    if not suggestions:
        raise HTTPException(status_code=404, detail="No suggestions found for the given songs")

    return JSONResponse(content={"suggestions": suggestions})

@app.get("/health", summary="Health check")
async def health_check():
    """Check if the API is running"""
    return {"status": "healthy"}
