import os
import anthropic


# ─── Persona tone directives (factual-first, no purple prose) ────────────────

PERSONA_INSTRUCTIONS = {
    "visualist": (
        "Write with a clean, image-conscious tone. Reference the artist's aesthetic and visual "
        "identity where supported by the data. Keep language precise — no vague adjectives, no "
        "over-the-top metaphors. One well-chosen description is worth ten generic ones."
    ),
    "statistician": (
        "Lead with numbers and facts. Release count, tempo, certifications, chart positions, "
        "follower milestones — put these front and centre. Keep sentences short and direct. "
        "A booker or A&R needs to scan this in 10 seconds and come away with a clear picture."
    ),
    "storyteller": (
        "Tell the artist's story using only verified facts. Connect the data points into a "
        "logical narrative arc — where they started, what they've released, what the numbers say "
        "about their trajectory. No invented drama, no speculation."
    ),
}

SYSTEM_PROMPT = """You are a music publicist writing Electronic Press Kit (EPK) bios in 2026.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES — NON-NEGOTIABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. ONLY use facts explicitly stated in the data below. Never invent numbers, track names,
   awards, collaborators, or quotes.
2. If a data field is missing or N/A — skip it entirely. Do not mention it.
3. If press research is provided, you MAY reference confirmed facts from it
   (e.g. a named publication, a confirmed award, a confirmed event). If unsure, skip it.
4. Keep language direct and factual. No cinematic metaphors. No "sonic journeys".
   No phrases like "carving a niche" or "captivating listeners worldwide" unless
   backed by a specific statistic or source in the data.
5. Awards: if awards are listed in the data, name them explicitly.
6. Follower/listener counts: if provided, include them as statistics in the bio.
7. NEVER mention Spotify popularity score or generic "growing fanbase" language.
8. Do NOT use markdown formatting of any kind — no asterisks, no bold, no underscores, no headers.
   Plain text only. Song and album titles should use regular quotes if needed, not asterisks.

TONE:
{persona_instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Produce exactly two sections separated by ---LEGACY---

SECTION 1 — KEY FACTS (staccato bullets):
- 3 to 5 bullet points
- Each bullet is ONE factual sentence — a statistic, a verified achievement, or a release fact
- Lead with the most impressive verifiable fact first
- Format: bullet character • then the fact
- No filler. If you only have 3 solid facts, write 3 bullets.

---LEGACY---

SECTION 2 — FULL BIO (prose):
- 2 to 3 paragraphs
- Each paragraph 2–4 sentences
- Factual, professional, no clichés
- If awards or follower counts are available, include them in the prose
- No headers, no bullet points inside this section
"""


def _fmt_number(n):
    """Format a raw follower integer to a readable string e.g. 1234567 → '1.2M'."""
    if n is None:
        return None
    try:
        n = int(n)
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)
    except Exception:
        return str(n)


def _build_stats_block(artist_data, social_stats):
    """
    Build a clean stats text block for the prompt.
    social_stats comes from researcher.parse_social_stats().
    """
    lines = []
    if artist_data.get("spotify_followers") is not None:
        lines.append(f"  Spotify Followers:     {_fmt_number(artist_data['spotify_followers'])}")
    if social_stats.get("instagram_followers"):
        lines.append(f"  Instagram Followers:   {social_stats['instagram_followers']}")
    if social_stats.get("youtube_subscribers"):
        lines.append(f"  YouTube Subscribers:   {social_stats['youtube_subscribers']}")
    if social_stats.get("awards"):
        lines.append(f"  Awards/Achievements:")
        for a in social_stats["awards"][:8]:
            lines.append(f"    - {a}")
    return "\n".join(lines) if lines else "  No platform stats available."


def _build_research_block(research_items):
    """Format research items for the prompt, capped at 8000 chars total."""
    if not research_items:
        return None
    lines       = []
    total_chars = 0
    char_limit  = 8000

    for item in research_items:
        if total_chars >= char_limit:
            break
        content = item.get("full_text") or item.get("snippet") or ""
        if not content:
            continue
        content = content[:700]
        domain  = item.get("domain", "")
        title   = item.get("title", "")
        entry   = f"[{domain}] {title}\n{content}"
        lines.append(entry)
        total_chars += len(entry)

    return "\n\n---\n\n".join(lines) if lines else None


def generate_bio(artist_data, persona, research=None, social_stats=None):
    """
    Generate Staccato (key facts) and Legacy (prose) bios using Claude Sonnet.
    Returns {"staccato": str, "legacy": str} or None on failure.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    system_prompt = SYSTEM_PROMPT.format(
        persona_instruction=PERSONA_INSTRUCTIONS.get(persona, PERSONA_INSTRUCTIONS["statistician"])
    )

    # ── Discography ───────────────────────────────────────────────────────────
    if artist_data.get("albums"):
        albums_text = "\n".join(
            f"  - {a['name']} ({a.get('release_date','Unknown')}) [{a.get('album_type','single').upper()}]"
            for a in artist_data["albums"][:6]
        )
    else:
        albums_text = "  No catalog data available."

    genres_str = ", ".join(artist_data.get("genres", [])) or "Independent Artist"

    # ── Stats block ───────────────────────────────────────────────────────────
    stats_block    = _build_stats_block(artist_data, social_stats or {})
    research_block = _build_research_block(research)

    research_section = (
        f"\nPRESS & WEB RESEARCH (use only clearly verifiable facts):\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{research_block}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ) if research_block else "\nPRESS & WEB RESEARCH: None — use Spotify data only.\n"

    user_message = f"""Write an EPK bio for this artist using only the data below.

ARTIST DATA:
  Name:             {artist_data['name']}
  Genre(s):         {genres_str}
  Avg Tempo:        {f"{artist_data['avg_bpm']} BPM" if artist_data.get('avg_bpm') else 'N/A - omit'}
  Energy Profile:   {artist_data.get('energy_label','N/A') if artist_data.get('energy_label') not in ('N/A',None) else 'N/A - omit'}
  Sonic Mood:       {artist_data.get('valence_label','N/A') if artist_data.get('valence_label') not in ('N/A',None) else 'N/A - omit'}
  Release Momentum: {artist_data.get('momentum_proxy','Unknown')}
  Explicit Content: {'Yes' if artist_data.get('has_explicit') else 'No'}

PLATFORM STATS:
{stats_block}

DISCOGRAPHY:
{albums_text}
{research_section}"""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            temperature=0.1,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = message.content[0].text

        if "---LEGACY---" in response_text:
            parts    = response_text.split("---LEGACY---", 1)
            staccato = parts[0].strip()
            legacy   = parts[1].strip()
        else:
            staccato = f"• {artist_data['name']} — independent artist."
            legacy   = response_text

        return {"staccato": staccato, "legacy": legacy}

    except Exception as e:
        print(f"[Synthesizer Error] {e}")
        return None
