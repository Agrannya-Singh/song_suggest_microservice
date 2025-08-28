import os
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Tuple
from functools import lru_cache
import redis
import json
import logging
import re
import urllib.parse
import time
import random
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db import init_db, get_read_session, get_write_sessions, User, UserLikedSong, VideoFeature, QueryCache

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
REDIS_URL = os.getenv("REDIS_URL")
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "3600"))

# Validate API key at startup
if not YOUTUBE_API_KEY:
    logger.warning("YouTube API key not found. Please set YOUTUBE_API_KEY environment variable.")
else:
    logger.info("YouTube API key loaded successfully.")

# Optional Redis client
redis_client: Optional[redis.Redis] = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            redis_client.ping()
            logger.info("Connected to Redis successfully.")
        except Exception:
            logger.warning("Redis reachable but ping failed; continuing without strict dependency.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        redis_client = None

@app.on_event("startup")
def on_startup() -> None:
    # Initialize database schema
    init_db()

# In-memory store for liked songs (kept for backward-compat/local cache)
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

# Simple in-process cache for suggestions: {key: (timestamp, suggestions)}
_suggestion_cache: Dict[str, Tuple[float, List[dict]]] = {}

def _cache_get(key: str) -> Optional[List[dict]]:
    now = time.time()
    entry = _suggestion_cache.get(key)
    if not entry:
        return None
    ts, data = entry
    if now - ts > CACHE_TTL:
        _suggestion_cache.pop(key, None)
        return None
    return data

def _cache_set(key: str, value: List[dict]) -> None:
    _suggestion_cache[key] = (time.time(), value)

def _persist_user_likes_write_through(user_external_id: str, songs: List[str]) -> None:
    for db in get_write_sessions():
        try:
            user = db.query(User).filter_by(user_id=user_external_id).one_or_none()
            if not user:
                user = User(user_id=user_external_id)
                db.add(user)
                db.flush()
            db.query(UserLikedSong).filter_by(user_id=user.id).delete()
            for s in songs:
                db.add(UserLikedSong(user_id=user.id, song_name=s))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Write-through failed for user {user_external_id}: {e}")
        finally:
            db.close()

def _load_user_likes(user_external_id: str) -> List[str]:
    db = get_read_session()
    try:
        user = db.query(User).filter_by(user_id=user_external_id).one_or_none()
        if not user:
            return []
        rows = db.query(UserLikedSong).filter_by(user_id=user.id).all()
        return [r.song_name for r in rows]
    finally:
        db.close()

# --- START OF NEW FALLBACK FUNCTION ---
def get_popular_song_fallback() -> Optional[List[dict]]:
    """
    Fetches a popular music video from YouTube's charts as a fallback.
    Filters for videos with more than 100 million views.
    """
    logger.info("Executing fallback: searching for a popular song.")
    try:
        # Use the 'videos' endpoint with the 'mostPopular' chart for the music category
        # The 'videos' endpoint with chart='mostPopular' is a reliable way to get popular videos. [8]
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

        # Filter for songs with over 100 million views
        popular_songs_high_views = [
            item for item in items
            if 'viewCount' in item.get('statistics', {}) and int(item['statistics']['viewCount']) > 100000000
        ]

        if not popular_songs_high_views:
            logger.warning("No songs with over 100M views in the current popular chart, returning from top of chart.")
            # If no song has 100M+ views, return a random one from the initial popular list
            if items:
                song = random.choice(items)
                return [{
                    "title": song["snippet"]["title"],
                    "artist": song["snippet"]["channelTitle"],
                    "youtube_video_id": song["id"],
                    "score": 1.0  # Assign a base score
                }]
            return None


        # Select a random song from the highly popular list
        song = random.choice(popular_songs_high_views)

        return [{
            "title": song["snippet"]["title"],
            "artist": song["snippet"]["channelTitle"],
            "youtube_video_id": song["id"],
            "score": 1.0  # Assign a base score
        }]

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during fallback search: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during fallback: {str(e)}")
        return None
# --- END OF NEW FALLBACK FUNCTION ---

@lru_cache(maxsize=128)
def get_youtube_suggestions(song_name: str) -> Optional[List[dict]]:
    """
    Fetch music suggestions from YouTube with improved filtering and genre-based scoring.
    """
    try:
        # Normalize song name and create a more specific query
        song_name = re.sub(r'[^\w\s]', '', song_name).lower().strip()
        query = urllib.parse.quote(f"{song_name} official music video")

        # Step 1: Search for the song
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

        # Build seed text from original video's snippet
        seed_text = original_video["snippet"].get("title", "") + " " + \
                    original_video["snippet"].get("channelTitle", "") + " " + \
                    original_video["snippet"].get("description", "")

        # Step 2: Fetch video details for duration
        video_url = (
            f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,statistics"
            f"&id={original_video_id}&key={YOUTUBE_API_KEY}"
        )
        video_resp = requests.get(video_url, timeout=5)
        if video_resp.status_code != 200:
            logger.error(f"Video details API error: {video_resp.status_code} - {video_resp.text}")
            return None
        video_details = video_resp.json().get('items', [{}])[0]

        # Step 3: Find related videos
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

        # Step 4: Fetch details for related items, filter and score with TF-IDF similarity
        suggestions = []
        unwanted_keywords = ['live', 'cover', 'remix', 'karaoke', 'instrumental', 'tutorial', 'reaction', 'lyrics']
        # Batch fetch details for all related video IDs
        related_ids = [it["id"]["videoId"] for it in related_items if "videoId" in it.get("id", {})]
        if not related_ids:
            return None
        # Fetch snippet+details+stats for richer features
        details_url = (
            f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id={','.join(related_ids)}&key={YOUTUBE_API_KEY}"
        )
        details_resp = requests.get(details_url, timeout=8)
        if details_resp.status_code != 200:
            logger.error(f"Details batch API error: {details_resp.status_code} - {details_resp.text}")
            return None
        details_map = {item["id"]: item for item in details_resp.json().get("items", [])}

        # Build corpus for TF-IDF: [seed_text] + [candidate_texts]
        candidate_texts = []
        candidate_objects = []
        for item in related_items:
            title = item["snippet"]["title"].lower()
            channel = item["snippet"]["channelTitle"].lower()
            if any(keyword in title for keyword in unwanted_keywords):
                continue
            vid = item["id"].get("videoId")
            if not vid:
                continue
            details = details_map.get(vid)
            if not details:
                continue
            duration = details.get("contentDetails", {}).get("duration", "")
            stats = details.get("statistics", {})
            video_views = int(stats.get("viewCount", 0) or 0)
            # Skip ultra short videos (< 1 minute)
            match = re.search(r"(\d+)M", duration)
            minutes = int(match.group(1)) if match else 0
            if "PT" in duration and minutes < 1:
                continue

            snippet = details.get("snippet", {})
            desc = snippet.get("description", "")
            tags = snippet.get("tags", [])
            combined_text = " ".join([
                snippet.get("title", ""),
                snippet.get("channelTitle", ""),
                desc,
                " ".join(tags) if isinstance(tags, list) else str(tags),
            ])

            # Heuristic base score
            base_score = 1.0
            if "official video" in title or "official music video" in title:
                base_score += 0.8
            if any(word in title for word in original_title.split()):
                base_score += 0.5
            if channel == original_channel:
                base_score += 0.4
            if video_views > 100000:
                base_score += 0.3 * (video_views / 1000000)

            candidate_texts.append(combined_text)
            candidate_objects.append((vid, snippet.get("title", ""), snippet.get("channelTitle", ""), base_score))

        if not candidate_objects:
            return None

        vectorizer = TfidfVectorizer(max_features=5000, stop_words="english")
        tfidf_matrix = vectorizer.fit_transform([seed_text] + candidate_texts)
        sims = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

        for (vid, title_raw, channel_raw, base), sim in zip(candidate_objects, sims):
            total_score = base + 1.5 * float(sim)
            suggestions.append({
                "title": title_raw,
                "artist": channel_raw,
                "youtube_video_id": vid,
                "score": min(total_score, 4.0)
            })

        # Sort by score desc and cap
        suggestions = sorted(suggestions, key=lambda x: x["score"], reverse=True)
        return suggestions[:10]

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching suggestions for {song_name}: {str(e)}")
        return None
        logger.error(f"Unexpected error for {song_name}: {str(e)}")
        return None

# --- MODIFIED combine_suggestions TO INCLUDE FALLBACK ---
def combine_suggestions(song_names: List[str]) -> List[dict]:
    """
    Combine suggestions from multiple songs, rank by score, and ensure uniqueness.
    If no suggestions are found, it triggers a fallback to popular songs.
    """
    # Use cache to reduce latency
    cache_key = "|".join(sorted([s.lower().strip() for s in song_names]))
    cached: Optional[List[dict]] = None
    if redis_client:
        try:
            val = redis_client.get(f"suggestions:{cache_key}")
            if val:
                cached = json.loads(val)
        except Exception as e:
            logger.warning(f"Redis get failed: {e}")
    if cached is None:
        cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    all_suggestions = []
    video_id_set = set()
    for song in song_names:
        suggestions = get_youtube_suggestions(song)
        if suggestions:
            for suggestion in suggestions:
                if suggestion["youtube_video_id"] not in video_id_set:
                    all_suggestions.append(suggestion)
                    video_id_set.add(suggestion["youtube_video_id"])

    # If no suggestions after checking all songs, use the fallback
    if not all_suggestions:
        logger.info("No suggestions found from liked songs, triggering fallback.")
        fallback_suggestions = get_popular_song_fallback()
        if fallback_suggestions:
            return fallback_suggestions

    # Rank and deduplicate
    ranked_suggestions = sorted(all_suggestions, key=lambda x: x["score"], reverse=True)
    unique_suggestions = []
    seen_titles = set()
    for suggestion in ranked_suggestions:
        title = suggestion["title"].lower()
        if title not in seen_titles:
            unique_suggestions.append(suggestion)
            seen_titles.add(title)

    result = unique_suggestions[:5]
    _cache_set(cache_key, result)
    if redis_client:
        try:
            redis_client.setex(f"suggestions:{cache_key}", REDIS_TTL_SECONDS, json.dumps(result))
        except Exception as e:
            logger.warning(f"Redis set failed: {e}")
    return result

@app.get(
    "/liked-songs",
    response_model=LikedSongsResponse,
    summary="Get liked songs",
    description="Returns the list of liked songs for a given user ID"
)
async def get_liked_songs(user_id: str = Query(..., min_length=1, description="User ID to fetch liked songs")):
    # Prefer DB, fallback to in-memory cache
    liked_songs = _load_user_likes(user_id)
    if not liked_songs:
        liked_songs = liked_songs_store.get(user_id, [])
    return JSONResponse(content={"liked_songs": liked_songs})

# --- MODIFIED post_suggestions FOR BETTER ERROR HANDLING ---
@app.post(
    "/suggestions",
    response_model=SuggestionResponse,
    summary="Get suggestions based on liked songs",
    description="Returns suggestions based on a list of liked songs for a user. Falls back to popular songs if no matches are found."
)
async def post_suggestions(request: LikedSongsRequest):
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YouTube API key not configured on the server.")
    if not request.songs:
        raise HTTPException(status_code=400, detail="At least one song must be provided in the request.")
    
    # Persist likes in DB and maintain in-memory cache
    liked_songs_store[request.user_id] = request.songs
    _persist_user_likes_write_through(request.user_id, request.songs)
    suggestions = combine_suggestions(request.songs)
    
    if not suggestions:
        raise HTTPException(status_code=404, detail="Could not find any suggestions, and the fallback mechanism also failed.")
    
    return JSONResponse(content={"suggestions": suggestions})

@app.get("/health", summary="Health check")
async def health_check():
    return {"status": "healthy"}
