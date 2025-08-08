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

# (The mood mapping and helper functions remain the same)
# ...

# --- Core Functions ---

@lru_cache(maxsize=1)
def get_spotify_token():
    """
    Fetches an access token from the Spotify API with detailed error logging.
    """
    auth_url = "https://accounts.spotify.com/api/token"
    
    # Check if credentials are loaded
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
            timeout=10 # Add a timeout
        )
        
        # ** NEW DEBUGGING BLOCK **
        # This will check the response even if it's not a complete crash.
        # If the status code is anything other than 200 (OK), we print the details.
        if response.status_code != 200:
            print(f"--- SPOTIFY AUTHENTICATION ERROR ---")
            print(f"Status Code: {response.status_code}")
            print(f"Response Body: {response.text}")
            print(f"------------------------------------")
            response.raise_for_status() # This will still raise an exception to stop the process
        
        return response.json()["access_token"]

    except requests.exceptions.RequestException as e:
        # This will catch network errors, timeouts, etc.
        print(f"--- NETWORK ERROR DURING SPOTIFY AUTH ---")
        print(f"Error: {e}")
        print(f"---------------------------------------")
        return None


# (The rest of the functions in this file remain the same)
# search_for_song, get_audio_features, etc.
# ...
def search_for_song(song_name: str, artist: str = ""):
    token = get_spotify_token()
    if not token: return None # Stop if we failed to get a token
    # ... rest of function
    return {}

def get_discover_playlist():
    token = get_spotify_token()
    if not token: return None
    # ... rest of function
    return []

def get_vibe_recommendations(genres: list = None, moods: list = None):
    token = get_spotify_token()
    if not token: return None
    # ... rest of function
    return []
