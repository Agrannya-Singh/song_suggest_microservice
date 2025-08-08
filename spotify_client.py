# ==============================================================================
# SPOTIFY API CLIENT
# ==============================================================================
# This module is responsible for all communication with the Spotify Web API.
# It handles authentication (using the Client Credentials Flow) and provides
# simple functions to search for songs and retrieve their audio features.
#
# By centralizing all Spotify-related code here, we keep the rest of the
# application clean and decoupled from the specifics of the Spotify API.
# ------------------------------------------------------------------------------

# --- Imports ---
import os
import requests
import base64
import re # Import the regular expressions module
from functools import lru_cache
from dotenv import load_dotenv

# --- Initial Setup ---

load_dotenv()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_API_URL = "https://api.spotify.com/v1"

# --- Helper Functions ---

def _clean_song_name(song_name: str) -> str:
    """
    Cleans a song title to improve Spotify search accuracy.

    This function removes common extraneous text like:
    - Text in parentheses or brackets (e.g., "(Official Music Video)")
    - Keywords like "lyric video", "official", "audio", "HD"
    - Separators like " - " which often precede a channel name.

    Args:
        song_name (str): The raw song title.

    Returns:
        str: The cleaned song title.
    """
    # Remove text in parentheses and brackets
    cleaned_name = re.sub(r'[\(\[].*?[\)\]]', '', song_name)

    # Remove common keywords (case-insensitive)
    keywords_to_remove = [
        'official music video', 'official video', 'lyric video',
        'lyrics', 'audio', 'hd', 'full', 'video', 'music'
    ]
    for keyword in keywords_to_remove:
        cleaned_name = re.sub(r'\b' + re.escape(keyword) + r'\b', '', cleaned_name, flags=re.IGNORECASE)

    # Remove the artist if it's separated by a hyphen, letting Spotify find it
    # e.g., "Bon Jovi - It's My Life" becomes "It's My Life"
    if ' - ' in cleaned_name:
        cleaned_name = cleaned_name.split(' - ')[-1]


    # Remove extra whitespace
    return cleaned_name.strip()


# --- Core Functions ---

@lru_cache(maxsize=1)
def get_spotify_token():
    """
    Fetches an access token from the Spotify API using the Client Credentials Flow.
    """
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
    """
    Searches for a song on Spotify using a cleaned title.
    """
    # **THIS IS THE KEY CHANGE**: Clean the song name before searching.
    cleaned_name = _clean_song_name(song_name)
    print(f"INFO: Original name: '{song_name}', Cleaned name for search: '{cleaned_name}'")

    token = get_spotify_token()
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
    """
    Gets audio features for a given Spotify track ID.
    """
    token = get_spotify_token()
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
