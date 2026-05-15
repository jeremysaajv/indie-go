"""
Indie-Go — Artist Web Researcher
Multi-engine web research: Bing scraping, Wikipedia, music databases,
social media. Capped at 15 real sources per artist. No API keys required.
"""

import re
import time
import requests
from urllib.parse import urlparse, quote_plus

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

SKIP_DOMAINS = {"open.spotify.com", "accounts.spotify.com", "spotify.com"}

# Domains that are never relevant to music artist research
_NOISE_DOMAINS = {
    "zhihu.com", "quora.com", "reddit.com", "stackoverflow.com",
    "stackexchange.com", "wikihow.com", "answers.yahoo.com",
    "amazon.com", "ebay.com", "etsy.com",
    "linkedin.com", "glassdoor.com", "indeed.com",
    "coursera.org", "udemy.com", "khan academy.org",
    "aliexpress.com", "taobao.com", "jd.com",
    "weibo.com", "baidu.com", "163.com", "sina.com.cn",
}


def _domain(url):
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _is_useful(url):
    d = _domain(url)
    if any(skip in d for skip in SKIP_DOMAINS):
        return False
    if any(noise in d for noise in _NOISE_DOMAINS):
        return False
    return True


def _is_relevant(result, artist_name):
    """
    Returns True only if the result genuinely relates to the artist.
    Checks title + URL first (strong signal), then snippet (weak signal).
    Also checks name without spaces for social media handles like
    @ashbelpeter, youtube.com/@derekandthecats, etc.
    Music databases and direct lookups bypass this check via skip_relevance=True.
    """
    full_name     = artist_name.lower().strip()
    name_no_space = full_name.replace(" ", "")

    title = (result.get("title") or "").lower()
    body  = (result.get("body")  or "").lower()
    href  = (result.get("href")  or "").lower()

    # Strong signal — name in title or URL
    if full_name in title or full_name in href:
        return True
    if name_no_space in title or name_no_space in href:
        return True

    # Weak signal — name in snippet, but require a music context word too.
    # This prevents misaligned Google blocks (zhihu URL + Derek snippet body)
    # from sneaking through just because the wrong body was paired with a URL.
    if len(body) > 80 and (full_name in body or name_no_space in body):
        _music_ctx = {
            "musician", "artist", "music", "band", "album", "single",
            "song", "tour", "concert", "release", "spotify", "label",
            "genre", "ep", "debut", "track", "record", "singer",
        }
        if any(t in body for t in _music_ctx):
            return True

    return False


def _strip_html(html, max_chars=2500):
    html = re.sub(
        r'<(script|style|noscript|iframe)[^>]*>.*?</(script|style|noscript|iframe)>',
        ' ', html, flags=re.DOTALL | re.IGNORECASE
    )
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


def _fetch(url, max_chars=2500):
    try:
        r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "")
        if "text" not in ct:
            return None
        return _strip_html(r.text, max_chars) or None
    except Exception:
        return None


# ─── Google search scraper (no API key) ──────────────────────────────────────

_GOOGLE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

