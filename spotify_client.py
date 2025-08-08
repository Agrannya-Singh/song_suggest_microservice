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
from functools import lru_cache
from dotenv import load_dotenv

# --- Initial Setup ---

# Load environment variables from the .env file.
load_dotenv()

# Retrieve Spotify credentials from environment variables.
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Base URL for all Spotify API endpoints.
SPOTIFY_API_URL = "https://api.spotify.com/v1"

# --- Core Functions ---

@lru_cache(maxsize=1)
def get_spotify_token():
    """
    Fetches an access token from the Spotify API using the Client Credentials Flow.

    This flow is used for server-to-server authentication where no user is
    involved. The token is cached in memory using `@lru_cache` to avoid
    unnecessary re-authentication for every API call. The cache size is 1
    because the token is the same for the entire application.

    Returns:
        str: A Spotify API access token.

    Raises:
        requests.exceptions.HTTPError: If the request to Spotify fails.
    """
    auth_url = "https://accounts.spotify.com/api/token"

    # Encode the client ID and secret as required by the Spotify API.
    auth_header = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()

    # The body of the request to get the token.
    auth_data = {"grant_type": "client_credentials"}

    # Make the POST request to the Spotify token endpoint.
    response = requests.post(
        auth_url,
        headers={"Authorization": f"Basic {auth_header}"},
        data=auth_data
    )

    # Raise an exception if the request was not successful (e.g., 4xx or 5xx).
    response.raise_for_status()

    # Extract and return the access token from the JSON response.
    return response.json()["access_token"]


def search_for_song(song_name: str, artist: str = ""):
    """
    Searches for a song on Spotify and returns its essential details.

    Args:
        song_name (str): The name of the song to search for.
        artist (str, optional): The name of the artist to narrow down the search.

    Returns:
        dict | None: A dictionary containing the song's Spotify ID, name, and
                      artist, or None if the song could not be found.
    """
    # Get a valid access token.
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Construct the search query.
    query = f"track:{song_name} artist:{artist}" if artist else f"track:{song_name}"
    params = {"q": query, "type": "track", "limit": 1}

    # Make the GET request to the Spotify search endpoint.
    response = requests.get(f"{SPOTIFY_API_URL}/search", headers=headers, params=params)

    # Check if the request was successful and if any tracks were found.
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

    Args:
        spotify_id (str): The unique Spotify ID for the track.

    Returns:
        dict | None: A dictionary containing the desired audio features,
                      or None if the features could not be retrieved.
    """
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Make the GET request to the audio-features endpoint.
    response = requests.get(f"{SPOTIFY_API_URL}/audio-features/{spotify_id}", headers=headers)

    if response.status_code == 200:
        features = response.json()
        # Return a dictionary with only the features we care about.
        return {
            "danceability": features.get("danceability"),
            "energy": features.get("energy"),
            "valence": features.get("valence"),
            "tempo": features.get("tempo"),
        }
    return None
