from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import requests  # For calling YouTube API
import os

app = FastAPI()

# Request and response models
class MusicRequest(BaseModel):
    liked_songs: List[str]

class SongSuggestion(BaseModel):
    title: str
    artist: str
    youtube_video_id: str

class SuggestSongsResponse(BaseModel):
    suggested_songs: List[SongSuggestion]

# YouTube API configuration (Add your API key as environment variable)
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

def get_youtube_suggestions(song_name: str):
    # Search YouTube for a song. You can expand this to make more ML based suggestions.
    search_url = (
        f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={song_name}&type=video&key={YOUTUBE_API_KEY}"
    )
    resp = requests.get(search_url)
    if resp.status_code != 200:
        return None
    items = resp.json().get('items', [])
    if not items:
        return None
    # Take the top result
    item = items[0]
    return {
        "title": item["snippet"]["title"],
        "artist": item["snippet"]["channelTitle"],
        "youtube_video_id": item["id"]["videoId"],
    }

@app.post("/suggest-songs", response_model=SuggestSongsResponse)
async def suggest_songs(req: MusicRequest):
    # Basic algorithm: for each liked song, fetch related YouTube results
    similar_songs = []
    for song in req.liked_songs:
        suggestion = get_youtube_suggestions(song + " music")
        if suggestion:
            similar_songs.append(suggestion)
    # You can deduplicate and enrich this with ML/embedding models
    return SuggestSongsResponse(suggested_songs=similar_songs)