def _google_search(query, max_results=10, log=None):
    """
    Scrape Google search results. Returns list of {href, title, body}.
    Splits on <div class="g"> blocks so results never bleed into each other.
    Falls back to DDG if Google returns a CAPTCHA/429.
    """
    from urllib.parse import unquote
    results = []
    try:
        url = (
            f"https://www.google.com/search"
            f"?q={quote_plus(query)}&num={max_results}&hl=en&gl=us"
        )
        r = requests.get(url, timeout=12, headers=_GOOGLE_HEADERS)

        if r.status_code == 429:
            if log is not None: log.append(f'Google "{query}" → rate-limited (429), trying DDG')
            return _ddg_search(query, max_results)
        if r.status_code != 200:
            if log is not None: log.append(f'Google "{query}" → HTTP {r.status_code}')
            return []

        html = r.text

        # Detect CAPTCHA / consent page (no real results)
        if 'id="captcha"' in html or 'consent.google.com' in html or '/sorry/' in html:
            if log is not None: log.append(f'Google "{query}" → blocked/consent, trying DDG')
            return _ddg_search(query, max_results)

        # Split on organic result blocks — Google wraps each in <div class="g"...>
        # Cap each segment at 4000 chars to stay within that one result block.
        segments  = re.split(r'(?=<div\b[^>]*\bclass="(?:[^"]*\s)?g(?:\s[^"]*)?")', html)
        blocks    = [s[:4000] for s in segments if '<h3' in s[:600]]
        blocks    = blocks[:max_results * 2]  # over-fetch then trim

        seen = set()
        for block in blocks:
            if len(results) >= max_results:
                break

            # Google encodes result URLs as href="/url?q=https://...&sa=..."
            href = None
            m = re.search(r'href="/url\?q=(https?://[^&"]+)', block)
            if m:
                href = unquote(m.group(1))
            else:
                # Some blocks use direct hrefs (news, featured snippets)
                m = re.search(r'href="(https?://(?!(?:www\.)?google\.)[^"]+)"', block)
                if m:
                    href = m.group(1)

            if not href or not _is_useful(href) or href in seen:
                continue
            seen.add(href)

            # Title from <h3>
            title_m = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
            title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else _domain(href)

            # Snippet — try multiple Google class patterns (they change these often)
            snippet = ""
            for pat in [
                r'<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>',
                r'<span[^>]*class="[^"]*aCOpRe[^"]*"[^>]*>(.*?)</span>',
                r'<div[^>]*data-sncf[^>]*>(.*?)</div>',
                r'<div[^>]*class="[^"]*s3v9rd[^"]*"[^>]*>(.*?)</div>',
            ]:
                sm = re.search(pat, block, re.DOTALL)
                if sm:
                    snippet = re.sub(r'<[^>]+>', ' ', sm.group(1))
                    snippet = re.sub(r'\s+', ' ', snippet).strip()
                    break

            results.append({"href": href, "title": title, "body": snippet})

        if log is not None:
            log.append(f'Google "{query}" → {len(results)} results')
    except Exception as e:
        if log is not None:
            log.append(f'Google "{query}" → error: {e}')
    return results


# ─── DuckDuckGo (fallback) ────────────────────────────────────────────────────

def _ddg_search(query, max_results=6):
    """Single DDG query. Returns list of {href, title, body} or []."""
    if not DDGS_AVAILABLE:
        return []
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results, region="us-en"))
            return [{"href": h.get("href",""), "title": h.get("title",""), "body": h.get("body","")}
                    for h in hits if h.get("href")]
    except Exception:
        return []


def _search(query, max_results=8, log=None):
    """Google first, DDG as fallback if Google is blocked or returns nothing."""
    results = _google_search(query, max_results, log)
    if not results:
        results = _ddg_search(query, max_results)
        if results and log is not None:
            log.append(f'  (DDG fallback: {len(results)} results)')
    return results


# ─── Wikipedia ────────────────────────────────────────────────────────────────

def _wikipedia(artist_name, log):
    """Fetch Wikipedia article via REST API — most comprehensive source for notable artists."""
    try:
        # Try summary first (fast)
        slug = artist_name.replace(" ", "_")
        api  = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(slug)}"
        r    = requests.get(api, timeout=8, headers=HEADERS)
        if r.status_code == 200:
            data    = r.json()
            extract = data.get("extract", "")
            if extract and len(extract) > 100:
                log.append(f"Wikipedia summary ✓ ({len(extract)} chars)")
                # Also try to get the full intro section for more detail
                full_url = f"https://en.wikipedia.org/wiki/{quote_plus(slug)}"
                full_text = _fetch(full_url, max_chars=5000)
                return {
                    "title":     f"{artist_name} — Wikipedia",
                    "source":    full_url,
                    "domain":    "en.wikipedia.org",
                    "snippet":   extract[:800],
                    "full_text": full_text,
                }
    except Exception as e:
        log.append(f"Wikipedia error: {e}")
    log.append("Wikipedia: not found")
    return None


# ─── Music databases ─────────────────────────────────────────────────────────

