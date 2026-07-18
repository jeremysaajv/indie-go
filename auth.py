import os
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from config import AUTHORIZED_USER_IDS, DEVELOPER_USER_IDS, SCOPES

load_dotenv(dotenv_path=Path(__file__).parent / ".env")


def _redirect_uri():
    """Read REDIRECT_URI at call time — Streamlit secrets aren't in os.environ at import time."""
    try:
        import streamlit as st
        return st.secrets.get("REDIRECT_URI", os.getenv("REDIRECT_URI", "http://127.0.0.1:8080"))
    except Exception:
        return os.getenv("REDIRECT_URI", "http://127.0.0.1:8080")

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"


def get_auth_url():
    """Generate Spotify OAuth authorization URL for artist login."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": SCOPES,
        "show_dialog": "true",
    }
    param_str = "&".join([f"{k}={v}" for k, v in params.items()])
    return f"{SPOTIFY_AUTH_URL}?{param_str}"


def exchange_code_for_token(code):
    """Exchange Spotify authorization code for access token."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

    auth_str = f"{client_id}:{client_secret}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()

    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(),
    }

    response = requests.post(SPOTIFY_TOKEN_URL, headers=headers, data=data)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Token exchange failed: {response.status_code} — {response.text}")
        return None


def get_current_user(access_token):
    """Fetch the logged-in user's Spotify profile."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.spotify.com/v1/me", headers=headers)
    if response.status_code == 200:
        return response.json()
    return None


def check_authorization(user_id):
    """
    Verification Mapping. Returns a role dict:
      {"role": "developer"}
      {"role": "artist", "artist_id": "..."}
      {"role": "public"}
    """
    if user_id in DEVELOPER_USER_IDS:
        return {"role": "developer"}
    if user_id in AUTHORIZED_USER_IDS:
        return {"role": "artist", "artist_id": AUTHORIZED_USER_IDS[user_id]}
    # Any authenticated Spotify user is treated as an artist —
    # they'll be prompted to paste their own artist page URL.
    return {"role": "artist"}


def get_spotify_cc_client():
    """
    Return a Spotipy client using Client Credentials flow.
    Used for all public artist data fetching — no user login required.
    """
    return spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        )
    )
