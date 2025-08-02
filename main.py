import os
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
from functools import lru_cache
import logging
import re
import urllib.parse
import time
import random
from dotenv import load_dotenv
from ratelimit import limits, sleep_and_retry

# Define rate-limiting constants
RATE_LIMIT_CALLS = 100
RATE_LIMIT_PERIOD = 60

# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Enhanced Music Suggestion API",
    description="API to manage liked songs and get music suggestions based on multiple liked songs using YouTube Data API. Includes a fallback to popular songs.",
    version="1.2.0"
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

# Validate API key at startup
if not YOUTUBE_API_KEY:
    logger.warning("YouTube API key not found. Please set YOUTUBE_API_KEY environment variable.")
else:
    logger.info("YouTube API key loaded successfully.")

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

# Cache settings
CACHE_TTL = 3600

def get_popular_song_fallback(input_songs: List[str] = None) -> Optional[List[dict]]:
    """
    Fetches a popular music video from YouTube's charts as a fallback.
    Filters for videos with more than 100 million views and excludes input songs.
    """
    logger.info("Executing fallback: searching for a popular song.")
    try:
        fallback_url = (
            f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics"
            f"&chart=mostPopular&videoCategoryId=10&maxResults=50&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(fallback_url, timeout=10)
        if resp.status_code != 200:
            logger.error(f"Fallback API error: {resp.status_code} - {resp.text}")
            return None

        items = resp.json().get('items', [])
        if not items:
            logger.warning("Fallback could not retrieve any popular songs.")
            return None

        # Normalize input song titles for comparison
        normalized_input_songs = {re.sub(r'[^\w\s]', '', song).lower().strip() for song in (input_songs or [])}

        # Filter for songs with over 100 million views
        popular_songs_high_views = [
            item for item in items
            if 'viewCount' in item.get('statistics', {}) and int(item['statistics']['viewCount']) > 100000000
        ]

        if not popular_songs_high_views:
            logger.warning("No songs with over 100M views in the current popular chart, returning from top of chart.")
            if items:
                # Select a song that doesn't match input songs
                valid_songs = [
                    item for item in items
                    if re.sub(r'[^\w\s]', '', item["snippet"]["title"]).lower().strip() not in normalized_input_songs
                ]
                if valid_songs:
                    song = random.choice(valid_songs)
                    return [{
                        "title": song["snippet"]["title"],
                        "artist": song["snippet"]["channelTitle"],
                        "youtube_video_id": song["id"],
                        "score": 1.0
                    }]
                return None
            return None

        # Select a song that doesn't match input songs
        valid_songs = [
            item for item in popular_songs_high_views
            if re.sub(r'[^\w\s]', '', item["snippet"]["title"]).lower().strip() not in normalized_input_songs
        ]
        if valid_songs:
            song = random.choice(valid_songs)
            return [{
                "title": song["snippet"]["title"],
                "artist": song["snippet"]["channelTitle"],
                "youtube_video_id": song["id"],
                "score": 1.0
            }]
        logger.warning("No valid fallback songs found that don't match input songs.")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during fallback search: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during fallback: {str(e)}")
        return None

@sleep_and_retry
@limits(calls=RATE_LIMIT_CALLS, period=RATE_LIMIT_PERIOD)
@lru_cache(maxsize=100)
def get_youtube_suggestions(song_name: str) -> Optional[List[dict]]:
    """
    Fetch music suggestions from YouTube with improved filtering and genre-based scoring.
    """
    try:
        song_name = re.sub(r'[^\w\s]', '', song_name).lower().strip()
        query = urllib.parse.quote(f"{song_name} official music video")

        search_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video"
            f"&videoCategoryId=10&maxResults=5&key={YOUTUBE_API_KEY}"
        )
        resp = requests.get(search_url, timeout=5)
        if resp.status_code == 429:
            logger.warning("Rate limit exceeded, retrying after delay")
            time.sleep(10)
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
        original_channel = original_video["snippet"]["channelTitle"].lower()

        video_url = (
            f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,statistics"
            f"&id={original_video_id}&key={YOUTUBE_API_KEY}"
        )
        video_resp = requests.get(video_url, timeout=5)
        if video_resp.status_code != 200:
            logger.error(f"Video details API error: {video_resp.status_code} - {video_resp.text}")
            return None
        video_details = video_resp.json().get('items', [{}])[0]

        related_url = (
            f"https://www.googleapis.com/youtube/v3/search?part=snippet&relatedToVideoId={original_video_id}"
            f"&type=video&videoCategoryId=10&maxResults=20&key={YOUTUBE_API_KEY}"
        )
        related_resp = requests.get(related_url, timeout=5)
        if related_resp.status_code != 200:
            logger.error(f"Related videos API error: {related_resp.status_code} - {related_resp.text}")
            return None
        related_items = related_resp.json().get('items', [])
        if not related_items:
            logger.warning(f"No related videos found for video ID: {original_video_id}")
            return None

        suggestions = []
        unwanted_keywords = ['live', 'cover', 'remix', 'karaoke', 'instrumental', 'tutorial', 'reaction', 'lyrics']
        for item in related_items:
            title = item["snippet"]["title"].lower()
            channel = item["snippet"]["channelTitle"].lower()
            if any(keyword in title for keyword in unwanted_keywords):
                continue
            
            video_id = item["id"]["videoId"]
            video_details_url = (
                f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,statistics"
                f"&id={video_id}&key={YOUTUBE_API_KEY}"
            )
            video_details_resp = requests.get(video_details_url, timeout=5)
            if video_details_resp.status_code != 200:
                continue
            
            video_details_item = video_details_resp.json().get('items', [{}])[0]
            video_duration = video_details_item.get("contentDetails", {}).get("duration", "")
            video_views = int(video_details_item.get("statistics", {}).get("viewCount", 0))

            match = re.search(r'(\d+)M', video_duration)
            minutes = int(match.group(1)) if match else 0
            if "PT" in video_duration and minutes < 1:
                continue

            score = 1.0
            if "official video" in title or "official music video" in title:
                score += 0.8
            if any(word in title for word in original_title.split()):
                score += 0.5
            if channel == original_channel:
                score += 0.4
            if video_views > 100000:
                score += 0.3 * (video_views / 1000000)
            suggestions.append({
                "title": item["snippet"]["title"],
                "artist": item["snippet"]["channelTitle"],
                "youtube_video_id": video_id,
                "score": min(score, 3.0)
            })
        return suggestions[:10]

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching suggestions for {song_name}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error for {song_name}: {str(e)}")
        return None

