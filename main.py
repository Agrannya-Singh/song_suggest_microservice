import os
import requests
import logging
import re
from collections import Counter
from functools import lru_cache
from typing import List, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi_socketio import SocketManager  # pip install fastapi-socketio
from ratelimit import limits, sleep_and_retry

# Initialize FastAPI app
app = FastAPI(
    title="Enhanced Music Suggestion Socket.IO API",
    description="Socket.IO API to manage liked songs and get music suggestions based on liked songs using YouTube Data API",
    version="1.1.0"
)

# Attach Socket.IO manager to FastAPI app
socket_manager = SocketManager(app=app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variable for YouTube API key
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# In-memory store for liked songs (user_id -> list of songs)
liked_songs_store: Dict[str, List[str]] = {}

# Cache and rate limit settings
CACHE_TTL = 3600  # 1 hour (used for lru_cache expiration indirectly)
RATE_LIMIT_CALLS = 100
RATE_LIMIT_PERIOD = 60  # seconds

# Pydantic models (used for validation or serialization)
class SongSuggestion(BaseModel):
    title: str
    artist: str
    youtube_video_id: str
    score: float


@sleep_and_retry
@limits(calls=RATE_LIMIT_CALLS, period=RATE_LIMIT_PERIOD)
@lru_cache(maxsize=100)
def get_youtube_suggestions(song_name: str) -> Optional[List[dict]]:
    """
    Fetch music suggestions from YouTube based on a song name with filtering and scoring.
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

        unwanted_keywords = ['live', 'cover', 'remix', 'karaoke', 'instrumental']
        suggestions = []

        for item in related_items:
            title = item["snippet"]["title"].lower()
            # Skip if unwanted keyword present
            if any(keyword in title for keyword in unwanted_keywords):
                continue

            score = 1.0  
            # Boost for title similarity
            if any(word in title for word in original_title.split()):
                score += 0.5
            # Boost for same artist/channel
            if item["snippet"]["channelTitle"].lower() == original_video["snippet"]["channelTitle"].lower():
                score += 0.3

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
    video_id_set = set()

    for song in song_names:
        suggestions = get_youtube_suggestions(song)
        if suggestions:
            for suggestion in suggestions:
                if suggestion["youtube_video_id"] not in video_id_set:
                    all_suggestions.append(suggestion)
                    video_id_set.add(suggestion["youtube_video_id"])

    # Sort by score descending and limit to top 5
    ranked_suggestions = sorted(all_suggestions, key=lambda x: x["score"], reverse=True)[:5]
    return ranked_suggestions


# ===============================
# Socket.IO event handlers
# ===============================

@socket_manager.on('connect')
async def on_connect(sid, environ):
    logger.info(f"Client connected: {sid}")
    await socket_manager.emit('connect_response', {'message': 'Connected successfully!'}, to=sid)


@socket_manager.on('disconnect')
def on_disconnect(sid):
    logger.info(f"Client disconnected: {sid}")


@socket_manager.on('get_liked_songs')
async def handle_get_liked_songs(sid, data):
    """
    Client sends: {"user_id": "some_user_id"}
    Server responds with liked songs list.
    """
    user_id = data.get('user_id')
    if not user_id:
        await socket_manager.emit('error', {'error': 'user_id is required'}, to=sid)
        return

    liked_songs = liked_songs_store.get(user_id, [])
    await socket_manager.emit('liked_songs_response', {'liked_songs': liked_songs}, to=sid)


@socket_manager.on('post_suggestions')
async def handle_post_suggestions(sid, data):
    """
    Client sends: {"user_id": "some_user_id", "songs": ["song1", "song2", ...]}
    Server responds with music suggestions.
    """
    user_id = data.get('user_id')
    songs = data.get('songs')

    if not YOUTUBE_API_KEY:
        await socket_manager.emit('suggestions_error', {'error': 'YouTube API key not configured'}, to=sid)
        return

    if not user_id or not songs or not isinstance(songs, list) or len(songs) == 0:
        await socket_manager.emit('suggestions_error', {'error': 'user_id and non-empty songs list are required'}, to=sid)
        return

    # Store liked songs for user
    liked_songs_store[user_id] = songs

    # Get combined suggestions
    suggestions = combine_suggestions(songs)

    if not suggestions:
        await socket_manager.emit('suggestions_error', {'error': 'No suggestions found for the given songs'}, to=sid)
        return

    serialized = [SongSuggestion(**s).dict() for s in suggestions]

    await socket_manager.emit('suggestions_response', {'suggestions': serialized}, to=sid)


@socket_manager.on('health_check')
async def handle_health_check(sid):
    await socket_manager.emit('health_status', {'status': 'healthy'}, to=sid)
