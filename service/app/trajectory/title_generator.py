"""
AI-powered playlist title generator.

Generates creative, evocative titles based on the prompt and selected tracks.
"""

import logging
import openai

from app.config import settings

logger = logging.getLogger(__name__)


def generate_playlist_title(prompt: str, track_artists: list[str] | None = None) -> str:
    """Generate a creative playlist title using OpenAI.
    
    Falls back to a simple title if OpenAI is not configured or fails.
    """
    if not settings.openai_api_key:
        logger.debug("OpenAI not configured, using fallback title")
        return _fallback_title(prompt)
    
    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        
        # Build context about the tracks
        artist_context = ""
        if track_artists:
            unique_artists = list(dict.fromkeys(track_artists))[:10]  # Top 10 unique artists
            artist_context = f"\nFeaturing artists like: {', '.join(unique_artists)}"
        
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
                    "content": f"Generate a playlist title for this vibe:\n\n\"{prompt}\"{artist_context}"
                }
            ],
            max_tokens=30,
            temperature=0.9,
        )
        
        title = response.choices[0].message.content.strip()
        # Clean up any quotes that might have been added
        title = title.strip('"\'')
        
        logger.info(f"Generated title: {title}")
        return title
        
    except Exception as e:
        logger.warning(f"OpenAI title generation failed: {e}")
        return _fallback_title(prompt)


def _fallback_title(prompt: str) -> str:
    """Generate a simple fallback title from the prompt."""
    # Take first few words and capitalize
    words = prompt.split()[:5]
    title = " ".join(words).title()
    
    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."
    
    return title