def combine_suggestions(song_names: List[str]) -> List[dict]:
    """
    Combine suggestions from multiple songs, rank by score, and ensure uniqueness.
    Excludes suggestions that match input song titles.
    If no suggestions are found, it triggers a fallback to popular songs.
    """
    all_suggestions = []
    video_id_set = set()
    # Normalize input song titles for comparison
    normalized_input_songs = {re.sub(r'[^\w\s]', '', song).lower().strip() for song in song_names}

    for song in song_names:
        suggestions = get_youtube_suggestions(song)
        if suggestions:
            for suggestion in suggestions:
                normalized_suggestion_title = re.sub(r'[^\w\s]', '', suggestion["title"]).lower().strip()
                if (suggestion["youtube_video_id"] not in video_id_set and 
                    normalized_suggestion_title not in normalized_input_songs):
                    all_suggestions.append(suggestion)
                    video_id_set.add(suggestion["youtube_video_id"])

    if not all_suggestions:
        logger.info("No suggestions found from liked songs, triggering fallback.")
        fallback_suggestions = get_popular_song_fallback(song_names)
        if fallback_suggestions:
            return fallback_suggestions

    ranked_suggestions = sorted(all_suggestions, key=lambda x: x["score"], reverse=True)
    unique_suggestions = []
    seen_titles = set()
    for suggestion in ranked_suggestions:
        title = suggestion["title"].lower()
        if title not in seen_titles:
            unique_suggestions.append(suggestion)
            seen_titles.add(title)

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
    description="Returns suggestions based on a list of liked songs for a user, excluding the input songs. Falls back to popular songs if no matches are found."
)
async def post_suggestions(request: LikedSongsRequest):
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YouTube API key not configured on the server.")
    if not request.songs:
        raise HTTPException(status_code=400, detail="At least one song must be provided in the request.")
    
    liked_songs_store[request.user_id] = request.songs
    suggestions = combine_suggestions(request.songs)
    
    if not suggestions:
        raise HTTPException(status_code=404, detail="Could not find any suggestions, and the fallback mechanism also failed.")
    
    return JSONResponse(content={"suggestions": suggestions})

@app.get("/health", summary="Health check")
async def health_check():
    return {"status": "healthy"}
