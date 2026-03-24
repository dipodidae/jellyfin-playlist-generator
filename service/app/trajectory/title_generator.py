"""
AI-powered playlist title generator.

Uses OpenAI gpt-4o-mini for creative, evocative playlist titles.
Sends the full tracklist with rich metadata so the title reflects
the actual music selected and the LLM can draw on its knowledge
of the artists, albums, and cultural context.
"""

import logging
import re
from collections import Counter
from typing import Any

import openai

from app.config import settings

logger = logging.getLogger(__name__)


def generate_playlist_title(
    prompt: str,
    tracks: list[dict[str, Any]] | None = None,
    arc_type: str | None = None,
    genre_hints: list[str] | None = None,
) -> str:
    """Generate a creative playlist title using OpenAI.

    Args:
        prompt: The original user prompt.
        tracks: List of dicts with keys: "artist", "title", "album", "year",
                "genres", "energy", "darkness", "tempo", "texture".
        arc_type: The trajectory arc type (e.g. "journey", "rise").
        genre_hints: Genre hints from intent parsing.

    Falls back to a simple title if OpenAI is not configured or fails.
    """
    if not settings.openai_api_key:
        logger.debug("OpenAI not configured, using fallback title")
        return _fallback_title(prompt)

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)

        context = _build_context(tracks, arc_type, genre_hints)
        user_content = f'User prompt: "{prompt}"'
        if context:
            user_content += f"\n\n{context}"

        def _call_api() -> str | None:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=30,
                temperature=0.7,
            )
            c = resp.choices[0].message.content
            return c.strip().strip('"\'') if c else None

        title = _call_api()
        if not title:
            return _fallback_title(prompt)

        if re.search(r'\b\w+ of \w+\b', title, re.IGNORECASE):
            logger.debug(f"Title '{title}' matched banned 'X of Y' pattern, retrying")
            retry = _call_api()
            if retry and not re.search(r'\b\w+ of \w+\b', retry, re.IGNORECASE):
                title = retry

        title = f"✦ {title}"
        logger.info(f"Generated title: {title}")
        return title

    except Exception as e:
        logger.warning(f"OpenAI title generation failed: {e}")
        return _fallback_title(prompt)


_SYSTEM_PROMPT = """\
You are a music curator who names playlists. You receive:
1. The user's original prompt describing what they wanted.
2. The full tracklist of the playlist that was generated, including artist, \
track title, album, year, genres, and sonic profile dimensions.
3. A statistical summary of the playlist's character.

Your job is to generate ONE short, descriptive playlist title (2-5 words) that \
tells the listener exactly what kind of music this is.

Build the title by combining, in order of priority:
1. Genre — what style of music is this? (e.g. Thrash, Doom, Darkwave, Industrial)
2. Mood or feel — what does it sound like? (e.g. Fast, Heavy, Dark, Raw, Slow)
3. Era — what decade is it from, if the tracks cluster in one? (e.g. 80s, 90s)

For concrete prompts (user already named genre/era/mood): reflect their own \
descriptors back in clean, natural word order.
For abstract prompts: derive genre, mood, and era from the tracklist data provided.

STRICT RULES — violations are not acceptable:
- NEVER use "X of Y" or "X of Z" constructions. Banned examples: \
"Throne of Shadows", "Echo of Rage", "Ruins of Dawn", "Edge of Chaos". \
These are lazy filler. Do not produce them.
- Do not use abstract filler words like: echoes, shadows, throne, lair, ritual, \
void, abyss, realm, forge, descent, ascent — unless the user's prompt \
explicitly contains them.
- Do not be poetic or metaphorical. Be direct and descriptive.
- No quotes, no word "playlist", no word "mix"
- Output ONLY the title, nothing else

Examples (prompt → correct title):
"pure evil 80s thrash" → Evil Thrash from the 80s
"dark and slow for 3am" → Late-Night Doom
"raw cold black metal" → Raw Cold Black Metal
"driving 90s industrial" → Hard 90s Industrial
"heavy goth with a building arc" → Heavy Building Goth
"fast and aggressive death metal" → Fast Aggressive Death Metal"""


