import os
import requests
import logging
from typing import List, Optional, Dict, Tuple
from functools import lru_cache
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis
import json
import time
import urllib.parse
import re
import random
from sqlalchemy.orm import Session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from db import init_db, get_read_session, get_write_sessions, User, UserLikedSong, QueryCache

# Load environment variables
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

# Environment variables
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "3600"))

# Validate API key at startup
if not YOUTUBE_API_KEY:
    logger.warning("YouTube API key not found. Please set YOUTUBE_API_KEY environment variable.")

# Optional Redis client
redis_client: Optional[redis.Redis] = None
if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("Connected to Redis successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Redis: {e}")
        redis_client = None

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


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# --- REPOSITORY PATTERN ---
# This class centralizes all database logic.
class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_liked_songs(self, user_id: str) -> List[str]:
        user = self.db.query(User).filter_by(user_id=user_id).one_or_none()
        if not user:
            return []
        rows = self.db.query(UserLikedSong).filter_by(user_id=user.id).all()
        return [r.song_name for r in rows]

    def persist_user_likes(self, user_id: str, songs: List[str]) -> None:
        user = self.db.query(User).filter_by(user_id=user_id).one_or_none()
        if not user:
            user = User(user_id=user_id)
            self.db.add(user)
            self.db.flush()

        existing_likes = {s.song_name for s in user.likes}
        new_likes = set(songs)

        songs_to_delete = existing_likes - new_likes
        if songs_to_delete:
            self.db.query(UserLikedSong).filter(
                UserLikedSong.user_id == user.id,
                UserLikedSong.song_name.in_(songs_to_delete)
            ).delete(synchronize_session='fetch')

        songs_to_add = new_likes - existing_likes
        for s in songs_to_add:
            self.db.add(UserLikedSong(user_id=user.id, song_name=s))

        self.db.commit()