def _lastfm(artist_name, log):
    url  = f"https://www.last.fm/music/{quote_plus(artist_name)}"
    text = _fetch(url, 3000)
    if text and len(text) > 300:
        log.append(f"Last.fm ✓ ({len(text)} chars)")
        return {"title": f"{artist_name} — Last.fm", "source": url,
                "domain": "last.fm", "snippet": "", "full_text": text}
    log.append("Last.fm: no content")
    return None


def _musicbrainz(artist_name, log, first_release_year=None):
    try:
        api = (f"https://musicbrainz.org/ws/2/artist/"
               f"?query=artist:{quote_plus(artist_name)}&fmt=json&limit=5")
        r = requests.get(api, timeout=8,
                         headers={"User-Agent": "Indie-Go/1.0 (contact@indie-go.app)"})
        if r.status_code == 200:
            artists = r.json().get("artists", [])
            # Pick the best match — if we know the first release year, reject artists
            # whose active period predates it by more than 10 years (different person).
            chosen = None
            for a in artists:
                begin = (a.get("life-span") or {}).get("begin") or ""
                begin_year = int(begin[:4]) if begin and begin[:4].isdigit() else None
                if first_release_year and begin_year:
                    if begin_year < first_release_year - 10:
                        log.append(f"MusicBrainz: skipping '{a.get('name')}' (active {begin_year}, expected ~{first_release_year})")
                        continue
                chosen = a
                break

            if chosen:
                parts = []
                if chosen.get("disambiguation"): parts.append(chosen["disambiguation"])
                if chosen.get("country"):        parts.append(f"Country: {chosen['country']}")
                if (chosen.get("life-span") or {}).get("begin"):
                    parts.append(f"Active since: {chosen['life-span']['begin']}")
                tags = [t["name"] for t in chosen.get("tags", [])[:8]]
                if tags: parts.append(f"Tags: {', '.join(tags)}")
                if parts:
                    log.append("MusicBrainz ✓")
                    return {"title": f"{artist_name} — MusicBrainz",
                            "source": f"https://musicbrainz.org/artist/{chosen.get('id','')}",
                            "domain": "musicbrainz.org",
                            "snippet": " | ".join(parts), "full_text": None}
    except Exception as e:
        log.append(f"MusicBrainz error: {e}")
    log.append("MusicBrainz: not found")
    return None


def _genius(artist_name, log):
    slug = artist_name.replace(" ", "-")
    url  = f"https://genius.com/artists/{quote_plus(slug)}"
    text = _fetch(url, 2500)
    if text and len(text) > 300:
        log.append(f"Genius ✓ ({len(text)} chars)")
        return {"title": f"{artist_name} — Genius", "source": url,
                "domain": "genius.com", "snippet": "", "full_text": text}
    log.append("Genius: not found")
    return None


def _allmusic(artist_name, log):
    url  = f"https://www.allmusic.com/search/artists/{quote_plus(artist_name)}"
    text = _fetch(url, 2000)
    if text and len(text) > 300:
        log.append(f"AllMusic ✓")
        return {"title": f"{artist_name} — AllMusic", "source": url,
                "domain": "allmusic.com", "snippet": "", "full_text": text}
    log.append("AllMusic: not found")
    return None


# ─── Social stats parser ──────────────────────────────────────────────────────

