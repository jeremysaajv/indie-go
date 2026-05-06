# Indie-Go — Project Context for Claude

## What This Is
Indie-Go is a zero-cost automated EPK (Electronic Press Kit) generator for independent musicians.
Built with Python + Streamlit. Generates a styled A4 PDF from live Spotify API data + online research.

---

## Project File Map

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI — left controls panel + right HTML preview |
| `harvester.py` | Spotify API: fetches artist data, discography, followers |
| `audio_analyzer.py` | Librosa audio analysis (BPM, energy, valence) — currently N/A due to Spotify removing preview_url |
| `researcher.py` | Online research: Bing scraping + music databases (Wikipedia, Last.fm, MusicBrainz, Genius, Bandcamp) |
| `synthesizer.py` | Bio generation via Claude Sonnet — factual, stats-driven, no purple prose |
| `exporter.py` | PDF generation via fpdf2 — three templates: Prestige, Editorial, Minimal |
| `config.py` | Central settings/constants |
| `auth.py` | Spotify OAuth token handling |
| `requirements.txt` | All dependencies |
| `.env.template` | Template for SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, ANTHROPIC_API_KEY |
| `run.bat` | Double-click to start: `streamlit run app.py --server.port 8080` |

---

## Architecture Decisions

### PDF Templates (exporter.py)
Three templates, each a separate build function:
- **Prestige** — Dark Spotify-style. `build_prestige()`. Background: `PAGE_BG (24,24,24)`, header: `DARK_BG (18,18,18)`
- **Editorial** — Magazine style. `build_editorial()`. Full-width image banner. Background: `EDITORIAL_BG (15,15,35)`
- **Minimal** — Clean light. `build_minimal()`. Background: `MINIMAL_BG (248,248,248)`

All templates share the same section order (top to bottom on page 1):
1. **Header** (artist photo + name + genres + branding)
2. **CONNECT** — Spotify always + Instagram/YouTube if found by researcher
3. **MOMENTUM MATRIX** — 4 metric cards (Release Momentum, Avg Tempo, Energy Profile, Sonic Mood)
4. **DISCOGRAPHY** — Up to 6 releases
5. **ARTIST NARRATIVE** — KEY HIGHLIGHTS (bullets) + FULL BIOGRAPHY (prose)
6. **PLATFORM STATS** — Follower counts (Spotify, Instagram, YouTube)
7. **AWARDS & ACHIEVEMENTS** — Named awards from research

### Page Background Fix
`EPKDocument.header()` is overridden to paint the full-page background on EVERY page.
This prevents page 2 from being blank white when content overflows.
The explicit `pdf.rect(0,0,210,297)` at start of each build function is still there for page 1 (belt + suspenders).

### CONNECT Section (the long-fought battle)
User's core requirement: Spotify/Instagram/YouTube links must appear as a **visible styled section** on page 1.
NOT in the footer only. NOT at the bottom of the page where bio pushes it to page 2.
**Solution**: CONNECT is rendered immediately after the header, before MOMENTUM MATRIX. Always on page 1.
Format: bold platform name (accent color, 28mm) + URL (body text color).

### Footer
Every page footer has two lines:
- Line 1: Spotify | Instagram | YouTube links (accent color, 7pt bold)  
- Line 2: Indie-Go branding + date + page number (grey, 7pt italic)
`set_auto_page_break(auto=True, margin=22)` — extra margin for 2-line footer.

### Bio Generation (synthesizer.py)
- Model: `claude-sonnet-4-6`, temperature=0.1, max_tokens=2500
- Output split on `---LEGACY---` separator: staccato (bullet facts) + legacy (prose bio)
- Persona system: `visualist` | `statistician` | `storyteller`
- Rules enforced in system prompt: no markdown formatting, no invented facts, no "sonic journey" language
- Stats injected into prompt: Spotify followers, Instagram followers, YouTube subscribers, named awards
- `safe()` function strips: smart quotes, em dashes, ellipsis, `**`, `*`, markdown underscores → latin-1 safe