# --- SERVICE PATTERN ---
# This class contains the core business logic for suggestions.
class SuggestionService:
    def __init__(self, api_key: str, redis_client: Optional[redis.Redis], redis_ttl: int):
        self.api_key = api_key
        self.redis_client = redis_client
        self.redis_ttl = redis_ttl

    def get_popular_song_fallback(self) -> Optional[List[dict]]:
        try:
            fallback_url = (f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics"
                            f"&chart=mostPopular&videoCategoryId=10&maxResults=50&key={self.api_key}")
            resp = requests.get(fallback_url, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Fallback API error: {resp.status_code} - {resp.text}")
                return None
            
            items = resp.json().get('items', [])
            if not items:
                logger.warning("Fallback could not retrieve any popular songs.")
                return None
            
            song = random.choice(items)
            return [{
                "title": song["snippet"]["title"],
                "artist": song["snippet"]["channelTitle"],
                "youtube_video_id": song["id"],
                "score": 1.0
            }]
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during fallback search: {str(e)}")
            return None

    @lru_cache(maxsize=128)
    def get_youtube_suggestions(self, song_name: str) -> Optional[List[dict]]:
        try:
            song_name = re.sub(r'[^\w\s]', '', song_name).lower().strip()
            query = urllib.parse.quote(f"{song_name} official music video")
            search_url = (f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video"
                          f"&videoCategoryId=10&maxResults=5&key={self.api_key}")
            resp = requests.get(search_url, timeout=5)
            if resp.status_code != 200: return None
            items = resp.json().get('items', [])
            if not items: return None

            original_video = items[0]
            original_video_id = original_video["id"]["videoId"]
            seed_text = " ".join([original_video["snippet"].get("title", ""), original_video["snippet"].get("channelTitle", "")])

            related_url = (f"https://www.googleapis.com/youtube/v3/search?part=snippet&relatedToVideoId={original_video_id}"
                           f"&type=video&videoCategoryId=10&maxResults=20&key={self.api_key}")
            related_resp = requests.get(related_url, timeout=5)
            if related_resp.status_code != 200: return None
            related_items = related_resp.json().get('items', [])
            if not related_items: return None

            related_ids = [it["id"]["videoId"] for it in related_items if "videoId" in it.get("id", {})]
            if not related_ids: return None

            details_url = (f"https://www.googleapis.com/youtube/v3/videos?part=snippet,contentDetails,statistics&id={','.join(related_ids)}&key={self.api_key}")
            details_resp = requests.get(details_url, timeout=8)
            details_map = {item["id"]: item for item in details_resp.json().get("items", [])}

            candidate_texts = []
            candidate_objects = []
            for item in related_items:
                vid = item["id"].get("videoId")
                details = details_map.get(vid)
                if not vid or not details: continue
                snippet = details.get("snippet", {})
                combined_text = " ".join([snippet.get("title", ""), snippet.get("channelTitle", ""), snippet.get("description", ""), " ".join(snippet.get("tags", []))])
                candidate_texts.append(combined_text)
                candidate_objects.append({"title": snippet.get("title", ""), "artist": snippet.get("channelTitle", ""), "youtube_video_id": vid, "score": 1.0})

            if not candidate_objects: return None
            
            vectorizer = TfidfVectorizer(max_features=5000, stop_words="english")
            tfidf_matrix = vectorizer.fit_transform([seed_text] + candidate_texts)
            sims = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

            for i, sim in enumerate(sims):
                candidate_objects[i]["score"] += 1.5 * float(sim)

            suggestions = sorted(candidate_objects, key=lambda x: x["score"], reverse=True)
            return suggestions[:10]
        except Exception as e:
            logger.error(f"Unexpected error for {song_name}: {str(e)}")
            return None

    def get_suggestions_for_songs(self, song_names: List[str]) -> List[dict]:
        cache_key = "|".join(sorted([s.lower().strip() for s in song_names]))
        
        cached = None
        if self.redis_client:
            try:
                val = self.redis_client.get(f"suggestions:{cache_key}")
                if val: cached = json.loads(val)
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")
        
        if cached is not None:
            return cached

        all_suggestions = []
        video_id_set = set()
        for song in song_names:
            suggestions = self.get_youtube_suggestions(song)
            if suggestions:
                for suggestion in suggestions:
                    if suggestion["youtube_video_id"] not in video_id_set:
                        all_suggestions.append(suggestion)
                        video_id_set.add(suggestion["youtube_video_id"])

        if not all_suggestions:
            logger.info("No suggestions found from liked songs, triggering fallback.")
            all_suggestions = self.get_popular_song_fallback() or []

        ranked_suggestions = sorted(all_suggestions, key=lambda x: x["score"], reverse=True)
        unique_suggestions = []
        seen_titles = set()
        for suggestion in ranked_suggestions:
            title = suggestion["title"].lower()
            if title not in seen_titles:
                unique_suggestions.append(suggestion)
                seen_titles.add(title)

        result = unique_suggestions[:5]
        if self.redis_client:
            try:
                self.redis_client.setex(f"suggestions:{cache_key}", self.redis_ttl, json.dumps(result))
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")
        
        return result


# --- DEPENDENCY INJECTION ---
# These functions provide class instances with database sessions.
def get_user_repository_read(db_session: Session = Depends(get_read_session)):
    return UserRepository(db=db_session)

def get_user_repository_write(db_sessions: List[Session] = Depends(get_write_sessions)):
    return [UserRepository(db=s) for s in db_sessions]

def get_suggestion_service():
    return SuggestionService(
        api_key=YOUTUBE_API_KEY,
        redis_client=redis_client,
        redis_ttl=REDIS_TTL_SECONDS
    )


# --- API ENDPOINTS ---
@app.get("/liked-songs", response_model=LikedSongsResponse, summary="Get liked songs",
         description="Returns the list of liked songs for a given user ID")
async def get_liked_songs(
    user_id: str = Query(..., min_length=1, description="User ID to fetch liked songs"),
    user_repo: UserRepository = Depends(get_user_repository_read)
):
    liked_songs = user_repo.get_liked_songs(user_id)
    return JSONResponse(content={"liked_songs": liked_songs})

@app.post("/suggestions", response_model=SuggestionResponse, summary="Get suggestions based on liked songs",
          description="Returns suggestions based on a list of liked songs for a user. Falls back to popular songs if no matches are found.")
async def post_suggestions(
    request: LikedSongsRequest,
    user_repos: List[UserRepository] = Depends(get_user_repository_write),
    suggestion_service: SuggestionService = Depends(get_suggestion_service)
):
    if not YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YouTube API key not configured on the server.")
    if not request.songs:
        raise HTTPException(status_code=400, detail="At least one song must be provided in the request.")

    # Persist likes using all write repositories
    for repo in user_repos:
        repo.persist_user_likes(request.user_id, request.songs)

    suggestions = suggestion_service.get_suggestions_for_songs(request.songs)
    
    if not suggestions:
        raise HTTPException(status_code=404, detail="Could not find any suggestions, and the fallback mechanism also failed.")
    
    return JSONResponse(content={"suggestions": suggestions})

@app.get("/health", summary="Health check")
async def health_check():
    return {"status": "healthy"}
