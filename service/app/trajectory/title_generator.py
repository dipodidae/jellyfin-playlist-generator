"""
AI-powered playlist title and track explanation generator.

Uses OpenAI gpt-4o-mini for:
- Creative, evocative playlist titles
- Per-track explanations of why each track was selected
"""

import json
import logging
from typing import Any

import openai

from app.config import settings

logger = logging.getLogger(__name__)


def generate_playlist_title(
    prompt: str,
    track_artists: list[str] | None = None,
    arc_type: str | None = None,
    genre_hints: list[str] | None = None,
) -> str:
    """Generate a creative playlist title using OpenAI.

    Falls back to a simple title if OpenAI is not configured or fails.
    """
    if not settings.openai_api_key:
        logger.debug("OpenAI not configured, using fallback title")
        return _fallback_title(prompt)

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)

        # Build context about the tracks
        context_parts = []
        if track_artists:
            unique_artists = list(dict.fromkeys(track_artists))[:10]
            context_parts.append(f"Featuring artists like: {', '.join(unique_artists)}")
        if arc_type:
            context_parts.append(f"Energy arc: {arc_type}")
        if genre_hints:
            context_parts.append(f"Genres: {', '.join(genre_hints[:8])}")

        context = "\n".join(context_parts)
        user_content = f'Generate a playlist title for this vibe:\n\n"{prompt}"'
        if context:
            user_content += f"\n\n{context}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": """You are a creative playlist naming assistant. Generate short, evocative playlist titles that capture the mood and essence of the music.

Rules:
- Keep titles between 2-6 words
- Be creative and poetic, not literal
- Don't use generic words like "playlist", "mix", "collection"
- Capture the emotional essence, not just describe it
- Can use metaphors, imagery, or abstract concepts
- No quotes around the title
- Just output the title, nothing else"""
                },
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
            max_tokens=30,
            temperature=0.9,
        )

        content = response.choices[0].message.content
        if not content:
            return _fallback_title(prompt)

        title = content.strip().strip('"\'')

        logger.info(f"Generated title: {title}")
        return title

    except Exception as e:
        logger.warning(f"OpenAI title generation failed: {e}")
        return _fallback_title(prompt)


def _fallback_title(prompt: str) -> str:
    """Generate a simple fallback title from the prompt."""
    words = prompt.split()[:5]
    title = " ".join(words).title()

    if len(title) > 50:
        title = title[:47] + "..."

    return title


def generate_track_explanations(
    prompt: str,
    tracks: list[Any],
    arc_type: str = "journey",
    genre_hints: list[str] | None = None,
) -> dict[str, str]:
    """Generate LLM-powered explanations for each track in the playlist.

    Returns a dict mapping track ID (as string) to explanation text.
    Falls back to score-based explanations if OpenAI is unavailable.
    """
    if not settings.openai_api_key:
        logger.debug("OpenAI not configured, using score-based explanations")
        return _fallback_explanations(tracks, arc_type)

    if not tracks:
        return {}

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)

        # Build a compact track list for the LLM
        track_summaries = []
        for i, t in enumerate(tracks):
            summary = {
                "pos": i + 1,
                "id": str(t.id),
                "title": t.title,
                "artist": t.artist_name or "Unknown",
            }
            # Add score context (compact)
            if hasattr(t, "semantic_score"):
                summary["sem"] = round(t.semantic_score, 2)
            if hasattr(t, "trajectory_score"):
                summary["traj"] = round(t.trajectory_score, 2)
            if hasattr(t, "genre_match_score"):
                summary["genre"] = round(t.genre_match_score, 2)
            if hasattr(t, "energy"):
                summary["energy"] = round(t.energy, 2)
            if hasattr(t, "darkness"):
                summary["dark"] = round(t.darkness, 2)
            track_summaries.append(summary)

        user_content = json.dumps({
            "prompt": prompt,
            "arc_type": arc_type,
            "genres": genre_hints or [],
            "tracks": track_summaries,
        }, separators=(",", ":"))

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": _EXPLANATION_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=2000,
            temperature=0.4,
        )

        content = response.choices[0].message.content
        if not content:
            return _fallback_explanations(tracks, arc_type)

        result = json.loads(content.strip())

        # Extract explanations - expected format: {"explanations": {"id": "text", ...}}
        explanations = result.get("explanations", {})
        if not isinstance(explanations, dict):
            return _fallback_explanations(tracks, arc_type)

        # Ensure all track IDs are present
        for t in tracks:
            tid = str(t.id)
            if tid not in explanations:
                explanations[tid] = _single_fallback(t, arc_type)

        logger.info(f"Generated explanations for {len(explanations)} tracks")
        return explanations

    except json.JSONDecodeError as e:
        logger.warning(f"Track explanation returned invalid JSON: {e}")
        return _fallback_explanations(tracks, arc_type)
    except Exception as e:
        logger.warning(f"Track explanation generation failed: {e}")
        return _fallback_explanations(tracks, arc_type)


_EXPLANATION_SYSTEM_PROMPT = """\
You are a music curator explaining playlist track selections. Given a playlist prompt, \
arc type, and track list with scores, write a brief explanation for each track.

## Input
JSON with: prompt, arc_type, genres, and tracks (each with position, id, title, artist, \
and numeric scores: sem=semantic match, traj=trajectory fit, genre=genre overlap, \
energy, dark=darkness).

## Output
Return JSON: {"explanations": {"track_id": "explanation", ...}}

## Rules
- Each explanation: 1 sentence, 10-20 words
- Explain why this track fits at this playlist position
- Reference the track's role in the arc (opener, builds energy, peak moment, cooldown, closer)
- Mention genre/style relevance when appropriate
- Mention the artist's sonic character when it's well-known
- Be specific about how the track serves the playlist's narrative
- Use music terminology naturally (not forced)
- Do NOT mention scores or numbers
- Do NOT repeat the track title or artist name — the user can already see those"""


def _fallback_explanations(tracks: list[Any], arc_type: str) -> dict[str, str]:
    """Generate simple score-based explanations when LLM is unavailable."""
    result = {}
    for t in tracks:
        result[str(t.id)] = _single_fallback(t, arc_type)
    return result


def _single_fallback(track: Any, arc_type: str) -> str:
    """Generate a single fallback explanation for a track."""
    parts = []

    if hasattr(track, "semantic_score") and track.semantic_score > 0.7:
        parts.append("Strong semantic match")
    elif hasattr(track, "semantic_score") and track.semantic_score > 0.5:
        parts.append("Good semantic match")

    if hasattr(track, "trajectory_score") and track.trajectory_score > 0.7:
        parts.append("fits the trajectory well")
    elif hasattr(track, "trajectory_score") and track.trajectory_score > 0.5:
        parts.append("reasonable trajectory fit")

    if hasattr(track, "genre_match_score") and track.genre_match_score > 0.3:
        parts.append("genre overlap")

    if not parts:
        parts.append("Selected for overall playlist coherence")

    return ". ".join(parts) + "."
