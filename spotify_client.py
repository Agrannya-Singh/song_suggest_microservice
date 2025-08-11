# ==============================================================================
# SPOTIFY API CLIENT (WITH ENHANCED DEBUGGING)
# ==============================================================================
# This version includes more detailed error logging in the token fetching
# function to help diagnose authentication issues.
# ------------------------------------------------------------------------------

# --- Imports ---
import os
import requests
import base64
import re
from functools import lru_cache
from dotenv import load_dotenv

# --- Initial Setup ---
load_dotenv()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_API_URL = "https://api.spotify.com/v1"
DISCOVER_PLAYLIST_ID = "37i9dQZF1DXcBWIGoYBM5M"

# --- Mappings for "Find Your Vibe" ---
MOOD_TO_SPOTIFY_PARAMS = {
    "chill": {"target_energy": 0.4, "target_danceability": 0.5},
    "upbeat": {"min_valence": 0.6, "min_energy": 0.6},
    "workout": {"min_energy": 0.7, "min_tempo": 120},
    "party": {"min_danceability": 0.7, "min_energy": 0.7},
    "sad": {"max_valence": 0.3},
    "focus": {"max_energy": 0.4, "min_instrumentalness": 0.5},
    "romantic": {"target_valence": 0.7, "max_energy": 0.6},
    "energetic": {"min_energy": 0.8, "min_valence": 0.5}
}


# --- Helper Functions ---
def _clean_song_name(song_name: str) -> str:
    cleaned_name = re.sub(r'[\(\[].*?[\)\]]', '', song_name)
    keywords_to_remove = [
        'official music video', 'official video', 'lyric video',
        'lyrics', 'audio', 'hd', 'full', 'video', 'music'
    ]
    for keyword in keywords_to_remove:
        cleaned_name = re.sub(r'\b' + re.escape(keyword) + r'\b', '', cleaned_name, flags=re.IGNORECASE)
    if ' - ' in cleaned_name:
        cleaned_name = cleaned_name.split(' - ')[-1]
    return cleaned_name.strip()

# --- Core Functions ---

@lru_cache(maxsize=1)
def get_spotify_token():
    """
    Fetches an access token from the Spotify API with detailed error logging.
    """
    auth_url = "https://accounts.spotify.com/api/token"
    
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("FATAL ERROR: SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET not found in environment.")
        return None

    auth_header = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    auth_data = {"grant_type": "client_credentials"}

    try:
        response = requests.post(
            auth_url,
            headers={"Authorization": f"Basic {auth_header}"},
            data=auth_data,
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"--- SPOTIFY AUTHENTICATION ERROR ---")
            print(f"Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")
            print(f"------------------------------------")
            response.raise_for_status()
        
        return response.json()["access_token"]

    except requests.exceptions.RequestException as e:
        print(f"--- NETWORK ERROR DURING SPOTIFY AUTH ---")
        print(f"Error: {e}")
        print(f"---------------------------------------")
        return None


def search_for_song(song_name: str, artist: str = ""):
    token = get_spotify_token()
    if not token: return None
    
    cleaned_name = _clean_song_name(song_name)
    headers = {"Authorization": f"Bearer {token}"}
    query = f"track:{cleaned_name} artist:{artist}" if artist else f"track:{cleaned_name}"
    params = {"q": query, "type": "track", "limit": 1}
    response = requests.get(f"{SPOTIFY_API_URL}/search", headers=headers, params=params)
    if response.status_code == 200 and response.json()["tracks"]["items"]:
        track = response.json()["tracks"]["items"][0]
        return {
            "spotify_id": track["id"],
            "name": track["name"],
            "artist": track["artists"][0]["name"]
        }
    return None

def get_audio_features(spotify_id: str):
    token = get_spotify_token()
    if not token: return None
    
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{SPOTIFY_API_URL}/audio-features/{spotify_id}", headers=headers)
    if response.status_code == 200:
        features = response.json()
        return {
            "danceability": features.get("danceability"),
            "energy": features.get("energy"),
            "valence": features.get("valence"),
            "tempo": features.get("tempo"),
        }
    return None

def get_discover_playlist():
    token = get_spotify_token()
    if not token: return None
    
    headers = {"Authorization": f"Bearer {token}"}
    playlist_url = f"{SPOTIFY_API_URL}/playlists/{DISCOVER_PLAYLIST_ID}/tracks"
    params = {"limit": 20}

    try:
        response = requests.get(playlist_url, headers=headers, params=params)
        response.raise_for_status()
        
        items = response.json().get("items", [])
        discover_songs = []
        for item in items:
            track = item.get("track")
            if track and track.get("id"):
                discover_songs.append({
                    "song_name": track["name"],
                    "artist_name": track["artists"][0]["name"],
                    "spotify_track_id": track["id"]
                })
        
        return discover_songs
    except Exception as e:
        print(f"ERROR: Could not fetch discover playlist: {e}")
        return None

def get_vibe_recommendations(genres: list = None, moods: list = None):
    token = get_spotify_token()
    if not token: return None
    
    params = {
        "limit": 20,
        "market": "US"
    }

    if genres:
        params["seed_genres"] = ",".join(genres[:5])

    if moods:
        for mood in moods:
            if mood.lower() in MOOD_TO_SPOTIFY_PARAMS:
                params.update(MOOD_TO_SPOTIFY_PARAMS[mood.lower()])

    if "seed_genres" not in params:
        return None

    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{SPOTIFY_API_URL}/recommendations", headers=headers, params=params)
        response.raise_for_status()
        
        tracks = response.json().get("tracks", [])
        recommendations = []
        for track in tracks:
            if track and track.get("id"):
                recommendations.append({
                    "song_name": track["name"],
                    "artist_name": track["artists"][0]["name"],
                    "spotify_track_id": track["id"]
                })
        
        return recommendations
    except Exception as e:
        print(f"ERROR: Could not fetch vibe recommendations: {e}")
        return None
