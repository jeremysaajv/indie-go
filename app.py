import os
import re
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

import streamlit as st
import streamlit.components.v1 as components

# Streamlit Cloud stores secrets in st.secrets — push them into os.environ
# so the rest of the app (auth.py, harvester.py etc.) can use os.getenv() uniformly.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k, _v)
except Exception:
    pass

from auth import get_auth_url, exchange_code_for_token, get_current_user, check_authorization
from harvester import get_full_artist_data
from synthesizer import generate_bio
from exporter import generate_epk_pdf
from researcher import research_artist, parse_social_stats
from config import ARTIST_PROFILES

# ─── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Indie-Go",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    html, body, [class*="css"] { background-color: #121212; color: #FFFFFF; }
    .stApp { background-color: #121212; }
    h1, h2, h3 { color: #1DB954; }
    .stButton > button {
        background-color: #1DB954 !important;
        color: #000 !important;
        font-weight: 700;
        border-radius: 50px;
        border: none;
    }
    .stButton > button:hover { background-color: #1ed760 !important; }
    .stLinkButton > a {
        background-color: #1DB954 !important;
        color: #000 !important;
        font-weight: 700;
        border-radius: 50px;
    }
    .stTextInput input, .stTextArea textarea {
        background-color: #282828 !important;
        color: #FFF !important;
        border: 1px solid #1DB954 !important;
    }
    .stSelectbox div[data-baseweb="select"] { background-color: #282828 !important; }
    .divider { border-top: 1px solid #333; margin: 16px 0; }
    .role-badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .badge-dev { background: #7c3aed; color: #fff; }
    .badge-artist { background: #1DB954; color: #000; }
    .badge-public { background: #555; color: #fff; }
</style>
""", unsafe_allow_html=True)


# ─── URI parser ───────────────────────────────────────────────────────────────

def parse_artist_id(raw):
    raw = raw.strip()
    m = re.match(r"spotify:artist:([A-Za-z0-9]+)", raw)
    if m: return m.group(1)
    m = re.search(r"open\.spotify\.com/artist/([A-Za-z0-9]+)", raw)
    if m: return m.group(1)
    if re.match(r"^[A-Za-z0-9]{22}$", raw): return raw
    return None


# ─── Session state ────────────────────────────────────────────────────────────

def init_session():
    defaults = {
        "authenticated": False,
        "token_info": None,
        "user_profile": None,
        "user_role": None,
        "editor_artist_id": None,
        "editor_artist_data": None,
        "generated_bio": None,
        "bio_finalized": False,
        "epk_settings":     None,
        "artist_research":          None,
        "research_debug":           None,
        "social_stats":             None,
        "merch_url":                "",
        "show_finalized_toast":     False,
        "manual_instagram": "",
        "manual_youtube":   "",
        "contact_email":    "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─── OAuth callback ───────────────────────────────────────────────────────────

def handle_oauth_callback():
    params = st.query_params
    if "code" in params and not st.session_state.authenticated:
        token_info = exchange_code_for_token(params["code"])
        if token_info:
            profile = get_current_user(token_info["access_token"])
            if profile:
                role = check_authorization(profile["id"])
                st.session_state.token_info    = token_info
                st.session_state.user_profile  = profile
                st.session_state.authenticated = True
                st.session_state.user_role     = role
        st.query_params.clear()
        st.rerun()


# ─── Default EPK settings ─────────────────────────────────────────────────────

def default_settings(artist_data=None):
    d = artist_data or {}
    # Infer Energy, Mood, BPM from genres immediately — genres come from
    # Spotify on first load so these are available before research runs.
    # _suggest_momentum_matrix is defined later in the file; Python resolves
    # function names at call time, not definition time, so this is safe.
    genres = d.get("genres", [])
    sugg_energy, sugg_mood, sugg_bpm = _suggest_momentum_matrix(genres)

    raw_bpm    = d.get("avg_bpm")
    raw_energy = d.get("energy_label")
    raw_mood   = d.get("valence_label")

    return {
        "template":         "Prestige",
        "primary_color":    "#1DB954",
        "bg_color":         "#121212",
        "font_size":        10,
        "show_momentum":    True,
        "show_discography": True,
        "show_bio":         True,
        # Use live Spotify audio data if present, else fall back to genre inference
        "momentum_text":    str(d.get("momentum_proxy") or "N/A"),
        "bpm_text":         str(raw_bpm)    if raw_bpm    else (sugg_bpm    or "N/A"),
        "energy_text":      str(raw_energy) if raw_energy else (sugg_energy or "N/A"),
        "mood_text":        str(raw_mood)   if raw_mood   else (sugg_mood   or "N/A"),
    }


# ─── Genre-based Momentum Matrix inference ────────────────────────────────────

def _suggest_momentum_matrix(genres, research_items=None):
    """
    Infer Energy Profile, Sonic Mood, and typical BPM from Spotify genre tags.
    Also attempts to extract BPM from research text if available.
    Returns (energy_str, mood_str, bpm_str). Any may be None if no match found.
    """
    g = " ".join(genres).lower() if genres else ""

    # ── BPM by genre ─────────────────────────────────────────────────────────
    bpm_rules = [
        (["drum and bass", "dnb"],                                 "174 BPM"),
        (["techno", "hardstyle"],                                  "140 BPM"),
        (["edm", "house", "electro", "trance", "dance"],          "128 BPM"),
        (["dubstep"],                                              "140 BPM"),
        (["metal", "hardcore", "thrash", "punk"],                  "160 BPM"),
        (["hard rock"],                                            "130 BPM"),
        (["rock", "grunge", "alternative", "indie rock"],         "120 BPM"),
        (["hip-hop", "hip hop", "rap", "grime"],                  "90 BPM"),
        (["trap", "drill"],                                        "75 BPM"),
        (["pop", "k-pop", "j-pop", "synthpop", "teen pop"],       "115 BPM"),
        (["funk", "disco"],                                        "108 BPM"),
        (["r&b", "rnb", "neo soul"],                              "85 BPM"),
        (["soul"],                                                 "90 BPM"),
        (["reggae", "dancehall"],                                  "90 BPM"),
        (["ska"],                                                  "160 BPM"),
        (["jazz", "swing", "bebop", "big band"],                  "120 BPM"),
        (["blues"],                                                "80 BPM"),
        (["country", "bluegrass"],                                 "105 BPM"),
        (["folk", "acoustic", "singer-songwriter"],               "95 BPM"),
        (["indie", "indie pop", "chillwave"],                     "110 BPM"),
        (["lo-fi", "lofi"],                                        "80 BPM"),
        (["classical", "orchestral", "chamber"],                  "108 BPM"),
        (["ambient", "new age", "meditation", "sleep"],           "70 BPM"),
        (["chill"],                                                "85 BPM"),
        (["bollywood", "filmi", "kollywood", "tollywood"],        "120 BPM"),
        (["carnatic", "hindustani", "classical indian"],          "100 BPM"),
        (["malayalam", "tamil", "hindi", "telugu", "kannada",
          "indian"],                                              "108 BPM"),
        (["devotional", "gospel", "worship", "spiritual"],       "80 BPM"),
    ]

    # ── Energy by genre ───────────────────────────────────────────────────────
    energy_rules = [
        (["metal", "hardcore", "punk", "thrash", "death metal"],  "High — Aggressive"),
        (["edm", "techno", "drum and bass", "dubstep", "house",
          "electro", "dance"],                                     "High — Electric"),
        (["hip-hop", "hip hop", "rap", "trap", "grime", "drill"], "High — Driving"),
        (["hard rock"],                                            "High — Driving"),
        (["rock", "alternative", "grunge", "indie rock"],         "Medium-High — Driving"),
        (["pop", "k-pop", "j-pop", "synthpop", "teen pop"],       "Medium — Polished"),
        (["funk", "disco", "r&b", "rnb", "soul", "neo soul"],     "Medium — Groove-Driven"),
        (["reggae", "dancehall", "ska"],                           "Medium — Relaxed"),
        (["indie", "indie pop", "lo-fi", "lofi", "chillwave"],   "Medium — Laid-Back"),
        (["jazz", "swing", "bebop", "big band"],                  "Low-Medium — Dynamic"),
        (["blues", "country", "folk", "acoustic",
          "singer-songwriter"],                                    "Low-Medium — Organic"),
        (["classical", "orchestral", "chamber"],                   "Low — Refined"),
        (["ambient", "new age", "meditation", "chill", "sleep"],  "Low — Serene"),
        (["bollywood", "filmi", "kollywood", "tollywood",
          "malayalam", "tamil", "hindi", "telugu", "kannada",
          "carnatic", "indian"],                                   "Medium — Melodic"),
        (["devotional", "gospel", "worship", "spiritual"],        "Low-Medium — Reverent"),
    ]

    # ── Mood by genre ─────────────────────────────────────────────────────────
    mood_rules = [
        (["metal", "hardcore", "punk", "thrash"],                 "Intense"),
        (["edm", "techno", "house", "dance", "electro", "trance"],"Euphoric"),
        (["hip-hop", "hip hop", "rap", "trap", "drill", "grime"], "Confident"),
        (["rock", "grunge", "alternative", "hard rock"],          "Energetic"),
        (["pop", "k-pop", "j-pop", "teen pop"],                   "Upbeat"),
        (["funk", "disco"],                                        "Groovy"),
        (["r&b", "rnb", "neo soul"],                              "Emotive"),
        (["soul", "blues"],                                        "Soulful"),
        (["reggae", "dancehall", "ska"],                          "Relaxed"),
        (["jazz", "swing", "bebop", "big band"],                  "Sophisticated"),
        (["folk", "acoustic", "singer-songwriter", "country"],    "Intimate"),
        (["indie", "indie pop", "lo-fi", "lofi", "chillwave"],   "Reflective"),
        (["classical", "orchestral", "chamber"],                  "Serene"),
        (["ambient", "new age", "meditation", "chill", "sleep"],  "Atmospheric"),
        (["bollywood", "filmi", "kollywood", "tollywood",
          "malayalam", "tamil", "hindi", "telugu", "kannada",
          "carnatic", "indian"],                                   "Soulful"),
        (["devotional", "gospel", "worship", "spiritual"],        "Spiritual"),
    ]

    def match(rules):
        if g:
            for keywords, val in rules:
                if any(k in g for k in keywords):
                    return val
        return None

    energy = match(energy_rules) or "Medium — Varied"
    mood   = match(mood_rules)   or "Eclectic"
    bpm    = match(bpm_rules)    or "100 BPM"

    # ── Try to extract BPM from research text ─────────────────────────────────
    if not bpm and research_items:
        import re as _re
        bpm_pat = _re.compile(r'\b(\d{2,3})\s*(?:bpm|beats per minute)\b', _re.I)
        for item in research_items:
            text = (item.get("snippet","") or "") + " " + (item.get("full_text","") or "")
            m = bpm_pat.search(text)
            if m:
                bpm = f"{m.group(1)} BPM"
                break

    return energy, mood, bpm


# Keep old 2-return signature as alias for any callers that haven't been updated
def _suggest_energy_mood(genres):
    e, m, _ = _suggest_momentum_matrix(genres)
    return e, m


# ─── Finalized EPK persistence ───────────────────────────────────────────────

EPK_DATA_DIR = Path(__file__).parent / "epk_data"

def save_finalized_epk(artist_id, artist_data, bio, social_stats, settings, persona):
    """Persist finalized EPK to disk as JSON, keyed by artist_id."""
    EPK_DATA_DIR.mkdir(exist_ok=True)
    payload = {
        "artist_data":  artist_data,
        "staccato_bio": bio.get("staccato", ""),
        "legacy_bio":   bio.get("legacy", ""),
        "social_stats": social_stats or {},
        "settings":     settings,
        "persona":      persona,
        "finalized_at": datetime.now().isoformat(),
    }
    (EPK_DATA_DIR / f"{artist_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_finalized_epk(artist_id):
    """Load finalized EPK JSON for an artist. Returns dict or None."""
    path = EPK_DATA_DIR / f"{artist_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


# ─── HTML Preview ─────────────────────────────────────────────────────────────

def build_html_preview(artist_data, bio, settings, social_stats=None):
    """Generates a styled HTML preview approximating the chosen PDF template."""
    template = settings["template"]
    primary  = settings["primary_color"]
    bg       = settings["bg_color"]
    fs       = settings["font_size"]
    name     = artist_data.get("name", "Artist")
    genres   = ", ".join(artist_data.get("genres", [])) or "Independent Artist"
    explicit = artist_data.get("has_explicit", False)
    momentum = settings.get("momentum_text") or artist_data.get("momentum_proxy", "N/A")
    bpm      = settings.get("bpm_text") or str(artist_data.get("avg_bpm") or "N/A")
    energy   = settings.get("energy_text") or artist_data.get("energy_label", "N/A")
    mood     = settings.get("mood_text") or artist_data.get("valence_label", "N/A")
    img_url  = artist_data.get("image_url", "")
    staccato = bio.get("staccato", "") if bio else ""
    legacy   = bio.get("legacy", "") if bio else ""
    albums   = artist_data.get("albums", [])
    ss       = social_stats or {}

    # Template-specific styles
    if template == "Prestige":
        text_color   = "#FFFFFF"
        section_bg   = "#282828"
        header_bg    = "#000000"
        accent       = primary
        font_family  = "Arial, sans-serif"
        img_position = "right"
    elif template == "Editorial":
        text_color   = "#FFFFFF"
        section_bg   = "#1a1a2e"
        header_bg    = "#0f0f23"
        accent       = primary
        font_family  = "Georgia, serif"
        img_position = "background"
    else:  # Minimal
        text_color   = "#1a1a1a"
        bg           = "#f8f8f8"
        section_bg   = "#eeeeee"
        header_bg    = "#ffffff"
        accent       = primary
        font_family  = "Arial, sans-serif"
        img_position = "left"

    # Build staccato bullets
    bullet_html = ""
    for line in staccato.split("\n"):
        line = line.strip().lstrip("•-*– ").strip()
        if line:
            bullet_html += f'<li style="margin-bottom:6px;">{line}</li>'

    # Build discography rows
    disco_html = ""
    for a in albums[:6]:
        disco_html += f"""
        <tr>
            <td style="padding:4px 8px; color:{text_color}; font-size:{fs}px;">{a.get('name','')}</td>
            <td style="padding:4px 8px; color:#888; font-size:{fs}px;">{a.get('release_date','')[:7]}</td>
            <td style="padding:4px 8px; color:{accent}; font-size:{fs}px;">{a.get('album_type','').upper()}</td>
        </tr>"""

    # Legacy bio paragraphs
    bio_html = ""
    for para in legacy.split("\n\n"):
        if para.strip():
            bio_html += f'<p style="margin-bottom:12px; font-size:{fs+1}px; line-height:1.7; color:{text_color};">{para.strip()}</p>'

    # Image block
    if img_position == "background" and img_url:
        header_style = f"""background-image: linear-gradient(rgba(0,0,0,0.65), rgba(0,0,0,0.65)), url('{img_url}');
                          background-size: cover; background-position: center;"""
        img_block = ""
        name_style = f"font-size:{fs+22}px;"
    elif img_position == "right" and img_url:
        header_style = f"background:{header_bg};"
        img_block = f'<img src="{img_url}" style="width:180px; height:180px; object-fit:cover; border-radius:4px; float:right; margin-left:20px;">'
        name_style = f"font-size:{fs+18}px;"
    else:
        header_style = f"background:{header_bg};"
        img_block = f'<img src="{img_url}" style="width:120px; height:120px; object-fit:cover; border-radius:4px; margin-right:20px; float:left;">' if img_url else ""
        name_style = f"font-size:{fs+18}px;"

    html = f"""
    <div style="background:{bg}; font-family:{font_family}; padding:0; max-width:700px; margin:0 auto; border:1px solid #333;">

        <!-- HEADER -->
        <div style="{header_style} padding:24px 28px; overflow:hidden; min-height:140px;">
            {img_block}
            <h1 style="{name_style} color:{accent}; margin:0 0 6px 0; font-weight:900;">{name}</h1>
            <p style="color:#aaa; margin:0 0 4px 0; font-size:{fs}px;">{genres}</p>
            <span style="color:{accent}; font-size:{fs-1}px; font-weight:700;">✓ Verified by Indie-Go | Spotify API | 2026</span><br>
            <span style="color:{'#dc3545' if explicit else accent}; font-size:{fs-1}px; font-weight:700;">
                {'[E] Explicit Content' if explicit else '[CLEAN] Non-Explicit'}
            </span>
        </div>

        <!-- CONNECT -->
        <div style="padding:8px 28px 4px;">
            <div style="background:{accent}; padding:4px 8px; margin-bottom:8px;">
                <span style="font-weight:700; font-size:{fs}px; color:#000;">CONNECT</span>
            </div>
            <table style="width:100%; border-collapse:collapse;">
                <tr>
                    <td style="padding:3px 8px; font-weight:700; color:{accent}; font-size:{fs}px; width:90px;">SPOTIFY</td>
                    <td style="padding:3px 8px; font-size:{fs}px;">
                        <a href="https://open.spotify.com/artist/{artist_data.get('artist_id','')}" target="_blank"
                           style="color:{accent}; text-decoration:underline;">Open Spotify Profile</a>
                    </td>
                </tr>
                {f'''<tr>
                    <td style="padding:3px 8px; font-weight:700; color:{accent}; font-size:{fs}px;">INSTAGRAM</td>
                    <td style="padding:3px 8px; font-size:{fs}px;">
                        <a href="{ss["instagram_url"]}" target="_blank" style="color:{accent}; text-decoration:underline;">Instagram</a>
                    </td>
                </tr>''' if ss.get("instagram_url") else ''}
                {f'''<tr>
                    <td style="padding:3px 8px; font-weight:700; color:{accent}; font-size:{fs}px;">YOUTUBE</td>
                    <td style="padding:3px 8px; font-size:{fs}px;">
                        <a href="{ss["youtube_url"]}" target="_blank" style="color:{accent}; text-decoration:underline;">YouTube Channel</a>
                    </td>
                </tr>''' if ss.get("youtube_url") else ''}
                {f'''<tr>
                    <td style="padding:3px 8px; font-weight:700; color:{accent}; font-size:{fs}px;">MERCH</td>
                    <td style="padding:3px 8px; font-size:{fs}px;">
                        <a href="{ss["merch_url"]}" target="_blank" style="color:{accent}; text-decoration:underline;">Visit Merch Store</a>
                    </td>
                </tr>''' if ss.get("merch_url") else ''}
                {f'''<tr>
                    <td style="padding:3px 8px; font-weight:700; color:{accent}; font-size:{fs}px;">EMAIL</td>
                    <td style="padding:3px 8px; font-size:{fs}px;">
                        <a href="mailto:{ss["contact_email"]}" style="color:{accent}; text-decoration:underline;">{ss["contact_email"]}</a>
                    </td>
                </tr>''' if ss.get("contact_email") else ''}
            </table>
        </div>

        <!-- MOMENTUM MATRIX -->
        {'<div style="padding:8px 28px;">' if settings['show_momentum'] else '<!--'}
        <div style="background:{accent}; padding:4px 8px; margin-bottom:8px;">
            <span style="font-weight:700; font-size:{fs}px; color:#000;">MOMENTUM MATRIX</span>
        </div>
        <table style="width:100%; border-collapse:separate; border-spacing:4px; margin-bottom:12px;">
            <tr>
                {''.join(f'''<td style="background:{section_bg}; padding:10px; width:25%; border-radius:4px;">
                    <div style="font-size:{fs-3}px; color:#888; font-weight:700; margin-bottom:4px;">{label}</div>
                    <div style="font-size:{fs+1}px; color:{text_color}; font-weight:700;">{val}</div>
                </td>''' for label, val in [
                    ("RELEASE MOMENTUM", momentum),
                    ("AVG TEMPO", f"{bpm} BPM"),
                    ("ENERGY", energy),
                    ("SONIC MOOD", mood),
                ])}
            </tr>
        </table>
        {'</div>' if settings['show_momentum'] else '-->'}

        <!-- DISCOGRAPHY -->
        {'<div style="padding:0 28px 12px;">' if settings['show_discography'] and albums else '<!--'}
        <div style="background:{accent}; padding:4px 8px; margin-bottom:8px;">
            <span style="font-weight:700; font-size:{fs}px; color:#000;">DISCOGRAPHY</span>
        </div>
        <table style="width:100%; border-collapse:collapse;">
            {disco_html}
        </table>
        {'</div>' if settings['show_discography'] and albums else '-->'}

        <!-- NARRATIVE -->
        {'<div style="padding:0 28px 20px;">' if settings['show_bio'] else '<!--'}
        <div style="background:{accent}; padding:4px 8px; margin-bottom:12px;">
            <span style="font-weight:700; font-size:{fs}px; color:#000;">ARTIST NARRATIVE</span>
        </div>
        {f'''<p style="font-weight:700; color:{accent}; font-size:{fs}px; margin-bottom:6px;">KEY HIGHLIGHTS</p>
        <ul style="margin:0 0 16px 16px; padding:0; color:{text_color};">{bullet_html}</ul>''' if bullet_html else ''}
        {f'<p style="font-weight:700; color:{accent}; font-size:{fs}px; margin-bottom:8px;">FULL BIOGRAPHY</p>{bio_html}' if bio_html else ''}
        {'</div>' if settings['show_bio'] else '-->'}

        <!-- FOOTER -->
        <div style="padding:8px 28px; border-top:1px solid #333;">
            <span style="font-size:{fs-2}px; color:#666;">
                spotify.com/artist/{artist_data.get('artist_id','')} | Indie-Go Verified EPK
            </span>
        </div>
    </div>
    """
    return html


# ─── EPK Editor ───────────────────────────────────────────────────────────────

def render_epk_editor(artist_data, persona, access_level):
    """
    Main editor view. Left panel = controls. Right panel = live HTML preview.
    access_level: "developer" | "artist"
    """
    if st.session_state.epk_settings is None:
        st.session_state.epk_settings = default_settings(artist_data)
        s = st.session_state.epk_settings
        # Must set widget keys here — without this, text_input with no value=
        # parameter defaults to "" and immediately overwrites the settings dict.
        st.session_state["inp_momentum"] = s["momentum_text"]
        st.session_state["inp_bpm"]      = s["bpm_text"]
        st.session_state["inp_energy"]   = s["energy_text"]
        st.session_state["inp_mood"]     = s["mood_text"]

    settings = st.session_state.epk_settings

    if st.session_state.get("show_finalized_toast"):
        st.toast("EPK has been updated and finalized!", icon="✅")
        st.session_state.show_finalized_toast = False

    badge = "badge-dev" if access_level == "developer" else "badge-artist"
    label = "DEVELOPER" if access_level == "developer" else "ARTIST"
    st.markdown(f'<span class="role-badge {badge}">{label} MODE</span>', unsafe_allow_html=True)
    st.markdown(f"### Editing: **{artist_data['name']}**")
    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    left, right = st.columns([1, 2], gap="large")

    # ── LEFT PANEL: Controls ──────────────────────────────────────────────────
    with left:
        st.subheader("🎨 Template")
        template = st.radio(
            "Choose template",
            ["Prestige", "Editorial", "Minimal"],
            index=["Prestige", "Editorial", "Minimal"].index(settings["template"]),
            label_visibility="collapsed",
        )
        settings["template"] = template

        st.markdown("**Template descriptions:**")
        descriptions = {
            "Prestige":  "Dark, bold, Spotify-style. Best for club/festival artists.",
            "Editorial": "Magazine look. Image-driven. Best for visual/brand artists.",
            "Minimal":   "Clean and light. Professional. Best for industry submissions.",
        }
        st.caption(descriptions[template])

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("🎨 Colours")
        settings["primary_color"] = st.color_picker("Accent colour", value=settings["primary_color"])

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("🔤 Font Size")
        settings["font_size"] = st.slider("Body font size", min_value=8, max_value=14, value=settings["font_size"])

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("📋 Sections")
        settings["show_momentum"]    = st.checkbox("Momentum Matrix",  value=settings["show_momentum"])
        settings["show_discography"] = st.checkbox("Discography",       value=settings["show_discography"])
        settings["show_bio"]         = st.checkbox("Artist Narrative",  value=settings["show_bio"])

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("📊 Momentum Matrix")
        st.caption("Edit any value that is wrong or missing.")

        # Show audio analysis diagnostic so we know why values may be N/A
        audio_debug = artist_data.get("audio_debug", "")
        if audio_debug:
            with st.expander("🔍 Audio Analysis Log", expanded=False):
                st.code(audio_debug)
        settings["momentum_text"] = st.text_input(
            "Release Momentum", key="inp_momentum"
        )
        settings["bpm_text"] = st.text_input(
            "Avg Tempo", key="inp_bpm", placeholder="e.g. 96 BPM"
        )
        settings["energy_text"] = st.text_input(
            "Energy Profile", key="inp_energy", placeholder="e.g. Driving"
        )
        settings["mood_text"] = st.text_input(
            "Sonic Mood", key="inp_mood", placeholder="e.g. Introspective"
        )

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("🔍 Online Research")
        st.caption("Search the web for press, achievements, articles, and events.")

        if st.button("Search Online for Artist Coverage", use_container_width=True):
            genres    = artist_data.get("genres", [])
            artist_id = artist_data.get("artist_id")
            # Build disambiguation anchors from Spotify data
            albums           = artist_data.get("albums", [])
            known_tracks     = [a["name"] for a in albums[:3] if a.get("name")]
            release_years    = [int(a["release_date"][:4]) for a in albums
                                if a.get("release_date") and a["release_date"][:4].isdigit()]
            first_rel_year   = min(release_years) if release_years else None
            with st.spinner("Searching across Bing, Last.fm, Genius, Bandcamp, MusicBrainz..."):
                items, debug = research_artist(
                    artist_data["name"], genres, artist_id=artist_id,
                    known_tracks=known_tracks, first_release_year=first_rel_year,
                )
            st.session_state.artist_research = items if items else []
            st.session_state.research_debug  = debug
            st.session_state.social_stats    = parse_social_stats(items) if items else {}

            # After research, try to fill BPM from research text if still N/A
            # (Energy & Mood are already filled at settings init time from genres)
            if st.session_state.epk_settings is None:
                st.session_state.epk_settings = default_settings(artist_data)
            s = st.session_state.epk_settings
            if s.get("bpm_text", "N/A") in ("N/A", "", None):
                _, _, sugg_bpm = _suggest_momentum_matrix(
                    artist_data.get("genres", []),
                    research_items=st.session_state.artist_research,
                )
                if sugg_bpm:
                    s["bpm_text"] = sugg_bpm

            st.rerun()

        if st.session_state.research_debug:
            with st.expander("🔎 Research Log", expanded=False):
                st.code(st.session_state.research_debug)

        if st.session_state.artist_research:
            st.success(f"✅ {len(st.session_state.artist_research)} source(s) found.")

            # ── Stats discovered from research ─────────��─────────────────────
            ss = st.session_state.social_stats or {}
            spotify_followers = artist_data.get("spotify_followers")

            has_stats = any([
                spotify_followers,
                ss.get("instagram_followers"),
                ss.get("youtube_subscribers"),
                ss.get("awards"),
                ss.get("instagram_url"),
                ss.get("youtube_url"),
            ])

            if has_stats:
                st.markdown("**📊 Discovered Stats**")
                if spotify_followers:
                    from synthesizer import _fmt_number
                    sf = _fmt_number(spotify_followers)
                    spotify_url = artist_data.get("spotify_url", "")
                    st.markdown(f"🎵 **Spotify Followers:** {sf}  \n[Open Spotify Profile]({spotify_url})")
                if ss.get("instagram_followers") or ss.get("instagram_url"):
                    ig_txt = f"**Instagram Followers:** {ss['instagram_followers']}" if ss.get("instagram_followers") else "Instagram"
                    ig_url = ss.get("instagram_url", "")
                    if ig_url:
                        st.markdown(f"📸 {ig_txt}  \n[Open Instagram]({ig_url})")
                    else:
                        st.markdown(f"📸 {ig_txt}")
                if ss.get("youtube_subscribers") or ss.get("youtube_url"):
                    yt_txt = f"**YouTube Subscribers:** {ss['youtube_subscribers']}" if ss.get("youtube_subscribers") else "YouTube"
                    yt_url = ss.get("youtube_url", "")
                    if yt_url:
                        st.markdown(f"▶️ {yt_txt}  \n[Open YouTube]({yt_url})")
                    else:
                        st.markdown(f"▶️ {yt_txt}")
                if ss.get("awards"):
                    with st.expander(f"🏆 Awards & Achievements ({len(ss['awards'])} found)", expanded=True):
                        for award in ss["awards"]:
                            st.markdown(f"• {award}")

            with st.expander("📰 All Sources", expanded=False):
                for item in st.session_state.artist_research:
                    st.markdown(f"**[{item['domain']}]** [{item['title']}]({item['source']})")
                    st.caption(item.get("snippet", "")[:200])
                    st.divider()

        elif st.session_state.research_debug:
            st.warning("No press sources found. Bio will use Spotify data only.")

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("🔗 Artist Links")
        st.caption("Paste links manually if online search didn't find them.")
        manual_instagram = st.text_input(
            "Instagram URL",
            value=st.session_state.get("manual_instagram", ""),
            placeholder="e.g. https://www.instagram.com/artistname",
            key="inp_manual_instagram",
        )
        st.session_state.manual_instagram = manual_instagram

        manual_youtube = st.text_input(
            "YouTube Channel URL",
            value=st.session_state.get("manual_youtube", ""),
            placeholder="e.g. https://www.youtube.com/@artistname",
            key="inp_manual_youtube",
        )
        st.session_state.manual_youtube = manual_youtube

        contact_email = st.text_input(
            "Contact Email",
            value=st.session_state.get("contact_email", ""),
            placeholder="e.g. artist@email.com",
            key="inp_contact_email",
        )
        st.session_state.contact_email = contact_email

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("🛍️ Merch Link")
        st.caption("Paste the artist's merchandise store URL. This will appear in the CONNECT section of the EPK.")
        merch_url = st.text_input(
            "Merch URL",
            value=st.session_state.get("merch_url", ""),
            placeholder="e.g. https://artist.bandcamp.com/merch",
            label_visibility="collapsed",
            key="inp_merch_url",
        )
        st.session_state.merch_url = merch_url

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        st.subheader("🤖 Bio Generation")
        st.caption(f"Persona: **{persona.upper()}**")

        if st.button("Generate Bio with Claude Sonnet", use_container_width=True):
            with st.spinner("Synthesising..."):
                bios = generate_bio(
                    artist_data, persona,
                    research=st.session_state.artist_research,
                    social_stats=st.session_state.social_stats,
                )
            if bios:
                st.session_state.generated_bio  = bios
                st.session_state.bio_finalized  = False
                st.rerun()
            else:
                st.error("Bio generation failed. Check Anthropic API key.")

        if st.session_state.generated_bio:
            st.markdown("**✏️ Edit Staccato Bio**")
            st.caption("Mobile / quick view")
            new_staccato = st.text_area(
                "staccato", height=150,
                value=st.session_state.generated_bio.get("staccato", ""),
                label_visibility="collapsed",
                key="ta_staccato",
            )
            st.markdown("**✏️ Edit Legacy Bio**")
            st.caption("Full narrative")
            new_legacy = st.text_area(
                "legacy", height=200,
                value=st.session_state.generated_bio.get("legacy", ""),
                label_visibility="collapsed",
                key="ta_legacy",
            )

            if st.button("💾 Finalize & Sign", use_container_width=True, type="primary"):
                st.session_state.generated_bio["staccato"] = new_staccato
                st.session_state.generated_bio["legacy"]   = new_legacy
                artist_data["staccato_bio"] = new_staccato
                artist_data["legacy_bio"]   = new_legacy
                st.session_state.editor_artist_data = artist_data
                st.session_state.bio_finalized = True

                # Build the complete social stats snapshot at finalization time
                final_social = dict(st.session_state.social_stats or {})
                if st.session_state.get("manual_instagram", "").strip():
                    final_social["instagram_url"] = st.session_state.manual_instagram.strip()
                if st.session_state.get("manual_youtube", "").strip():
                    final_social["youtube_url"] = st.session_state.manual_youtube.strip()
                if st.session_state.get("contact_email", "").strip():
                    final_social["contact_email"] = st.session_state.contact_email.strip()
                if st.session_state.get("merch_url", "").strip():
                    final_social["merch_url"] = st.session_state.merch_url.strip()

                save_finalized_epk(
                    artist_data.get("artist_id"),
                    artist_data,
                    st.session_state.generated_bio,
                    final_social,
                    st.session_state.epk_settings,
                    persona,
                )
                st.session_state.show_finalized_toast = True
                st.rerun()

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

        # Export
        if st.session_state.bio_finalized:
            if st.button("📄 Export EPK to PDF", use_container_width=True):
                export_data = st.session_state.editor_artist_data.copy()
                export_data["staccato_bio"]   = st.session_state.generated_bio["staccato"]
                export_data["legacy_bio"]     = st.session_state.generated_bio["legacy"]
                # Apply any manual overrides from the momentum matrix editor
                s = st.session_state.epk_settings
                if s.get("momentum_text"):
                    export_data["momentum_proxy"] = s["momentum_text"]
                if s.get("bpm_text") and s["bpm_text"] != "N/A":
                    bpm_raw = s["bpm_text"].replace(" BPM", "").strip()
                    export_data["avg_bpm"] = bpm_raw if not bpm_raw.isdigit() else int(bpm_raw)
                if s.get("energy_text"):
                    export_data["energy_label"] = s["energy_text"]
                if s.get("mood_text"):
                    export_data["valence_label"] = s["mood_text"]
                with st.spinner("Generating PDF..."):
                    try:
                        social_stats_export = dict(st.session_state.social_stats or {})
                        if st.session_state.get("manual_instagram", "").strip():
                            social_stats_export["instagram_url"] = st.session_state.manual_instagram.strip()
                        if st.session_state.get("manual_youtube", "").strip():
                            social_stats_export["youtube_url"] = st.session_state.manual_youtube.strip()
                        if st.session_state.get("contact_email", "").strip():
                            social_stats_export["contact_email"] = st.session_state.contact_email.strip()
                        if st.session_state.get("merch_url", "").strip():
                            social_stats_export["merch_url"] = st.session_state.merch_url.strip()
                        pdf_bytes = generate_epk_pdf(export_data, persona, settings,
                                                    social_stats=social_stats_export)
                    except Exception as e:
                        import traceback
                        st.error(f"PDF error: {e}")
                        st.code(traceback.format_exc())
                        pdf_bytes = None
                if pdf_bytes:
                    fname = f"{artist_data['name'].replace(' ','_')}_EPK_IndieGo.pdf"
                    st.download_button("⬇️ Download PDF", data=pdf_bytes,
                                       file_name=fname, mime="application/pdf",
                                       use_container_width=True)
        else:
            st.info("Finalize bio to enable PDF export.")

        # Back button
        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
        if st.button("← Change Artist", use_container_width=True):
            st.session_state.editor_artist_id   = None
            st.session_state.editor_artist_data = None
            st.session_state.generated_bio      = None
            st.session_state.bio_finalized      = False
            st.session_state.epk_settings       = None
            st.session_state.artist_research    = None
            st.session_state.research_debug     = None
            st.session_state.social_stats       = None
            st.session_state.manual_instagram   = ""
            st.session_state.manual_youtube     = ""
            st.session_state.contact_email      = ""
            st.session_state.merch_url          = ""
            st.rerun()

    # ── RIGHT PANEL: HTML Preview ─────────────────────────────────────────────
    with right:
        st.subheader("👁️ Live Preview")
        st.caption("Approximation of the final PDF. Click Refresh Preview to update.")

        if st.button("🔄 Refresh Preview", use_container_width=True):
            st.rerun()

        bio = st.session_state.generated_bio or {
            "staccato": artist_data.get("staccato_bio") or "",
            "legacy":   artist_data.get("legacy_bio") or "",
        }

        preview_ss = dict(st.session_state.social_stats or {})
        if st.session_state.get("manual_instagram", "").strip():
            preview_ss["instagram_url"] = st.session_state.manual_instagram.strip()
        if st.session_state.get("manual_youtube", "").strip():
            preview_ss["youtube_url"] = st.session_state.manual_youtube.strip()
        if st.session_state.get("contact_email", "").strip():
            preview_ss["contact_email"] = st.session_state.contact_email.strip()
        if st.session_state.get("merch_url", "").strip():
            preview_ss["merch_url"] = st.session_state.merch_url.strip()
        html_preview = build_html_preview(artist_data, bio, settings, social_stats=preview_ss)
        components.html(html_preview, height=900, scrolling=True)


# ─── Artist URL input screen ──────────────────────────────────────────────────

def render_artist_selector(role_label):
    st.markdown(f"<h2>Welcome back 👋</h2>", unsafe_allow_html=True)
    badge = "badge-dev" if role_label == "developer" else "badge-artist"
    st.markdown(f'<span class="role-badge {badge}">{role_label.upper()}</span>', unsafe_allow_html=True)
    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    st.subheader("Paste Spotify Artist URL")
    st.caption("Enter the artist's Spotify link to load their profile and open the EPK editor.")

    artist_input = st.text_input(
        "Spotify URL", placeholder="https://open.spotify.com/artist/...",
        label_visibility="collapsed",
    )

    if st.button("Open EPK Editor →", use_container_width=True):
        artist_id = parse_artist_id(artist_input)
        if artist_id:
            with st.spinner("Fetching artist data from Spotify..."):
                try:
                    data = get_full_artist_data(artist_id)
                except Exception as e:
                    st.error(f"Spotify API error: {e}")
                    data = None
            if data:
                st.session_state.editor_artist_id   = artist_id
                st.session_state.editor_artist_data = data
                st.session_state.generated_bio      = None
                st.session_state.bio_finalized      = False
                st.session_state.epk_settings       = None
                st.rerun()
            else:
                st.error("Could not fetch artist data. Check the URL.")
        else:
            st.error("Invalid Spotify URL or URI.")

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
    if st.button("Logout"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()


# ─── Landing page ─────────────────────────────────────────────────────────────

_LANDING_BG_JS = """
<script>
(function() {
    // Avoid duplicating if already injected
    if (parent.document.getElementById('ig-bg-canvas')) return;

    // Make stApp background transparent so canvas shows through
    var style = parent.document.createElement('style');
    style.id = 'ig-bg-style';
    style.textContent = '.stApp { background: transparent !important; }';
    parent.document.head.appendChild(style);

    var canvas = parent.document.createElement('canvas');
    canvas.id = 'ig-bg-canvas';
    canvas.style.cssText = [
        'position:fixed', 'top:0', 'left:0',
        'width:100vw', 'height:100vh',
        'z-index:-1', 'pointer-events:none',
        'background:#121212'
    ].join(';');
    parent.document.body.insertBefore(canvas, parent.document.body.firstChild);

    var ctx = canvas.getContext('2d');
    var W, H;

    function resize() {
        W = canvas.width  = parent.window.innerWidth;
        H = canvas.height = parent.window.innerHeight;
    }
    resize();
    parent.window.addEventListener('resize', resize);

    // ── Equalizer bars ────────────────────────────────────────────────────────
    var BAR_COUNT = 80;
    var bars = Array.from({length: BAR_COUNT}, function() {
        return {
            h:      Math.random() * 60 + 10,
            target: Math.random() * 100 + 10,
            speed:  Math.random() * 2.5 + 0.8
        };
    });

    // ── Floating note particles ───────────────────────────────────────────────
    var NOTES  = ['♪', '♫', '♬', '♩'];
    var PARTICLES = 35;
    var parts = [];

    function spawnParticle(startY) {
        return {
            x:    Math.random() * 1400,
            y:    (startY !== undefined) ? startY : Math.random() * 900,
            note: NOTES[Math.floor(Math.random() * NOTES.length)],
            size: Math.random() * 12 + 8,
            vy:   -(Math.random() * 0.5 + 0.2),
            vx:   (Math.random() - 0.5) * 0.3,
            op:   Math.random() * 0.18 + 0.04,
            fade: Math.random() * 0.0008 + 0.0003
        };
    }

    for (var i = 0; i < PARTICLES; i++) parts.push(spawnParticle());

    // ── Waveform sine ─────────────────────────────────────────────────────────
    var waveOffset = 0;

    function draw() {
        ctx.clearRect(0, 0, W, H);

        // Background
        ctx.fillStyle = '#121212';
        ctx.fillRect(0, 0, W, H);

        // Subtle sine wave line across the middle
        ctx.beginPath();
        ctx.strokeStyle = 'rgba(29,185,84,0.06)';
        ctx.lineWidth = 1.5;
        for (var x = 0; x <= W; x += 2) {
            var y = H * 0.5 + Math.sin((x * 0.012) + waveOffset) * 28
                            + Math.sin((x * 0.025) + waveOffset * 1.3) * 12;
            if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        waveOffset += 0.012;

        // Equalizer bars along the bottom
        var bw = W / BAR_COUNT;
        for (var b = 0; b < BAR_COUNT; b++) {
            var bar = bars[b];
            if (Math.abs(bar.h - bar.target) < 3) {
                bar.target = Math.random() * 110 + 8;
                bar.speed  = Math.random() * 2.5 + 0.8;
            }
            bar.h += (bar.h < bar.target) ? bar.speed : -bar.speed;

            var grad = ctx.createLinearGradient(0, H - bar.h, 0, H);
            grad.addColorStop(0, 'rgba(29,185,84,0.45)');
            grad.addColorStop(1, 'rgba(29,185,84,0.03)');
            ctx.fillStyle = grad;
            ctx.fillRect(b * bw, H - bar.h, bw - 1, bar.h);
        }

        // Floating note particles
        ctx.font = '';
        for (var p = 0; p < parts.length; p++) {
            var pt = parts[p];
            pt.x  += pt.vx;
            pt.y  += pt.vy;
            pt.op -= pt.fade;
            if (pt.op <= 0 || pt.y < -20) {
                parts[p] = spawnParticle(H + 10);
                continue;
            }
            ctx.save();
            ctx.globalAlpha = pt.op;
            ctx.fillStyle   = '#1DB954';
            ctx.font        = pt.size + 'px serif';
            ctx.fillText(pt.note, pt.x, pt.y);
            ctx.restore();
        }

        requestAnimationFrame(draw);
    }

    draw();
})();
</script>
"""

def render_landing():
    # Inject animated music background (canvas lives in parent document)
    components.html(_LANDING_BG_JS, height=0, width=0)

    # ── Hero title ────────────────────────────────────────────────────────────
    st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Raleway:wght@300;400;600&display=swap" rel="stylesheet">
    <div style="text-align:center; padding: 52px 0 12px 0;">
        <div style="
            font-family: 'Bebas Neue', sans-serif;
            font-size: 92px;
            letter-spacing: 6px;
            line-height: 1;
        ">
            <span style="color:#E141A9; text-shadow: 0 0 40px rgba(225,65,169,0.5);">INDIE-</span><span style="color:#1DB954; text-shadow: 0 0 40px rgba(29,185,84,0.4);">GO</span>
        </div>
        <div style="
            font-family: 'Raleway', sans-serif;
            font-size: 13px;
            font-weight: 400;
            letter-spacing: 4px;
            color: #888;
            margin-top: 14px;
            text-transform: uppercase;
        ">Go — Build Yourself</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    # ── Three action cards ────────────────────────────────────────────────────
    col_l, col_m, col_r = st.columns(3, gap="medium")

    # ── Card 1: Listener ──────────────────────────────────────────────────────
    with col_l:
        st.markdown("""
        <div style="
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(29,185,84,0.30);
            border-radius: 12px;
            padding: 26px 24px 18px 24px;
            margin-bottom: 8px;
            min-height: 130px;
        ">
            <div style="font-family:'Raleway',sans-serif; font-size:17px; font-weight:600; color:#1DB954; margin-bottom:6px;">👂 I'm a Listener</div>
            <div style="font-family:'Raleway',sans-serif; font-size:12px; color:#888; margin-bottom:0px; letter-spacing:0.5px;">
                View any artist's EPK. Paste their Spotify URL to explore their profile — no account needed.
            </div>
        </div>
        """, unsafe_allow_html=True)
        artist_input = st.text_input("URL", placeholder="https://open.spotify.com/artist/...", label_visibility="collapsed")
        if st.button("View EPK →", use_container_width=True):
            artist_id = parse_artist_id(artist_input)
            if artist_id:
                st.session_state.public_artist_id = artist_id
                st.rerun()
            else:
                st.error("Invalid Spotify URL.")

    # ── Card 2: Artist ────────────────────────────────────────────────────────
    with col_m:
        st.markdown("""
        <div style="
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(225,65,169,0.35);
            border-radius: 12px;
            padding: 26px 24px 18px 24px;
            margin-bottom: 8px;
            min-height: 130px;
        ">
            <div style="font-family:'Raleway',sans-serif; font-size:17px; font-weight:600; color:#E141A9; margin-bottom:6px;">🎤 I'm an Artist</div>
            <div style="font-family:'Raleway',sans-serif; font-size:12px; color:#888; margin-bottom:0px; letter-spacing:0.5px;">
                Log in with your Spotify account to build, customize, and export your own EPK.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.link_button("Login as Artist →", url=get_auth_url(), use_container_width=True)

    # ── Card 3: Developer ─────────────────────────────────────────────────────
    with col_r:
        st.markdown("""
        <div style="
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(124,58,237,0.35);
            border-radius: 12px;
            padding: 26px 24px 18px 24px;
            margin-bottom: 8px;
            min-height: 130px;
        ">
            <div style="font-family:'Raleway',sans-serif; font-size:17px; font-weight:600; color:#7c3aed; margin-bottom:6px;">⚙️ I'm a Developer</div>
            <div style="font-family:'Raleway',sans-serif; font-size:12px; color:#888; margin-bottom:0px; letter-spacing:0.5px;">
                Log in with your authorized Spotify account to generate, edit, and export EPKs for any artist.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.link_button("Login as Developer →", url=get_auth_url(), use_container_width=True)


# ─── Default bio generator (no Claude call — Spotify data only) ──────────────

def generate_default_bio(artist_data):
    """
    Builds a staccato + legacy bio purely from Spotify data.
    Used when no finalized EPK exists, so listeners still see something useful.
    """
    from synthesizer import _fmt_number

    name      = artist_data.get("name", "This artist")
    genres    = artist_data.get("genres", [])
    followers = artist_data.get("spotify_followers", 0)
    albums    = artist_data.get("albums", [])

    genre_str  = ", ".join(genres[:3]) if genres else "independent"
    followers_str = _fmt_number(followers) if followers else None

    # Career span
    years = [
        int(a["release_date"][:4])
        for a in albums
        if a.get("release_date") and a["release_date"][:4].isdigit()
    ]
    first_year = min(years) if years else None
    album_count  = len([a for a in albums if a.get("album_type") == "album"])
    single_count = len([a for a in albums if a.get("album_type") == "single"])
    ep_count     = len([a for a in albums if a.get("album_type") == "ep"])

    # ── Staccato bullets ──────────────────────────────────────────────────────
    bullets = []
    if genres:
        bullets.append(f"Genre: {genre_str.title()}")
    if followers_str:
        bullets.append(f"{followers_str} Spotify followers")
    if first_year:
        bullets.append(f"Active since {first_year}")
    if album_count:
        bullets.append(f"{album_count} album{'s' if album_count > 1 else ''}")
    if ep_count:
        bullets.append(f"{ep_count} EP{'s' if ep_count > 1 else ''}")
    if single_count:
        bullets.append(f"{single_count} single{'s' if single_count > 1 else ''}")
    staccato = "\n".join(f"• {b}" for b in bullets)

    # ── Legacy bio ────────────────────────────────────────────────────────────
    parts = []

    intro = f"{name} is a {genre_str} artist"
    if first_year:
        intro += f" who has been active since {first_year}"
    intro += "."
    parts.append(intro)

    release_line = []
    if album_count:
        release_line.append(f"{album_count} album{'s' if album_count > 1 else ''}")
    if ep_count:
        release_line.append(f"{ep_count} EP{'s' if ep_count > 1 else ''}")
    if single_count:
        release_line.append(f"{single_count} single{'s' if single_count > 1 else ''}")
    if release_line:
        parts.append(
            f"Their discography spans {', '.join(release_line)}, reflecting a consistent "
            f"output across their career."
        )

    if followers_str:
        parts.append(
            f"With {followers_str} followers on Spotify, {name} has built a dedicated "
            f"fanbase through their music."
        )

    if albums:
        recent = albums[0]
        parts.append(
            f"Their most recent release, \"{recent['name']}\" "
            f"({recent.get('release_date', '')[:4]}), continues to showcase their "
            f"artistic evolution."
        )

    legacy = "\n\n".join(parts)
    return {"staccato": staccato, "legacy": legacy}


# ─── Public EPK viewer ────────────────────────────────────────────────────────

def render_public_epk(artist_id):
    if st.button("← Back"):
        st.session_state.public_artist_id = None
        st.rerun()

    # ── Check for a finalized EPK saved by the developer ─────────────────────
    saved = load_finalized_epk(artist_id)

    if saved:
        artist_data  = saved["artist_data"]
        social_stats = saved.get("social_stats", {})
        settings     = saved.get("settings", {})
        persona      = saved.get("persona", "statistician")
        bio = {
            "staccato": saved.get("staccato_bio", ""),
            "legacy":   saved.get("legacy_bio", ""),
        }
        artist_data["staccato_bio"] = bio["staccato"]
        artist_data["legacy_bio"]   = bio["legacy"]

        finalized_date = saved.get("finalized_at", "")[:10]
        st.caption(f"✅ Verified EPK — last finalized {finalized_date}")
        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

        # HTML preview (view-only)
        html_preview = build_html_preview(artist_data, bio, settings, social_stats=social_stats)
        components.html(html_preview, height=950, scrolling=True)

        st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

        # PDF download
        with st.spinner("Preparing PDF..."):
            try:
                pdf_bytes = generate_epk_pdf(
                    artist_data, persona, settings, social_stats=social_stats
                )
            except Exception as e:
                pdf_bytes = None
                st.error(f"PDF error: {e}")

        if pdf_bytes:
            fname = f"{artist_data.get('name','Artist').replace(' ','_')}_EPK_IndieGo.pdf"
            st.download_button(
                "⬇️ Download EPK as PDF",
                data=pdf_bytes,
                file_name=fname,
                mime="application/pdf",
                use_container_width=True,
            )
        return

    # ── No finalized EPK — generate a default view from Spotify data ──────────
    with st.spinner("Fetching artist data..."):
        try:
            data = get_full_artist_data(artist_id)
        except Exception as e:
            st.error(f"Spotify API error: {e}")
            return

    if not data:
        st.error("Could not fetch artist data.")
        return

    st.caption("📋 Auto-generated profile — artist has not yet finalized their EPK")
    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)

    bio      = generate_default_bio(data)
    settings = default_settings(data)
    html_preview = build_html_preview(data, bio, settings)
    components.html(html_preview, height=1400, scrolling=True)


# ─── Router ───────────────────────────────────────────────────────────────────

def main():
    init_session()
    handle_oauth_callback()

    if "public_artist_id" not in st.session_state:
        st.session_state.public_artist_id = None

    role = st.session_state.user_role

    if st.session_state.authenticated and role:

        # Developer or Artist in editor
        if st.session_state.editor_artist_data:
            artist_data = st.session_state.editor_artist_data
            artist_id   = artist_data.get("artist_id")

            # Determine persona
            if artist_id in ARTIST_PROFILES:
                persona = ARTIST_PROFILES[artist_id]["persona"]
            else:
                persona = "statistician"  # Default for unknown artists

            access = role["role"]
            render_epk_editor(artist_data, persona, access)

        # Show artist URL input
        elif role["role"] in ("developer", "artist"):
            # For artists, pre-fill their own artist ID
            if role["role"] == "artist" and not st.session_state.editor_artist_id:
                artist_id = role.get("artist_id")
                if artist_id:
                    with st.spinner("Loading your profile..."):
                        try:
                            data = get_full_artist_data(artist_id)
                        except Exception:
                            data = None
                    if data:
                        st.session_state.editor_artist_data = data
                        st.rerun()
            render_artist_selector(role["role"])

        else:
            # Public user who logged in
            st.title("Indie-Go")
            st.info(f"Welcome, **{st.session_state.user_profile.get('display_name','Guest')}**. You have read-only access.")
            st.caption(f"Your Spotify User ID: `{st.session_state.user_profile.get('id')}`")
            if st.button("Logout"):
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.rerun()

    elif st.session_state.public_artist_id:
        render_public_epk(st.session_state.public_artist_id)

    else:
        render_landing()


if __name__ == "__main__":
    main()
