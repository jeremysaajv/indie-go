import os
import io
import re
import tempfile
import requests
from datetime import datetime
from fpdf import FPDF
from PIL import Image


# ─── Default colour palette (Spotify Dark / Prestige) ────────────────────────
SPOTIFY_GREEN = (29, 185, 84)
WHITE         = (255, 255, 255)
DARK_BG       = (18, 18, 18)
MID_GREY      = (50, 50, 50)
LIGHT_GREY    = (179, 179, 179)
RED           = (220, 50, 50)
PAGE_BG       = (24, 24, 24)

# Editorial palette
EDITORIAL_BG       = (15, 15, 35)
EDITORIAL_CARD     = (26, 26, 60)
EDITORIAL_HEADER   = (10, 10, 25)

# Minimal palette
MINIMAL_BG         = (248, 248, 248)
MINIMAL_CARD       = (238, 238, 238)
MINIMAL_HEADER     = (255, 255, 255)
MINIMAL_TEXT       = (26, 26, 26)
MINIMAL_SUBTEXT    = (100, 100, 100)
MINIMAL_BORDER     = (200, 200, 200)
BLACK              = (0, 0, 0)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _friendly_url(url):
    """Strip protocol/www for display. Caps at 55 chars."""
    display = re.sub(r'^https?://(www\.)?', '', str(url).strip())
    return (display[:52] + '...') if len(display) > 55 else display


