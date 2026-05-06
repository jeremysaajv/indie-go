"""
Indie-Go — Audio Analyzer
Computes real BPM, energy, and mood metrics from Spotify's 30-second
preview clips using Librosa signal processing.
No fabricated values. If audio is unavailable, returns None.
"""

import os
import tempfile
import requests
import numpy as np

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


# ─── Preview URL harvesting ───────────────────────────────────────────────────

def get_preview_urls(albums, sp, max_clips=5):
    """
    Scans the artist's most recent releases for tracks with preview URLs.
    Returns up to max_clips URLs. Stops as soon as we have enough.
    """
    preview_urls = []

    for album in albums[:5]:  # Only check 5 most recent releases
        album_id = album.get("id")
        if not album_id:
            continue
        try:
            tracks_raw = sp.album_tracks(album_id, limit=10)
            for track in tracks_raw.get("items", []):
                url = track.get("preview_url")
                if url:
                    preview_urls.append(url)
                if len(preview_urls) >= max_clips:
                    return preview_urls
        except Exception:
            continue

    return preview_urls


# ─── Single clip analysis ─────────────────────────────────────────────────────

def analyze_clip(preview_url):
    """
    Downloads a 30-second preview MP3 and extracts audio features.
    Returns a dict of raw signal features, or None on failure.
    """
    try:
        response = requests.get(preview_url, timeout=15)
        if response.status_code != 200:
            return None

        # Save to temp file — librosa needs a file path for MP3 decoding
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tmp.write(response.content)
        tmp.close()

        try:
            y, sr = librosa.load(tmp.name, duration=30, sr=22050)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

        if len(y) == 0:
            return None

        # BPM
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(np.atleast_1d(tempo)[0])

        # RMS Energy — overall loudness/intensity
        rms = float(np.mean(librosa.feature.rms(y=y)))

        # Spectral Centroid — tonal brightness (higher = brighter/happier)
        centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))

        # Zero Crossing Rate — noisiness indicator
        zcr = float(np.mean(librosa.feature.zero_crossing_rate(y)))

        return {
            "tempo": tempo,
            "rms": rms,
            "centroid": centroid,
            "zcr": zcr,
            "sr": sr,
        }

    except Exception as e:
        print(f"[AudioAnalyzer] Clip analysis failed: {e}")
        return None


# ─── Feature mapping ──────────────────────────────────────────────────────────

def map_energy(rms):
    """
    Maps RMS energy to a descriptive label.
    Typical music RMS range: 0.01 - 0.30
    """
    if rms >= 0.15:
        return "High-Octane"
    elif rms >= 0.09:
        return "Driving"
    elif rms >= 0.05:
        return "Controlled Intensity"
    else:
        return "Atmospheric"


def map_mood(centroid, sr=22050):
    """
    Maps spectral centroid to a mood descriptor.
    Higher centroid = brighter, more positive sound.
    Normalized against Nyquist frequency.
    """
    normalized = centroid / (sr / 2)
    if normalized >= 0.18:
        return "Upbeat / Positive"
    elif normalized >= 0.12:
        return "Balanced"
    elif normalized >= 0.08:
        return "Introspective"
    else:
        return "Melancholic / Atmospheric"


# ─── Main entry point ─────────────────────────────────────────────────────────

def analyze_artist_audio(albums, sp):
    """
    Main function called by the harvester.
    - Finds up to 5 preview URLs from recent releases
    - Analyzes each clip with Librosa
    - Averages results
    Returns {"avg_bpm": int, "energy_label": str, "valence_label": str, "debug": str}
    or None if no audio could be analyzed.
    """
    if not LIBROSA_AVAILABLE:
        return {"debug": "Librosa not installed — run: pip install librosa audioread --break-system-packages"}

    preview_urls = get_preview_urls(albums, sp)

    if not preview_urls:
        return {"debug": "No preview URLs found. Spotify has deprecated preview_url for most tracks (common in 2024+). Use the manual fields to enter values."}

    log = [f"Found {len(preview_urls)} preview URL(s). Analyzing..."]

    results = []
    for i, url in enumerate(preview_urls):
        clip_data = analyze_clip(url)
        if clip_data:
            results.append(clip_data)
            log.append(f"  Clip {i+1}: BPM={clip_data['tempo']:.0f}, RMS={clip_data['rms']:.4f}, Centroid={clip_data['centroid']:.0f}Hz ✓")
        else:
            log.append(f"  Clip {i+1}: failed to load (likely needs ffmpeg for MP3 decoding on Windows)")

    if not results:
        log.append("All clips failed. Fix: install ffmpeg and add it to PATH, then restart.")
        return {"debug": "\n".join(log)}

    avg_tempo    = round(sum(r["tempo"]    for r in results) / len(results))
    avg_rms      = sum(r["rms"]       for r in results) / len(results)
    avg_centroid = sum(r["centroid"]  for r in results) / len(results)
    avg_sr       = results[0]["sr"]

    energy_label  = map_energy(avg_rms)
    valence_label = map_mood(avg_centroid, avg_sr)

    log.append(f"Result: BPM={avg_tempo}, Energy={energy_label}, Mood={valence_label}")

    return {
        "avg_bpm":       avg_tempo,
        "energy_label":  energy_label,
        "valence_label": valence_label,
        "debug":         "\n".join(log),
    }
