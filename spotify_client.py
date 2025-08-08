# ==============================================================================
# SPOTIFY API CLIENT
# ==============================================================================
# This module is responsible for all communication with the Spotify Web API.
# It now includes a powerful function to get recommendations based on
# user-selected genres and moods.
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
# This dictionary translates user-friendly mood names into the technical
# audio feature parameters required by the Spotify recommendations endpoint.
MOOD_TO_SPOTIFY_PARAMS = {
    "chill": {"target_energy": 0.4, "target_danceability": 0.5},
    "upbeat": {"min_valence": 0.6, "min_energy": 0.6},
    "workout": {"min_energy": 0.7, "min_tempo": 120},
    "party": {"min_danceability": 0.7, "min_energy": 0.7},
    "sad": {"max_valence": 0.3},
    "focus": {"max_energy": 0.4, "min_instrumentalness": 0.5},
    "romantic": {"target_valence": 0.7, "max_energy": 0.6},
    # ** NEW MOOD ADDED **
    "energetic": {"min_energy": 0.8, "min_valence": 0.5}
}


# --- Helper Functions ---
def _clean_song_name(song_name: str) -> str:
    # (This function remains the same)
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
    # (This function remains the same)
    auth_url = "https://accounts.spotify.com/api/token"
    auth_header = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    auth_data = {"grant_type": "client_credentials"}
    response = requests.post(
        auth_url,
        headers={"Authorization": f"Basic {auth_header}"},
        data=auth_data
    )
    response.raise_for_status()
    return response.json()["access_token"]

def search_for_song(song_name: str, artist: str = ""):
    # (This function remains the same)
    # ...
    return {}

def get_audio_features(spotify_id: str):
    # (This function remains the same)
    # ...
    return {}

def get_discover_playlist():
    """Fetches the default "Today's Top Hits" playlist."""
    # (This function remains the same, used as a fallback)
    # ...
    return []

def get_vibe_recommendations(genres: list = None, moods: list = None):
    """
    ** NEW FUNCTION **
    Gets recommendations from Spotify based on seed genres and target
    audio features derived from moods.

    Args:
        genres (list, optional): A list of Spotify genre seeds.
        moods (list, optional): A list of mood names from the frontend.

    Returns:
        list[dict] | None: A list of recommended tracks or None on failure.
    """
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    # Base parameters for the recommendation endpoint.
    params = {
        "limit": 20,
        "market": "US" # Use a specific market for better results
    }

    # Add genres to the query if provided.
    if genres:
        # Spotify expects a comma-separated string of up to 5 seeds.
        params["seed_genres"] = ",".join(genres[:5])

    # Add mood parameters to the query.
    if moods:
        for mood in moods:
            if mood.lower() in MOOD_TO_SPOTIFY_PARAMS:
                # Merge the dictionaries of parameters for each mood.
                params.update(MOOD_TO_SPOTIFY_PARAMS[mood.lower()])

    # We must have at least one seed (genre) to make a recommendation call.
    if "seed_genres" not in params:
        print("WARN: Cannot get vibe recommendations without at least one genre seed.")
        return None

    try:
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