def parse_social_stats(items):
    """
    Scan research items for follower counts, profile links, and award mentions.
    Returns a dict:
      {
        instagram_url, instagram_followers,
        youtube_url,   youtube_subscribers,
        awards: [str, ...]    # named awards found in text
      }
    """
    stats = {
        "instagram_url":       None,
        "instagram_followers": None,
        "youtube_url":         None,
        "youtube_subscribers": None,
        "awards":              [],
    }

    # Follower/subscriber number patterns  e.g. "24.8M Followers", "1,200 followers"
    _follower_re  = re.compile(r'([\d,]+(?:\.\d+)?[MKBmkb]?)\s*[Ff]ollower', re.I)
    _sub_re       = re.compile(r'([\d,]+(?:\.\d+)?[MKBmkb]?)\s*[Ss]ubscriber', re.I)

    # Award name patterns — ordered by specificity
    _award_pats = [
        re.compile(r'Grammy Award[^.]{0,80}', re.I),
        re.compile(r'Billboard Music Award[^.]{0,80}', re.I),
        re.compile(r'MTV (Video )?Music Award[^.]{0,80}', re.I),
        re.compile(r'BET Award[^.]{0,80}', re.I),
        re.compile(r'American Music Award[^.]{0,80}', re.I),
        re.compile(r'iHeartRadio Music Award[^.]{0,80}', re.I),
        re.compile(r'People\'s Choice Award[^.]{0,80}', re.I),
        re.compile(r'BRIT Award[^.]{0,80}', re.I),
        re.compile(r'ARIA Award[^.]{0,80}', re.I),
        re.compile(r'won[^.]{0,60}award[^.]{0,40}', re.I),
        re.compile(r'nominated[^.]{0,60}Grammy[^.]{0,40}', re.I),
    ]

    seen_awards = set()

    for item in items:
        url     = item.get("source", "")
        domain  = item.get("domain", "")
        text    = ((item.get("snippet") or "") + " " + (item.get("full_text") or "")).strip()

        # ── Instagram ────────────────────────────────────────────────────────
        if "instagram.com" in domain or "instagram.com" in url:
            if not stats["instagram_url"]:
                stats["instagram_url"] = url
            if not stats["instagram_followers"]:
                m = _follower_re.search(text)
                if m:
                    stats["instagram_followers"] = m.group(1).strip()

        # ── YouTube ──────────────────────────────────────────────────────────
        if "youtube.com" in domain or "youtube.com" in url:
            if not stats["youtube_url"]:
                stats["youtube_url"] = url
            if not stats["youtube_subscribers"]:
                m = _sub_re.search(text)
                if m:
                    stats["youtube_subscribers"] = m.group(1).strip()

        # ── Awards ────────────────────────────────────────────────────────────
        for pat in _award_pats:
            for match in pat.findall(text):
                clean = re.sub(r'\s+', ' ', match).strip().rstrip(",.")
                key   = clean.lower()[:60]
                if key not in seen_awards and len(clean) < 120:
                    seen_awards.add(key)
                    stats["awards"].append(clean)

    stats["awards"] = stats["awards"][:12]   # cap at 12 award mentions
    return stats


# ─── Direct social profile prober ────────────────────────────────────────────

