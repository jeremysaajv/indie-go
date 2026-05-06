from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from auth import get_spotify_cc_client
from audio_analyzer import analyze_artist_audio


def get_full_artist_data(artist_id):
    """
    Fetches artist data from Spotify. Every API call is wrapped individually
    so Dev Mode restrictions on specific endpoints never crash the app —
    the system degrades gracefully and uses whatever data it can get.
    """
    sp = get_spotify_cc_client()
    result = {
        "name": "Unknown Artist",
        "artist_id": artist_id,
        "genres": [],
        "image_url": None,
        "albums": [],
        "momentum_proxy": "No catalog data available",
        "avg_bpm": None,
        "energy_label": "N/A",
        "valence_label": "N/A",
        "has_explicit": False,
        "staccato_bio": None,
        "legacy_bio": None,
        "spotify_followers": None,
        "spotify_url": f"https://open.spotify.com/artist/{artist_id}",
    }

    # ── 1. Artist profile ─────────────────────────────────────────────────────
    try:
        artist = sp.artist(artist_id)
        result["name"] = artist.get("name", "Unknown Artist")
        result["genres"] = artist.get("genres", [])
        if artist.get("images"):
            result["image_url"] = artist["images"][0]["url"]
        followers = artist.get("followers", {}).get("total")
        if followers is not None:
            result["spotify_followers"] = followers
    except Exception as e:
        raise Exception(f"Could not fetch artist profile: {e}")

    # ── 2. Albums / singles ───────────────────────────────────────────────────
    albums = []
    for limit in [10, 5, 1]:  # Step down if Spotify rejects the limit
        try:
            raw = sp.artist_albums(artist_id, album_type="album,single,appears_on", limit=limit)
            albums = raw.get("items", [])
            break
        except Exception:
            continue

    # Process releases — for appears_on, find the specific track
    seen = set()
    for album in albums:
        album_name = album.get("name", "")
        album_type = album.get("album_type", "single")
        album_id   = album.get("id")
        release_date = album.get("release_date", "Unknown")

        if album_type == "appears_on" and album_id:
            # Find the specific track this artist appears on
            try:
                tracks_raw = sp.album_tracks(album_id, limit=50)
                for track in tracks_raw.get("items", []):
                    track_artists = [a.get("id") for a in track.get("artists", [])]
                    if artist_id in track_artists:
                        track_name = track.get("name", "Unknown Track")
                        entry_key = track_name.lower()
                        if entry_key not in seen:
                            seen.add(entry_key)
                            result["albums"].append({
                                "name": track_name,
                                "release_date": release_date,
                                "album_type": "feature",
                                "id": album_id,
                            })
            except Exception:
                pass  # Skip if track lookup fails
        else:
            entry_key = album_name.lower()
            if entry_key not in seen:
                seen.add(entry_key)
                result["albums"].append({
                    "name": album_name,
                    "release_date": release_date,
                    "album_type": album_type,
                    "id": album_id,
                })

    result["momentum_proxy"] = calculate_momentum_proxy(result["albums"])

    # ── 3. Track IDs for audio features ──────────────────────────────────────
    track_ids = []

    # Try top-tracks first (may be restricted in Dev Mode)
    try:
        top = sp.artist_top_tracks(artist_id, country="AU")
        for t in top.get("tracks", [])[:10]:
            if t.get("id"):
                track_ids.append(t["id"])
            if t.get("explicit"):
                result["has_explicit"] = True
    except Exception:
        pass

    # Fallback: pull tracks from albums
    if not track_ids and result["albums"]:
        for album in result["albums"][:3]:
            if not album.get("id"):
                continue
            try:
                atracks = sp.album_tracks(album["id"], limit=5)
                for t in atracks.get("items", []):
                    if t.get("id"):
                        track_ids.append(t["id"])
                    if t.get("explicit"):
                        result["has_explicit"] = True
            except Exception:
                continue

    track_ids = list(set(track_ids))[:10]

    # ── 4. Audio features ─────────────────────────────────────────────────────
    if track_ids:
        try:
            features_raw = sp.audio_features(track_ids)
            audio_features = [f for f in features_raw if f is not None]

            if audio_features:
                tempos = [f["tempo"] for f in audio_features if f.get("tempo")]
                energies = [f["energy"] for f in audio_features if f.get("energy") is not None]
                valences = [f["valence"] for f in audio_features if f.get("valence") is not None]

                if tempos:
                    result["avg_bpm"] = round(sum(tempos) / len(tempos))
                if energies:
                    result["energy_label"] = map_energy(sum(energies) / len(energies))
                if valences:
                    result["valence_label"] = map_valence(sum(valences) / len(valences))
        except Exception:
            pass  # Audio features unavailable in Spotify Dev Mode 2026

    # ── 5. Audio analysis via Librosa (fallback when Spotify returns nothing) ──
    # Downloads up to 5 preview clips and computes real signal-based metrics.
    if result["avg_bpm"] is None:
        audio_metrics = analyze_artist_audio(result["albums"], sp)
        if audio_metrics:
            result["audio_debug"] = audio_metrics.get("debug", "")
            if audio_metrics.get("avg_bpm") is not None:
                result["avg_bpm"]       = audio_metrics["avg_bpm"]
                result["energy_label"]  = audio_metrics["energy_label"]
                result["valence_label"] = audio_metrics["valence_label"]
        else:
            result["audio_debug"] = "Audio analysis returned nothing."
    else:
        result["audio_debug"] = "Audio features sourced from Spotify API."

    return result


def calculate_momentum_proxy(albums):
    if not albums:
        return "No catalog data available"

    six_months_ago = datetime.now() - timedelta(days=180)
    recent_count = 0

    for album in albums:
        release_date = album.get("release_date", "")
        try:
            if len(release_date) >= 7:
                rel_date = datetime.strptime(release_date[:7], "%Y-%m")
                if rel_date >= six_months_ago:
                    recent_count += 1
        except ValueError:
            pass

    total = len(albums)
    if recent_count >= 3:
        return f"{recent_count} in 6 months - High Velocity"
    elif recent_count >= 1:
        return f"{recent_count} in 6 months - Active"
    elif total >= 5:
        return f"{total} releases - Established"
    else:
        return f"{total} release(s) - Building"


def map_energy(val):
    if val >= 0.8:
        return "High-Octane"
    elif val >= 0.6:
        return "Driving"
    elif val >= 0.4:
        return "Controlled Intensity"
    else:
        return "Atmospheric"


def map_valence(val):
    if val >= 0.7:
        return "Upbeat / Positive"
    elif val >= 0.5:
        return "Balanced"
    elif val >= 0.3:
        return "Introspective"
    else:
        return "Melancholic / Atmospheric"