def hex_to_rgb(hex_color):
    """Convert #RRGGBB to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    try:
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        return SPOTIFY_GREEN


def download_artist_image(url):
    """Download artist image to a temp JPEG. Returns path or None."""
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            img.save(tmp.name, "JPEG", quality=90)
            return tmp.name
    except Exception as e:
        print(f"[Exporter] Image download error: {e}")
    return None


def safe(text):
    """
    Normalise text for fpdf2's Helvetica (latin-1 only).
    Replaces smart punctuation with plain ASCII equivalents.
    """
    if not text:
        return ""
    t = str(text)
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("—", " - ").replace("–", " - ")
    t = t.replace("…", "...")
    t = t.replace("•", "-")
    # Strip markdown bold/italic markers so they don't print literally
    t = t.replace("**", "").replace("*", "")
    t = re.sub(r'_([^_\n]+)_', r'\1', t)
    return t.encode("latin-1", errors="ignore").decode("latin-1")


# ─── Template: PRESTIGE (dark/Spotify) ───────────────────────────────────────

def build_prestige(pdf, artist_data, persona, accent_rgb, fs, show_momentum, show_discography, show_bio, social_stats=None):
    """Dark, bold, Spotify-style. Image right-aligned for visualist, left otherwise."""

    # Full dark background
    pdf.set_fill_color(*PAGE_BG)
    pdf.rect(0, 0, 210, 297, "F")

    image_path = None
    if artist_data.get("image_url"):
        image_path = download_artist_image(artist_data["image_url"])

    # ── HEADER ────────────────────────────────────────────────────────────────
    header_h = 72
    pdf.set_fill_color(*DARK_BG)
    pdf.rect(0, 0, 210, header_h, "F")

    if persona == "visualist" and image_path:
        img_obj = Image.open(image_path)
        orig_w, orig_h = img_obj.size
        display_w = 100
        display_h = round(display_w * orig_h / orig_w)
        display_h = min(display_h, header_h)
        pdf.image(image_path, x=110, y=0, w=display_w, h=display_h)
        text_x = 10
    elif image_path:
        img_size = header_h - 10
        pdf.image(image_path, x=8, y=5, w=img_size)
        text_x = img_size + 14
    else:
        text_x = 10

    pdf.set_xy(text_x, 14)
    pdf.set_font("Helvetica", "B", 30)
    pdf.set_text_color(*accent_rgb)
    pdf.cell(0, 11, safe(artist_data.get("name", "Unknown Artist")), ln=True)

    genres = safe(", ".join(artist_data.get("genres", []))[:55] or "Independent Artist")
    pdf.set_x(text_x)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*LIGHT_GREY)
    pdf.cell(0, 7, genres, ln=True)

    pdf.set_x(text_x)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*accent_rgb)
    pdf.cell(0, 6, "Verified by Indie-Go  |  Data Source: Spotify API  |  2026", ln=True)

    pdf.set_y(header_h + 6)

    # ── CONNECT ───────────────────────────────────────────────────────────────
    _prestige_section_header(pdf, "CONNECT", accent_rgb)
    ss_connect = social_stats or {}
    connect_links = []
    if artist_data.get("artist_id"):
        connect_links.append(("SPOTIFY", f"https://open.spotify.com/artist/{artist_data['artist_id']}"))
    if ss_connect.get("instagram_url"):
        connect_links.append(("INSTAGRAM", ss_connect["instagram_url"][:72]))
    if ss_connect.get("youtube_url"):
        connect_links.append(("YOUTUBE", ss_connect["youtube_url"][:72]))
    if ss_connect.get("merch_url"):
        connect_links.append(("MERCH", ss_connect["merch_url"][:72]))
    if ss_connect.get("contact_email"):
        connect_links.append(("EMAIL", ss_connect["contact_email"][:72]))
    for platform, url in connect_links:
        pdf.set_x(14)
        pdf.set_font("Helvetica", "B", fs)
        pdf.set_text_color(*accent_rgb)
        pdf.cell(28, 6, platform)
        pdf.set_font("Helvetica", "", fs)
        pdf.set_text_color(*WHITE)
        if platform == "EMAIL":
            pdf.cell(0, 6, safe(url), link=f"mailto:{url}", ln=True)
        else:
            pdf.cell(0, 6, safe(_friendly_url(url)), link=url, ln=True)
    pdf.ln(3)

    # ── MOMENTUM MATRIX ───────────────────────────────────────────────────────
    if show_momentum:
        _prestige_section_header(pdf, "MOMENTUM MATRIX", accent_rgb)
        metrics = [
            ("RELEASE MOMENTUM", str(artist_data.get("momentum_proxy", "N/A"))),
            ("AVG TEMPO",        f"{artist_data.get('avg_bpm') or 'N/A'} BPM"),
            ("ENERGY PROFILE",   str(artist_data.get("energy_label", "N/A"))),
            ("SONIC MOOD",       str(artist_data.get("valence_label", "N/A"))),
        ]
        _prestige_metric_grid(pdf, metrics, accent_rgb, fs)

    # ── DISCOGRAPHY ───────────────────────────────────────────────────────────
    albums = artist_data.get("albums", [])
    if show_discography and albums:
        _prestige_section_header(pdf, "DISCOGRAPHY", accent_rgb)
        for album in albums[:6]:
            pdf.set_x(14)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*WHITE)
            pdf.cell(100, 6, safe(album.get("name", "Unknown")[:40]))
            pdf.set_font("Helvetica", "", fs)
            pdf.set_text_color(*LIGHT_GREY)
            pdf.cell(40, 6, safe(album.get("release_date", "")[:7]))
            pdf.set_text_color(*accent_rgb)
            pdf.cell(40, 6, safe(album.get("album_type", "").upper()), ln=True)
        pdf.ln(4)

    # ── ARTIST NARRATIVE ──────────────────────────────────────────────────────
    if show_bio:
        _prestige_section_header(pdf, "ARTIST NARRATIVE", accent_rgb)
        staccato = artist_data.get("staccato_bio") or ""
        legacy   = artist_data.get("legacy_bio") or ""

        if staccato:
            pdf.set_x(14)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(0, 6, "KEY HIGHLIGHTS", ln=True)
            pdf.ln(1)
            lines = [l.strip().lstrip("•-*- ").strip() for l in staccato.split("\n") if l.strip().lstrip("•-*- ").strip()]
            for line in lines:
                pdf.set_x(14)
                pdf.set_font("Helvetica", "", fs)
                pdf.set_text_color(*accent_rgb)
                pdf.cell(6, 6, "-")
                pdf.set_text_color(*WHITE)
                if len(line) <= 90:
                    pdf.cell(0, 6, safe(line), ln=True)
                else:
                    pdf.multi_cell(174, 6, safe(line))
            pdf.ln(5)

        if legacy:
            pdf.set_x(14)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(0, 6, "FULL BIOGRAPHY", ln=True)
            pdf.ln(2)
            paragraphs = [p.strip() for p in legacy.split("\n\n") if p.strip()]
            if persona != "storyteller":
                paragraphs = paragraphs[:2]
            for para in paragraphs:
                pdf.set_x(14)
                pdf.set_font("Helvetica", "", fs)
                pdf.set_text_color(*WHITE)
                pdf.multi_cell(182, 6, safe(para))
                pdf.ln(3)

    # ── STATS, AWARDS & LINKS ─────────────────────────────────────────────────
    pdf.ln(4)
    _render_stats_and_links(pdf, artist_data, social_stats, accent_rgb, fs,
                             text_color=WHITE, section_bg=MID_GREY, label_color=LIGHT_GREY)

    if image_path and os.path.exists(image_path):
        try:
            os.unlink(image_path)
        except Exception:
            pass


def _prestige_section_header(pdf, title, accent_rgb):
    y = pdf.get_y()
    pdf.set_fill_color(*MID_GREY)
    pdf.rect(10, y, 190, 8, "F")
    pdf.set_fill_color(*accent_rgb)
    pdf.rect(10, y, 3, 8, "F")
    pdf.set_xy(16, y + 1)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*accent_rgb)
    pdf.cell(180, 6, title, ln=True)
    pdf.ln(3)


def _prestige_metric_grid(pdf, metrics, accent_rgb, fs):
    box_w, box_h, gap = 44, 24, 3
    x0 = 11
    y0 = pdf.get_y()
    for i, (label, value) in enumerate(metrics):
        x = x0 + i * (box_w + gap)
        pdf.set_fill_color(*MID_GREY)
        pdf.rect(x, y0, box_w, box_h, "F")
        pdf.set_xy(x + 3, y0 + 3)
        pdf.set_font("Helvetica", "B", 6)
        pdf.set_text_color(*LIGHT_GREY)
        pdf.cell(box_w - 6, 4, safe(label))
        pdf.set_xy(x + 3, y0 + 9)
        pdf.set_font("Helvetica", "B", fs - 1)
        pdf.set_text_color(*WHITE)
        v = safe(value) if len(safe(value)) <= 26 else safe(value)[:23] + "..."
        pdf.multi_cell(box_w - 6, 5, v)
    pdf.set_y(y0 + box_h + 5)


# ─── Template: EDITORIAL (magazine) ──────────────────────────────────────────

def build_editorial(pdf, artist_data, persona, accent_rgb, fs, show_momentum, show_discography, show_bio, social_stats=None):
    """Magazine-style. Full-width image banner at top with name overlaid. Georgia-style with structured columns."""

    pdf.set_fill_color(*EDITORIAL_BG)
    pdf.rect(0, 0, 210, 297, "F")

    image_path = None
    if artist_data.get("image_url"):
        image_path = download_artist_image(artist_data["image_url"])

    # ── FULL-WIDTH BANNER ─────────────────────────────────────────────────────
    banner_h = 80
    if image_path:
        # Stretch image across full width as banner (intentional for editorial)
        pdf.image(image_path, x=0, y=0, w=210, h=banner_h)
        # Dark gradient overlay via semi-transparent rect (simulate with dark fill at bottom)
        pdf.set_fill_color(0, 0, 0)
        pdf.rect(0, banner_h - 36, 210, 36, "F")
    else:
        pdf.set_fill_color(*EDITORIAL_HEADER)
        pdf.rect(0, 0, 210, banner_h, "F")

    # Artist name over banner
    pdf.set_xy(12, banner_h - 30)
    pdf.set_font("Helvetica", "B", 34)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 12, safe(artist_data.get("name", "Unknown Artist")), ln=True)

    pdf.set_x(12)
    pdf.set_font("Helvetica", "I", 11)
    pdf.set_text_color(*accent_rgb)
    genres = safe(", ".join(artist_data.get("genres", []))[:60] or "Independent Artist")
    pdf.cell(0, 6, genres, ln=True)

    # Issue line (editorial touch)
    pdf.set_y(banner_h + 4)
    pdf.set_fill_color(*accent_rgb)
    pdf.rect(0, pdf.get_y(), 210, 7, "F")
    pdf.set_x(12)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*BLACK)
    pdf.cell(0, 7, f"INDIE-GO EPK  |  VERIFIED  |  {datetime.now().strftime('%B %Y').upper()}", ln=True)
    pdf.ln(5)

    # ── CONNECT ───────────────────────────────────────────────────────────────
    _editorial_section_header(pdf, "CONNECT", accent_rgb)
    ss_connect = social_stats or {}
    connect_links = []
    if artist_data.get("artist_id"):
        connect_links.append(("SPOTIFY", f"https://open.spotify.com/artist/{artist_data['artist_id']}"))
    if ss_connect.get("instagram_url"):
        connect_links.append(("INSTAGRAM", ss_connect["instagram_url"][:72]))
    if ss_connect.get("youtube_url"):
        connect_links.append(("YOUTUBE", ss_connect["youtube_url"][:72]))
    if ss_connect.get("merch_url"):
        connect_links.append(("MERCH", ss_connect["merch_url"][:72]))
    if ss_connect.get("contact_email"):
        connect_links.append(("EMAIL", ss_connect["contact_email"][:72]))
    for platform, url in connect_links:
        pdf.set_x(12)
        pdf.set_font("Helvetica", "B", fs)
        pdf.set_text_color(*accent_rgb)
        pdf.cell(28, 6, platform)
        pdf.set_font("Helvetica", "", fs)
        pdf.set_text_color(*WHITE)
        pdf.cell(0, 6, safe(url), ln=True)
    pdf.ln(3)

    # ── MOMENTUM MATRIX ───────────────────────────────────────────────────────
    if show_momentum:
        _editorial_section_header(pdf, "MOMENTUM MATRIX", accent_rgb)
        metrics = [
            ("RELEASE MOMENTUM", str(artist_data.get("momentum_proxy", "N/A"))),
            ("AVG TEMPO",        f"{artist_data.get('avg_bpm') or 'N/A'} BPM"),
            ("ENERGY PROFILE",   str(artist_data.get("energy_label", "N/A"))),
            ("SONIC MOOD",       str(artist_data.get("valence_label", "N/A"))),
        ]
        _editorial_metric_grid(pdf, metrics, accent_rgb, fs)

    # ── DISCOGRAPHY ───────────────────────────────────────────────────────────
    albums = artist_data.get("albums", [])
    if show_discography and albums:
        _editorial_section_header(pdf, "DISCOGRAPHY", accent_rgb)
        for album in albums[:6]:
            pdf.set_x(12)
            # Accent dot
            pdf.set_fill_color(*accent_rgb)
            y_dot = pdf.get_y() + 2
            pdf.rect(12, y_dot, 2, 2, "F")
            pdf.set_x(17)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*WHITE)
            pdf.cell(95, 6, safe(album.get("name", "Unknown")[:40]))
            pdf.set_font("Helvetica", "", fs - 1)
            pdf.set_text_color(*LIGHT_GREY)
            pdf.cell(40, 6, safe(album.get("release_date", "")[:7]))
            pdf.set_font("Helvetica", "B", fs - 1)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(40, 6, safe(album.get("album_type", "").upper()), ln=True)
        pdf.ln(4)

    # ── ARTIST NARRATIVE ──────────────────────────────────────────────────────
    if show_bio:
        _editorial_section_header(pdf, "ARTIST NARRATIVE", accent_rgb)
        staccato = artist_data.get("staccato_bio") or ""
        legacy   = artist_data.get("legacy_bio") or ""

        if staccato:
            pdf.set_x(12)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(0, 6, "KEY HIGHLIGHTS", ln=True)
            pdf.ln(1)
            lines = [l.strip().lstrip("•-*- ").strip() for l in staccato.split("\n") if l.strip().lstrip("•-*- ").strip()]
            for line in lines:
                pdf.set_x(12)
                pdf.set_font("Helvetica", "", fs)
                pdf.set_text_color(*accent_rgb)
                pdf.cell(6, 6, ">")
                pdf.set_text_color(*WHITE)
                if len(line) <= 90:
                    pdf.cell(0, 6, safe(line), ln=True)
                else:
                    pdf.multi_cell(174, 6, safe(line))
            pdf.ln(4)

        if legacy:
            pdf.set_x(12)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(0, 7, "THE FULL STORY", ln=True)
            pdf.ln(1)
            # Pull-quote style: first paragraph large, rest normal
            paragraphs = [p.strip() for p in legacy.split("\n\n") if p.strip()]
            for idx, para in enumerate(paragraphs):
                pdf.set_x(12)
                font_size = fs + 2 if idx == 0 else fs
                pdf.set_font("Helvetica", "I" if idx == 0 else "", font_size)
                pdf.set_text_color(*WHITE)
                pdf.multi_cell(186, 6, safe(para))
                pdf.ln(3)

    # ── STATS, AWARDS & LINKS ─────────────────────────────────────────────────
    pdf.ln(4)
    _render_stats_and_links(pdf, artist_data, social_stats, accent_rgb, fs,
                             text_color=WHITE, section_bg=EDITORIAL_CARD, label_color=LIGHT_GREY)

    if image_path and os.path.exists(image_path):
        try:
            os.unlink(image_path)
        except Exception:
            pass


def _editorial_section_header(pdf, title, accent_rgb):
    y = pdf.get_y()
    # Thin top rule
    pdf.set_fill_color(*accent_rgb)
    pdf.rect(12, y, 186, 1, "F")
    pdf.set_xy(12, y + 3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*accent_rgb)
    pdf.cell(0, 6, title, ln=True)
    # Thin bottom rule
    y2 = pdf.get_y()
    pdf.set_fill_color(*LIGHT_GREY)
    pdf.rect(12, y2, 186, 0.5, "F")
    pdf.ln(4)


def _editorial_metric_grid(pdf, metrics, accent_rgb, fs):
    box_w, box_h, gap = 44, 26, 3
    x0 = 12
    y0 = pdf.get_y()
    for i, (label, value) in enumerate(metrics):
        x = x0 + i * (box_w + gap)
        pdf.set_fill_color(*EDITORIAL_CARD)
        pdf.rect(x, y0, box_w, box_h, "F")
        # Accent top bar
        pdf.set_fill_color(*accent_rgb)
        pdf.rect(x, y0, box_w, 2, "F")
        pdf.set_xy(x + 3, y0 + 4)
        pdf.set_font("Helvetica", "B", 6)
        pdf.set_text_color(*LIGHT_GREY)
        pdf.cell(box_w - 6, 4, safe(label))
        pdf.set_xy(x + 3, y0 + 10)
        pdf.set_font("Helvetica", "B", fs - 1)
        pdf.set_text_color(*WHITE)
        v = safe(value) if len(safe(value)) <= 26 else safe(value)[:23] + "..."
        pdf.multi_cell(box_w - 6, 5, v)
    pdf.set_y(y0 + box_h + 5)


# ─── Template: MINIMAL (clean/light) ─────────────────────────────────────────

def build_minimal(pdf, artist_data, persona, accent_rgb, fs, show_momentum, show_discography, show_bio, social_stats=None):
    """Light background, clean lines. Professional industry-submission style."""

    # Light background
    pdf.set_fill_color(*MINIMAL_BG)
    pdf.rect(0, 0, 210, 297, "F")

    image_path = None
    if artist_data.get("image_url"):
        image_path = download_artist_image(artist_data["image_url"])

    # ── HEADER ────────────────────────────────────────────────────────────────
    header_h = 64
    pdf.set_fill_color(*MINIMAL_HEADER)
    pdf.rect(0, 0, 210, header_h, "F")
    # Bottom border line on header
    pdf.set_fill_color(*accent_rgb)
    pdf.rect(0, header_h - 2, 210, 2, "F")

    if image_path:
        img_size = header_h - 12
        pdf.image(image_path, x=10, y=6, w=img_size)
        text_x = img_size + 16
    else:
        text_x = 12

    pdf.set_xy(text_x, 12)
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*MINIMAL_TEXT)
    pdf.cell(0, 10, safe(artist_data.get("name", "Unknown Artist")), ln=True)

    pdf.set_x(text_x)
    genres = safe(", ".join(artist_data.get("genres", []))[:60] or "Independent Artist")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*MINIMAL_SUBTEXT)
    pdf.cell(0, 6, genres, ln=True)

    pdf.set_x(text_x)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*accent_rgb)
    pdf.cell(0, 5, "Verified by Indie-Go  |  Spotify API  |  2026", ln=True)

    pdf.set_y(header_h + 6)

    # ── CONNECT ───────────────────────────────────────────────────────────────
    _minimal_section_header(pdf, "CONNECT", accent_rgb)
    ss_connect = social_stats or {}
    connect_links = []
    if artist_data.get("artist_id"):
        connect_links.append(("SPOTIFY", f"https://open.spotify.com/artist/{artist_data['artist_id']}"))
    if ss_connect.get("instagram_url"):
        connect_links.append(("INSTAGRAM", ss_connect["instagram_url"][:72]))
    if ss_connect.get("youtube_url"):
        connect_links.append(("YOUTUBE", ss_connect["youtube_url"][:72]))
    if ss_connect.get("merch_url"):
        connect_links.append(("MERCH", ss_connect["merch_url"][:72]))
    if ss_connect.get("contact_email"):
        connect_links.append(("EMAIL", ss_connect["contact_email"][:72]))
    for platform, url in connect_links:
        pdf.set_x(14)
        pdf.set_font("Helvetica", "B", fs)
        pdf.set_text_color(*accent_rgb)
        pdf.cell(28, 6, platform)
        pdf.set_font("Helvetica", "", fs)
        pdf.set_text_color(*MINIMAL_TEXT)
        pdf.cell(0, 6, safe(_friendly_url(url)), link=url, ln=True)
    pdf.ln(3)

    # ── MOMENTUM MATRIX ───────────────────────────────────────────────────────
    if show_momentum:
        _minimal_section_header(pdf, "MOMENTUM MATRIX", accent_rgb)
        metrics = [
            ("RELEASE MOMENTUM", str(artist_data.get("momentum_proxy", "N/A"))),
            ("AVG TEMPO",        f"{artist_data.get('avg_bpm') or 'N/A'} BPM"),
            ("ENERGY PROFILE",   str(artist_data.get("energy_label", "N/A"))),
            ("SONIC MOOD",       str(artist_data.get("valence_label", "N/A"))),
        ]
        _minimal_metric_grid(pdf, metrics, accent_rgb, fs)

    # ── DISCOGRAPHY ───────────────────────────────────────────────────────────
    albums = artist_data.get("albums", [])
    if show_discography and albums:
        _minimal_section_header(pdf, "DISCOGRAPHY", accent_rgb)
        # Table header row
        pdf.set_x(12)
        pdf.set_font("Helvetica", "B", fs - 1)
        pdf.set_text_color(*MINIMAL_SUBTEXT)
        pdf.cell(100, 5, "TITLE")
        pdf.cell(40, 5, "DATE")
        pdf.cell(40, 5, "TYPE", ln=True)
        # Thin rule
        y_rule = pdf.get_y()
        pdf.set_fill_color(*MINIMAL_BORDER)
        pdf.rect(12, y_rule, 186, 0.5, "F")
        pdf.ln(2)
        for album in albums[:6]:
            pdf.set_x(12)
            pdf.set_font("Helvetica", "", fs)
            pdf.set_text_color(*MINIMAL_TEXT)
            pdf.cell(100, 6, safe(album.get("name", "Unknown")[:40]))
            pdf.set_text_color(*MINIMAL_SUBTEXT)
            pdf.cell(40, 6, safe(album.get("release_date", "")[:7]))
            pdf.set_font("Helvetica", "B", fs - 1)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(40, 6, safe(album.get("album_type", "").upper()), ln=True)
        pdf.ln(4)

    # ── ARTIST NARRATIVE ──────────────────────────────────────────────────────
    if show_bio:
        _minimal_section_header(pdf, "ARTIST NARRATIVE", accent_rgb)
        staccato = artist_data.get("staccato_bio") or ""
        legacy   = artist_data.get("legacy_bio") or ""

        if staccato:
            pdf.set_x(12)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*MINIMAL_SUBTEXT)
            pdf.cell(0, 6, "KEY HIGHLIGHTS", ln=True)
            pdf.ln(1)
            lines = [l.strip().lstrip("•-*- ").strip() for l in staccato.split("\n") if l.strip().lstrip("•-*- ").strip()]
            for line in lines:
                pdf.set_x(14)
                pdf.set_font("Helvetica", "", fs)
                pdf.set_text_color(*accent_rgb)
                pdf.cell(5, 6, "-")
                pdf.set_text_color(*MINIMAL_TEXT)
                if len(line) <= 90:
                    pdf.cell(0, 6, safe(line), ln=True)
                else:
                    pdf.multi_cell(177, 6, safe(line))
            pdf.ln(4)

        if legacy:
            pdf.set_x(12)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*MINIMAL_SUBTEXT)
            pdf.cell(0, 6, "FULL BIOGRAPHY", ln=True)
            pdf.ln(2)
            paragraphs = [p.strip() for p in legacy.split("\n\n") if p.strip()]
            if persona != "storyteller":
                paragraphs = paragraphs[:2]
            for para in paragraphs:
                pdf.set_x(12)
                pdf.set_font("Helvetica", "", fs)
                pdf.set_text_color(*MINIMAL_TEXT)
                pdf.multi_cell(186, 6, safe(para))
                pdf.ln(3)

    # ── STATS, AWARDS & LINKS ─────────────────────────────────────────────────
    pdf.ln(4)
    _render_stats_and_links(pdf, artist_data, social_stats, accent_rgb, fs,
                             text_color=MINIMAL_TEXT, section_bg=MINIMAL_CARD, label_color=MINIMAL_SUBTEXT)

    if image_path and os.path.exists(image_path):
        try:
            os.unlink(image_path)
        except Exception:
            pass


def _minimal_section_header(pdf, title, accent_rgb):
    y = pdf.get_y()
    # Left accent bar only
    pdf.set_fill_color(*accent_rgb)
    pdf.rect(12, y, 3, 7, "F")
    pdf.set_xy(18, y + 0.5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*MINIMAL_TEXT)
    pdf.cell(0, 6, title, ln=True)
    pdf.ln(3)


def _minimal_metric_grid(pdf, metrics, accent_rgb, fs):
    box_w, box_h, gap = 44, 22, 3
    x0 = 12
    y0 = pdf.get_y()
    for i, (label, value) in enumerate(metrics):
        x = x0 + i * (box_w + gap)
        pdf.set_fill_color(*MINIMAL_CARD)
        pdf.rect(x, y0, box_w, box_h, "F")
        # Accent left bar
        pdf.set_fill_color(*accent_rgb)
        pdf.rect(x, y0, 2, box_h, "F")
        pdf.set_xy(x + 5, y0 + 3)
        pdf.set_font("Helvetica", "B", 6)
        pdf.set_text_color(*MINIMAL_SUBTEXT)
        pdf.cell(box_w - 7, 4, safe(label))
        pdf.set_xy(x + 5, y0 + 9)
        pdf.set_font("Helvetica", "B", fs - 1)
        pdf.set_text_color(*MINIMAL_TEXT)
        v = safe(value) if len(safe(value)) <= 26 else safe(value)[:23] + "..."
        pdf.multi_cell(box_w - 7, 5, v)
    pdf.set_y(y0 + box_h + 5)


# ─── Shared: Stats & Links section ───────────────────────────────────────────

def _fmt_number(n):
    if n is None: return None
    try:
        n = int(n)
        if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
        if n >= 1_000:     return f"{n/1_000:.1f}K"
        return str(n)
    except Exception:
        return str(n)


def _render_stats_and_links(pdf, artist_data, social_stats, accent_rgb, fs,
                             text_color, section_bg, label_color):
    """
    Renders PLATFORM STATS and CONNECT sections.
    Works across all three templates — caller passes the right colours.
    social_stats: dict from researcher.parse_social_stats()
    """
    ss = social_stats or {}
    spotify_followers = artist_data.get("spotify_followers")
    artist_id         = artist_data.get("artist_id", "")

    # Collect stat rows
    stat_rows = []
    if spotify_followers is not None:
        stat_rows.append(("SPOTIFY FOLLOWERS", safe(_fmt_number(spotify_followers) or "N/A")))
    if ss.get("instagram_followers"):
        stat_rows.append(("INSTAGRAM FOLLOWERS", safe(ss["instagram_followers"])))
    if ss.get("youtube_subscribers"):
        stat_rows.append(("YOUTUBE SUBSCRIBERS", safe(ss["youtube_subscribers"])))

    awards = ss.get("awards", [])

    # Nothing to render in body — links are in footer
    if not stat_rows and not awards:
        return

    # ── PLATFORM STATS ────────────────────────────────────────────────────────
    if stat_rows:
        y = pdf.get_y()
        pdf.set_fill_color(*accent_rgb)
        pdf.rect(10, y, 3, 7, "F")
        pdf.set_fill_color(*section_bg)
        pdf.rect(13, y, 187, 7, "F")
        pdf.set_xy(17, y + 1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*accent_rgb)
        pdf.cell(180, 5, "PLATFORM STATS", ln=True)
        pdf.ln(2)

        col_w = 60
        x0    = 14
        y0    = pdf.get_y()
        for i, (label, value) in enumerate(stat_rows[:4]):
            x = x0 + i * (col_w + 2)
            pdf.set_fill_color(*section_bg)
            pdf.rect(x, y0, col_w, 18, "F")
            pdf.set_xy(x + 3, y0 + 2)
            pdf.set_font("Helvetica", "B", 6)
            pdf.set_text_color(*label_color)
            pdf.cell(col_w - 4, 4, safe(label))
            pdf.set_xy(x + 3, y0 + 7)
            pdf.set_font("Helvetica", "B", fs)
            pdf.set_text_color(*text_color)
            pdf.multi_cell(col_w - 4, 5, value)
        pdf.set_y(y0 + 22)

    # ── AWARDS & ACHIEVEMENTS ─────────────────────────────────────────────────
    if awards:
        pdf.ln(2)
        y = pdf.get_y()
        pdf.set_fill_color(*accent_rgb)
        pdf.rect(10, y, 3, 7, "F")
        pdf.set_fill_color(*section_bg)
        pdf.rect(13, y, 187, 7, "F")
        pdf.set_xy(17, y + 1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*accent_rgb)
        pdf.cell(180, 5, "AWARDS & ACHIEVEMENTS", ln=True)
        pdf.ln(3)
        for award in awards[:8]:
            pdf.set_x(16)
            pdf.set_font("Helvetica", "", fs - 1)
            pdf.set_text_color(*accent_rgb)
            pdf.cell(5, 5, "-")
            pdf.set_text_color(*text_color)
            pdf.multi_cell(179, 5, safe(award))
        pdf.ln(3)

    # Links are handled exclusively by EPKDocument.footer() — not rendered in body.


# ─── EPK Document class ───────────────────────────────────────────────────────

class EPKDocument(FPDF):
    def __init__(self, artist_name, template="Prestige", accent_rgb=SPOTIFY_GREEN,
                 artist_id="", instagram_url=None, youtube_url=None):
        super().__init__()
        self.artist_name   = artist_name
        self.template      = template
        self.accent_rgb    = accent_rgb
        self.artist_id     = artist_id
        self.instagram_url = instagram_url
        self.youtube_url   = youtube_url

    def header(self):
        """Paint the page background on every page so page 2+ are never blank white."""
        if self.template == "Prestige":
            self.set_fill_color(*PAGE_BG)
        elif self.template == "Editorial":
            self.set_fill_color(*EDITORIAL_BG)
        else:  # Minimal
            self.set_fill_color(*MINIMAL_BG)
        self.rect(0, 0, 210, 297, "F")

    def footer(self):
        # ── Line 1: links (accent colour, slightly larger) ────────────────────
        self.set_y(-18)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.accent_rgb)

        link_parts = []
        if self.artist_id:
            link_parts.append(f"Spotify: open.spotify.com/artist/{self.artist_id}")
        if self.instagram_url:
            link_parts.append(f"Instagram: {self.instagram_url[:55]}")
        if self.youtube_url:
            link_parts.append(f"YouTube: {self.youtube_url[:55]}")

        if link_parts:
            self.cell(0, 6, safe("  |  ".join(link_parts)), align="C", ln=True)

        # ── Line 2: Indie-Go branding (grey, small) ───────────────────────────
        self.set_font("Helvetica", "I", 7)
        if self.template == "Minimal":
            self.set_text_color(*MINIMAL_SUBTEXT)
        else:
            self.set_text_color(*LIGHT_GREY)
        self.cell(
            0, 5,
            f"Indie-Go  |  Verified EPK  |  {datetime.now().strftime('%d %B %Y')}  |  Page {self.page_no()}",
            align="C",
        )


# ─── Main export function ─────────────────────────────────────────────────────

def generate_epk_pdf(artist_data, persona, settings=None, social_stats=None):
    """
    Generates A4 EPK PDF.
    settings keys:
        template        : "Prestige" | "Editorial" | "Minimal"
        primary_color   : hex string e.g. "#1DB954"
        font_size       : int (8–14)
        show_momentum   : bool
        show_discography: bool
        show_bio        : bool
    social_stats: dict from researcher.parse_social_stats()
    Returns bytes or None.
    """
    if settings is None:
        settings = {}

    template         = settings.get("template", "Prestige")
    hex_color        = settings.get("primary_color", "#1DB954")
    fs               = int(settings.get("font_size", 10))
    show_momentum    = settings.get("show_momentum", True)
    show_discography = settings.get("show_discography", True)
    show_bio         = settings.get("show_bio", True)

    accent_rgb = hex_to_rgb(hex_color)
    ss         = social_stats or {}

    pdf = EPKDocument(
        artist_data.get("name", "Artist"),
        template      = template,
        accent_rgb    = accent_rgb,
        artist_id     = artist_data.get("artist_id", ""),
        instagram_url = ss.get("instagram_url"),
        youtube_url   = ss.get("youtube_url"),
    )
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(auto=True, margin=22)  # Extra room for 2-line footer
    pdf.add_page()

    if template == "Prestige":
        build_prestige(pdf, artist_data, persona, accent_rgb, fs, show_momentum, show_discography, show_bio, social_stats)
    elif template == "Editorial":
        build_editorial(pdf, artist_data, persona, accent_rgb, fs, show_momentum, show_discography, show_bio, social_stats)
    else:  # Minimal
        build_minimal(pdf, artist_data, persona, accent_rgb, fs, show_momentum, show_discography, show_bio, social_stats)

    return bytes(pdf.output())
