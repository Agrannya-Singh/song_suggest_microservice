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
import urllib.parse
import time

# Initialize FastAPI app
app = FastAPI(
    title="Enhanced Music Suggestion API",
    description="API to manage liked songs and get music suggestions based on multiple liked songs using YouTube Data API",
    version="1.1.1"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variable for YouTube API key
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# In-memory store for liked songs
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
CACHE_TTL = 3600
RATE_LIMIT_CALLS = 100
RATE_LIMIT_PERIOD = 60

@sleep_and_retry
@limits(calls=RATE_LIMIT_CALLS, period=RATE_LIMIT_PERIOD)
@lru_cache(maxsize=100)
def get_youtube_suggestions(song_name: str) -> Optional[List[dict]]:
    """
    Fetch music suggestions from YouTube with improved filtering and genre-based scoring.
    """
    try:
        # Normalize song name
        song_name = re.sub(r'[^\w\s]', '', song_name).lower().strip()
        query = urllib.parse.quote(f"{song_name} music song")
        
        # Step 1: Search for the song
        search_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video"
            f"&videoCategoryId=10&maxResults=5&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url, timeout=5)
        if resp.status_code == 429:
            logger.warning("Rate limit exceeded, retrying after delay")
            time.sleep(10)  # Exponential backoff could be added here
            resp = requests.get(search_url, timeout=5)
        if resp.status_code != 200:
            logger.error(f"Search API error: {resp.status_code} - {resp.text}")
            return None
        items = resp.json().get('items', [])
        if not items:
            logger.warning(f"No search results for song: {song_name}")
            # Fallback: Search by artist name
            artist_name = song_name.split()[0]  # Simplified artist extraction
            fallback_query = urllib.parse.quote(f"{artist_name} music")
            search_url = (
                f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={fallback_query}&type=video"
                f"&videoCategoryId=10&maxResults=5&key={YOUTUBE_API_KEY}"
            )
            resp = requests.get(search_url, timeout=5)
            items = resp.json().get('items', [])
            if not items:
                return None

        original_video = items[0]
        original_video_id = original_video["id"]["videoId"]
        original_title = original_video["snippet"]["title"].lower()
        original_channel = original_video["snippet"]["channelTitle"].lower()

        # Step 2: Fetch video details for category and stats
        video_url = (
            f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics"
            f"&id={original_video_id}&key={YOUTUBE_API_KEY}"
        )
        video_resp = requests.get(video_url, timeout=5)
        if video_resp.status_code != 200:
            logger.error(f"Video details API error: {video_resp.status_code} - {video_resp.text}")
            return None
        video_details = video_resp.json().get('items', [])[0]
        category_id = video_details["snippet"].get("categoryId", "10")  # Default to Music
        duration = video_details["contentDetails"].get("duration", "")
        view_count = int(video_details["statistics"].get("viewCount", 0))

        # Step 3: Find related videos
        related_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&relatedToVideoId={original_video_id}"
            f"&type=video&videoCategoryId=10&maxResults=15&key={YOUTUBE_API_KEY}"
        )
        related_resp = requests.get(related_url, timeout=5)
        if related_resp.status_code != 200:
            logger.error(f"Related videos API error: {related_resp.status_code} - {related_resp.text}")
            return None
        related_items = related_resp.json().get('items', [])
        if not related_items:
            logger.warning(f"No related videos found for video ID: {original_video_id}")
            return None

        # Step 4: Filter and score suggestions
        suggestions = []
        unwanted_keywords = ['live', 'cover', 'remix', 'karaoke', 'instrumental', 'tutorial', 'reaction']
        for item in related_items:
            title = item["snippet"]["title"].lower()
            channel = item["snippet"]["channelTitle"].lower()
            # Skip irrelevant videos
            if any(keyword in title for keyword in unwanted_keywords):
                continue
            # Fetch video details for duration and views
            video_id = item["id"]["videoId"]
            video_url = (
                f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,statistics"
                f"&id={video_id}&key={YOUTUBE_API_KEY}"
            )
            video_resp = requests.get(video_url, timeout=5)
            if video_resp.status_code != 200:
                continue
            video_details = video_resp.json().get('items', [])[0]
            video_duration = video_details["contentDetails"].get("duration", "")
            video_views = int(video_details["statistics"].get("viewCount", 0))

            # Filter short videos (< 1 minute)
            if "PT" in video_duration and int(re.search(r'(\d+)M', video_duration, re.I)?.group(1) or 0) < 1:
                continue

            # Scoring
            score = 1.0
            if any(word in title for word in original_title.split()):
                score += 0.5
            if channel == original_channel:
                score += 0.4
            if video_views > 100000:  # Boost popular videos
                score += 0.3 * (video_views / 1000000)  # Scale with views
            suggestions.append({
                "title": item["snippet"]["title"],
                "artist": item["snippet"]["channelTitle"],
                "youtube_video_id": video_id,
                "score": min(score, 3.0)  # Cap score
            })
        return suggestions[:10]  # Limit to top 10

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching suggestions for {song_name}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error for {song_name}: {str(e)}")
        return None

def combine_suggestions(song_names: List[str]) -> List[dict]:
    """
    Combine suggestions from multiple songs, rank by score, and ensure uniqueness.
    """
    all_suggestions = []
    video_id_set = set()
    for song in song_names:
        suggestions = get_youtube_suggestions(song)
        if suggestions:
            for suggestion in suggestions:
                if suggestion["youtube_video_id"] not in video_id_set:
                    all_suggestions.append(suggestion)
                    video_id_set.add(suggestion["youtube_video_id"])

    # Rank and deduplicate
    ranked_suggestions = sorted(all_suggestions, key=lambda x: x["score"], reverse=True)
    unique_suggestions = []
    seen_titles = set()
    for suggestion in ranked_suggestions:
        title = suggestion["title"].lower()
        if title not in seen_titles:
            unique_suggestions.append(suggestion)
            seen_titles.add(title)

    # Return top 5 or all if fewer
    return unique_suggestions[:5]

@app.get(
    "/liked-songs",
    response_model=LikedSongsResponse,
    summary="Get liked songs",
    description="Returns the list of liked songs for a given user ID"
)
async def get_liked_songs(user_id: str = Query(..., min_length=1, description="User ID to fetch liked songs")):
    liked_songs = liked_songs_store.get(user_id, [])
    return JSONResponse(content={"liked_songs": liked_songs})

@app.post(
    "/suggestions",
    response_model=SuggestionResponse,
    summary="Get suggestions based on liked songs",
    description="Returns suggestions based on a list of liked songs for a user"
)
async def post_suggestions(request: LikedSongsRequest):
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")
    if not request.songs:
        raise HTTPException(status_code=400, detail="At least one song must be provided")
    liked_songs_store[request.user_id] = request.songs
    suggestions = combine_suggestions(request.songs)
    if not suggestions:
        raise HTTPException(status_code=404, detail="No suggestions found for the given songs")
    return JSONResponse(content={"suggestions": suggestions})

@app.get("/health", summary="Health check")
async def health_check():
    return {"status": "healthy"}