### Online Research (researcher.py)
- Primary search: Bing HTML scraping (`<li class="b_algo">` blocks)
- Fallback: DuckDuckGo (rate-limits silently so deprioritised)
- Direct databases: Wikipedia REST API, Last.fm, MusicBrainz, Genius, Bandcamp, AllMusic
- Relevance filter: `_is_relevant()` requires FULL artist name as substring (not just first/last name)
  - Prevents garbage like "Ariel Efraim Ashbel" matching a search for "Ashbel Peter"
- MAX_SOURCES = 15 (hard cap, no minimum — obscure artists may have 2-3 sources)
- `parse_social_stats()` extracts: Instagram URL + followers, YouTube URL + subscribers, named awards (capped at 12)

### Spotify Data (harvester.py)
- `sp.artist()` → `followers.total` stored as `spotify_followers`
- `spotify_url` = `open.spotify.com/artist/{artist_id}`
- `audio_debug` field stores diagnostic from `analyze_artist_audio()`

### Audio Analysis (audio_analyzer.py)
- Uses Librosa. Currently returns N/A for most artists.
- Root cause: Spotify deprecated `preview_url` in 2024. No 30-second clips = nothing to analyse.
- Returns `{"debug": "No preview URLs found"}` or `{"debug": "All clips failed (needs ffmpeg)"}` instead of None.
- Debug message is surfaced in the UI in "🔍 Audio Analysis Log" expander.

---

## Known Issues / Pending Work

### Bio overflow to page 2
Currently bio is capped to `[:2]` paragraphs for non-storyteller, `all` for storyteller.
If bio is long, it overflows to page 2. The background fix (header() override) means page 2 is now properly styled.
But ideally the bio should be short enough to stay on page 1.
**Pending**: Consider capping bio to 1 paragraph for non-storyteller, or adding a char limit in synthesizer max_tokens.

### Librosa / BPM / Energy Profile / Sonic Mood = N/A
All three Momentum Matrix fields that depend on audio analysis will always be N/A until Spotify preview_url is replaced.
Options for future: use a different audio source (YouTube preview, SoundCloud), or let user manually input BPM.

### Instagram followers not always found
`parse_social_stats()` uses regex to extract follower counts from scraped text.
For many artists the Instagram page isn't scraped or the count format doesn't match.
This is a known limitation of free scraping.

---

## UI Structure (app.py)
Left panel controls:
- Artist name input + Search button
- Persona selector (Visualist / Statistician / Storyteller)
- 🔍 Online Research button
- Stats display: Spotify followers (link), Instagram (link + followers), YouTube (link + subscribers), Awards expander
- Editable Momentum Matrix: 4 text_input fields (pre-filled from artist data, injected at export time)
- Template selector: Prestige / Editorial / Minimal
- Settings: Primary colour picker, Font size slider, Show/hide toggles (Momentum, Discography, Bio)
- Generate Bio button
- Export PDF button

Right panel:
- HTML preview of the EPK (mirrors the PDF content visually)
- 🔍 Audio Analysis Log expander (shows why BPM/Energy/Mood are N/A)

Session state keys: `artist_data`, `artist_research`, `research_debug`, `social_stats`, `staccato_bio`, `legacy_bio`

---

## Design Principles (User Preferences)
- **No purple prose**: Bio must be factual, punchy, statistics-first. No "sonic journeys", no "captivating listeners worldwide"
- **Stats visible in PDF**: Follower counts, named awards, release count must appear as data, not narrative filler
- **Links as a real section**: CONNECT must be a visible styled section, not tiny footer text
- **One page preferred**: Everything should ideally fit on page 1 of the PDF
- **Three distinct templates**: Each must look genuinely different, not just colour-swapped

---

## Running the App
```
cd "C:\Users\Jeremy\OneDrive\Documents\Claude\Projects\MIP Project\indie-go"
streamlit run app.py --server.port 8080
```
Or double-click `run.bat`.

Open: http://localhost:8080

---

## Environment Variables Required (.env file)
```
SPOTIFY_CLIENT_ID=your_key
SPOTIFY_CLIENT_SECRET=your_key
ANTHROPIC_API_KEY=your_key
```