def _probe_social_profiles(artist_name, log):
    """
    Construct likely social media handles and verify them via GET request.
    Uses body content validation — Instagram/YouTube both serve 200 for dead
    pages sometimes, so we check the response text confirms the profile exists.

    Slug variants tried (in order):
      compact:    "derekandthecats"
      hyphenated: "derek-and-the-cats"
      underscored:"derek_and_the_cats"
    """
    base = artist_name.lower()
    base = re.sub(r'&', 'and', base)
    base = re.sub(r"[^\w\s-]", '', base).strip()

    slug_compact = base.replace(" ", "")
    slug_hyphen  = base.replace(" ", "-")
    slug_under   = base.replace(" ", "_")

    # Instagram candidates first, then YouTube variants
    candidates = []
    for slug in dict.fromkeys([slug_compact, slug_hyphen, slug_under]):
        candidates.append((f"https://www.instagram.com/{slug}/", "instagram.com", "ig"))
        candidates.append((f"https://www.youtube.com/@{slug}",   "youtube.com",   "yt"))
        candidates.append((f"https://www.youtube.com/c/{slug}",  "youtube.com",   "yt"))

    found = []
    seen_platforms = set()   # "ig", "yt" — stop after first confirmed hit per platform

    _probe_headers = {
        **HEADERS,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

    for url, dom, platform in candidates:
        if platform in seen_platforms:
            continue
        try:
            r = requests.get(url, timeout=8, headers=_probe_headers,
                             allow_redirects=True)

            # ── Instagram validation ──────────────────────────────────────────
            # Instagram 404s redirect to login (final URL = instagram.com/accounts/...)
            # A valid profile page keeps the URL on instagram.com/{slug}
            if platform == "ig":
                final_url = r.url.rstrip("/").lower()
                slug_in_url = any(
                    s in final_url
                    for s in [slug_compact, slug_hyphen, slug_under]
                )
                is_login_redirect = "accounts" in final_url or "login" in final_url
                if r.status_code == 200 and slug_in_url and not is_login_redirect:
                    log.append(f"  Instagram ✓ {url}")
                    found.append({"href": url, "title": f"{artist_name} — Instagram", "body": ""})
                    seen_platforms.add(platform)
                else:
                    log.append(f"  Instagram miss ({r.status_code}, final={r.url[:60]}): {url}")

            # ── YouTube validation ────────────────────────────────────────────
            # YouTube 404s return status 404 or redirect to youtube.com
            # A valid channel page contains the channel handle or name in the HTML
            elif platform == "yt":
                if r.status_code == 200:
                    body_lower = r.text[:8000].lower()
                    slug_found = any(
                        s in body_lower
                        for s in [slug_compact, slug_hyphen, slug_under,
                                  artist_name.lower()]
                    )
                    if slug_found:
                        log.append(f"  YouTube ✓ {url}")
                        found.append({"href": url, "title": f"{artist_name} — YouTube", "body": ""})
                        seen_platforms.add(platform)
                    else:
                        log.append(f"  YouTube miss (handle not in body): {url}")
                else:
                    log.append(f"  YouTube {r.status_code}: {url}")

        except Exception as e:
            log.append(f"  Probe error ({url}): {e}")

    return found


# ─── Main entry point ─────────────────────────────────────────────────────────

def research_artist(artist_name, genres=None, artist_id=None,
                    known_tracks=None, first_release_year=None):
    """
    Multi-strategy web research. Targets up to 15 sources.
    known_tracks: list of track/album names from Spotify (used to disambiguate).
    first_release_year: int year of earliest known release (used to reject wrong-era results).
    Returns (items: list[dict], debug_log: str).
    """
    log   = [f"=== Research: {artist_name} ===\n"]
    items = []
    seen  = set()

    genre_hint   = genres[0] if genres else "musician"
    anchor_track = known_tracks[0] if known_tracks else None  # most recent track for disambiguation

    MAX_SOURCES = 15

    def add_item(r, full_text=None, skip_relevance=False):
        if len(items) >= MAX_SOURCES:
            return False
        url = r.get("href") or r.get("source", "")
        if not url or url in seen or not _is_useful(url):
            return False
        # Relevance filter: skip results that don't mention the artist at all
        # (bypass for direct database lookups which are always relevant)
        if not skip_relevance and not _is_relevant(r, artist_name):
            return False
        seen.add(url)
        snippet = r.get("body") or r.get("snippet", "")
        # Social media profile URLs are always kept even without a snippet —
        # parse_social_stats() only needs the URL, not the page content.
        d = _domain(url)
        is_social = any(s in d for s in [
            "instagram.com", "youtube.com", "facebook.com",
            "twitter.com", "x.com", "tiktok.com"
        ])
        if snippet or full_text or r.get("full_text") or is_social:
            items.append({
                "title":     r.get("title", _domain(url)),
                "source":    url,
                "domain":    _domain(url),
                "snippet":   snippet,
                "full_text": full_text or r.get("full_text"),
            })
            return True
        return False

    # ── 0. Social profiles — always first, guaranteed slots ───────────────────
    # Run before everything else so Instagram + YouTube are never crowded out.
    log.append("--- Social Profiles (priority) ---")
    for r in _probe_social_profiles(artist_name, log):
        add_item(r, skip_relevance=True)

    # ── 1. Wikipedia ──────────────────────────────────────────────────────────
    log.append("--- Wikipedia ---")
    wiki = _wikipedia(artist_name, log)
    if wiki:
        add_item({"href": wiki["source"], "title": wiki["title"],
                  "body": wiki["snippet"], "full_text": wiki["full_text"]},
                 skip_relevance=True)

    # ── 2. General web search (Bing + DDG fallback) ───────────────────────────
    log.append("\n--- Web Search ---")
    general_queries = []

    # If we have a known track, lead with a disambiguating query.
    # This pins the search to the correct artist when two people share a name.
    if anchor_track:
        log.append(f"  Disambiguation anchor track: \"{anchor_track}\"")
        general_queries.append(f"{artist_name} \"{anchor_track}\"")
        general_queries.append(f"{artist_name} \"{anchor_track}\" musician")

    general_queries += [
        f"{artist_name} musician artist",
        f"{artist_name} {genre_hint} biography",
        f"{artist_name} music awards achievements",
        f"{artist_name} artist interview",
        f"{artist_name} music review",
        f"{artist_name} artist profile",
    ]
    for q in general_queries:
        if len(items) >= MAX_SOURCES: break
        for r in _search(q, max_results=6, log=log):
            add_item(r)
        time.sleep(0.3)

    # ── 3. Awards & achievements focused search ───────────────────────────────
    log.append("\n--- Awards & Achievements ---")
    award_queries = [
        f"{artist_name} Grammy award nominations wins",
        f"{artist_name} music awards won",
        f"{artist_name} Billboard chart history",
        f"{artist_name} achievements career milestones",
        f"{artist_name} certified platinum gold album",
    ]
    for q in award_queries:
        if len(items) >= MAX_SOURCES: break
        for r in _search(q, max_results=5, log=log):
            add_item(r)
        time.sleep(0.3)

    # ── 4. Press & news articles ──────────────────────────────────────────────
    log.append("\n--- Press & News ---")
    press_queries = [
        f"{artist_name} Rolling Stone",
        f"{artist_name} Billboard magazine",
        f"{artist_name} NME Pitchfork",
        f"{artist_name} news 2024 2025",
        f"{artist_name} new music release",
    ]
    for q in press_queries:
        if len(items) >= MAX_SOURCES: break
        for r in _search(q, max_results=5, log=log):
            add_item(r)
        time.sleep(0.3)

    # ── 5. Social media search fallback (supplements direct probe) ───────────
    # Only runs if direct probe missed Instagram or YouTube (e.g. unusual handle).
    if len(items) < MAX_SOURCES:
        log.append("\n--- Social Media (search fallback) ---")
        social_queries = [
            f"{artist_name} official Instagram",
            f"{artist_name} YouTube channel music",
        ]
        social_blocked = {"instagram.com", "tiktok.com"}
        for q in social_queries:
            if len(items) >= MAX_SOURCES: break
            for r in _search(q, max_results=4, log=log):
                url = r.get("href", "")
                d   = _domain(url)
                ft  = None if d in social_blocked else _fetch(url, 2000)
                add_item(r, full_text=ft)
            time.sleep(0.3)

    # ── 6. Spotify ID reverse-search ─────────────────────────────────────────
    if artist_id and len(items) < MAX_SOURCES:
        log.append("\n--- Spotify ID Reverse Search ---")
        for r in _search(f"open.spotify.com/artist/{artist_id}", max_results=5, log=log):
            add_item(r, skip_relevance=True)

    # ── 7. Music databases (direct) — always relevant, skip relevance check ──
    log.append("\n--- Music Databases ---")
    for fn in [_lastfm, _genius, _allmusic]:
        if len(items) >= MAX_SOURCES: break
        result = fn(artist_name, log)
        if result:
            add_item(result, skip_relevance=True)

    # MusicBrainz separately so we can pass the year hint for disambiguation
    if len(items) < MAX_SOURCES:
        mb = _musicbrainz(artist_name, log, first_release_year=first_release_year)
        if mb:
            add_item(mb, skip_relevance=True)

    # ── Fetch full article text for items that only have snippets ─────────────
    log.append("\n--- Fetching full article text ---")
    fetched = 0
    for item in items:
        if fetched >= 8:
            break
        if not item.get("full_text") and item.get("snippet"):
            d = item["domain"]
            if d not in {"instagram.com", "tiktok.com", "facebook.com",
                         "twitter.com", "x.com", "musicbrainz.org"}:
                text = _fetch(item["source"], 3000)
                if text:
                    item["full_text"] = text
                    log.append(f"  Fetched: {d} ({len(text)} chars)")
                    fetched += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    log.append(f"\n=== Done: {len(items)} source(s) found ===")
    if not items:
        log.append("Zero sources found. Bio will use Spotify data only.")

    return items, "\n".join(log)