def _build_context(
    tracks: list[dict[str, Any]] | None,
    arc_type: str | None,
    genre_hints: list[str] | None,
) -> str:
    """Build a rich context string for the LLM from track metadata."""
    parts: list[str] = []

    if not tracks:
        if genre_hints:
            parts.append(f"Target genres: {', '.join(genre_hints[:8])}")
        if arc_type and arc_type != "steady":
            parts.append(f"Energy arc: {arc_type}")
        return "\n\n".join(parts)

    # --- Per-track listing (up to 30) ---
    sample = tracks[:30]
    track_lines = []
    for i, t in enumerate(sample, 1):
        artist = t.get("artist", "Unknown")
        title = t.get("title", "")
        album = t.get("album", "")
        year = t.get("year")
        genres = t.get("genres", [])

        line = f"{i}. {artist} — {title}"
        if album:
            line += f" [{album}]"
        if year:
            line += f" ({year})"
        if genres:
            line += f"  #{', #'.join(genres[:4])}"

        # Compact sonic profile
        energy = t.get("energy")
        darkness = t.get("darkness")
        if energy is not None and darkness is not None:
            tempo = t.get("tempo", 0.5)
            texture = t.get("texture", 0.5)
            line += f"  | E:{energy:.1f} D:{darkness:.1f} T:{tempo:.1f} Tx:{texture:.1f}"

        track_lines.append(line)

    tracklist_str = "\n".join(track_lines)
    if len(tracks) > 30:
        tracklist_str += f"\n... and {len(tracks) - 30} more tracks"
    parts.append(f"Tracklist ({len(tracks)} tracks):\n{tracklist_str}")

    # --- Playlist summary statistics ---
    summary_lines = []

    # Dominant genres
    genre_counter: Counter[str] = Counter()
    for t in tracks:
        for g in t.get("genres", [])[:3]:
            genre_counter[g] += 1
    if genre_counter:
        top_genres = [g for g, _ in genre_counter.most_common(6)]
        summary_lines.append(f"Dominant genres: {', '.join(top_genres)}")

    # Era spread
    years = [t["year"] for t in tracks if t.get("year")]
    if years:
        decade_counter: Counter[str] = Counter()
        for y in years:
            decade_counter[f"{(y // 10) * 10}s"] += 1
        top_decades = [d for d, _ in decade_counter.most_common(3)]
        summary_lines.append(f"Era: {', '.join(top_decades)} (range {min(years)}-{max(years)})")

    # Average sonic profile
    profile_keys = ["energy", "darkness", "tempo", "texture"]
    avgs = {}
    for key in profile_keys:
        vals = [t[key] for t in tracks if t.get(key) is not None]
        if vals:
            avgs[key] = sum(vals) / len(vals)
    if avgs:
        profile_parts = [f"{k}={v:.2f}" for k, v in avgs.items()]
        summary_lines.append(f"Average sonic profile: {', '.join(profile_parts)}")

    # Artist diversity
    unique_artists = {t.get("artist", "") for t in tracks}
    summary_lines.append(f"Artists: {len(unique_artists)} unique across {len(tracks)} tracks")

    # Arc type
    if arc_type and arc_type != "steady":
        summary_lines.append(f"Energy arc: {arc_type}")

    if summary_lines:
        parts.append("Playlist character:\n" + "\n".join(summary_lines))

    return "\n\n".join(parts)


def _fallback_title(prompt: str) -> str:
    """Generate a simple fallback title from the prompt."""
    words = prompt.split()[:5]
    title = " ".join(words).title()

    if len(title) > 50:
        title = title[:47] + "..."

    return f"✦ {title}"
