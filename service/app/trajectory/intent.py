"""
Intent extraction from natural language prompts.

Parses user prompts into structured intent objects that define:
- Mood/energy trajectory (arc shape)
- Genre/style preferences
- Temporal constraints
- Abstract concepts to interpret
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.embeddings.generator import generate_embedding

logger = logging.getLogger(__name__)


class ArcType(str, Enum):
    """Predefined trajectory arc shapes."""
    STEADY = "steady"           # Maintain consistent energy
    RISE = "rise"               # Build energy over time
    FALL = "fall"               # Wind down energy
    PEAK = "peak"               # Build to climax then resolve
    VALLEY = "valley"           # Start high, dip, return
    WAVE = "wave"               # Oscillating energy
    JOURNEY = "journey"         # Narrative arc with phases


@dataclass
class TrajectoryWaypoint:
    """A point along the playlist trajectory."""
    position: float  # 0.0 to 1.0 (start to end)
    energy: float    # 0.0 to 1.0
    mood_embedding: list[float] | None = None
    description: str = ""
    

@dataclass
class PlaylistIntent:
    """Structured representation of user's playlist intent."""
    raw_prompt: str
    prompt_embedding: list[float]
    
    # Core parameters
    arc_type: ArcType = ArcType.STEADY
    target_size: int = 20
    target_duration_minutes: int | None = None
    
    # Mood/style
    mood_keywords: list[str] = field(default_factory=list)
    genre_hints: list[str] = field(default_factory=list)
    artist_seeds: list[str] = field(default_factory=list)
    
    # Trajectory waypoints
    waypoints: list[TrajectoryWaypoint] = field(default_factory=list)
    
    # Constraints
    avoid_keywords: list[str] = field(default_factory=list)
    year_range: tuple[int | None, int | None] = (None, None)
    
    # Abstract concepts for semantic matching
    abstract_concepts: list[str] = field(default_factory=list)


# Keyword mappings for arc detection
ARC_KEYWORDS = {
    ArcType.RISE: ["build", "building", "crescendo", "energize", "pump up", "get hyped", "workout", "morning"],
    ArcType.FALL: ["wind down", "relax", "chill", "calm", "sleep", "evening", "unwind", "decompress"],
    ArcType.PEAK: ["party", "climax", "peak", "dance", "rave", "club"],
    ArcType.VALLEY: ["introspective", "contemplative", "meditation", "focus", "study"],
    ArcType.WAVE: ["varied", "mix", "eclectic", "journey", "adventure"],
    ArcType.JOURNEY: ["story", "narrative", "epic", "soundtrack", "cinematic"],
}

# Energy level keywords
ENERGY_KEYWORDS = {
    "high": ["energetic", "intense", "powerful", "aggressive", "fast", "heavy", "loud", "upbeat", "driving"],
    "medium": ["moderate", "balanced", "steady", "groovy", "rhythmic"],
    "low": ["calm", "quiet", "soft", "gentle", "peaceful", "ambient", "slow", "minimal"],
}

# Common genre aliases
GENRE_ALIASES = {
    "metal": ["metal", "heavy metal", "death metal", "black metal", "thrash", "doom"],
    "electronic": ["electronic", "techno", "house", "ambient", "idm", "synth"],
    "rock": ["rock", "alternative", "indie", "punk", "grunge"],
    "jazz": ["jazz", "bebop", "fusion", "smooth jazz"],
    "classical": ["classical", "orchestral", "symphony", "chamber"],
    "hip-hop": ["hip-hop", "rap", "trap", "boom bap"],
    "folk": ["folk", "acoustic", "singer-songwriter", "americana"],
}


def detect_arc_type(prompt: str) -> ArcType:
    """Detect the trajectory arc type from prompt keywords."""
    prompt_lower = prompt.lower()
    
    for arc_type, keywords in ARC_KEYWORDS.items():
        for keyword in keywords:
            if keyword in prompt_lower:
                return arc_type
    
    return ArcType.STEADY


def extract_mood_keywords(prompt: str) -> list[str]:
    """Extract mood-related keywords from the prompt."""
    moods = []
    prompt_lower = prompt.lower()
    
    # Check energy keywords
    for level, keywords in ENERGY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in prompt_lower:
                moods.append(keyword)
    
    # Common mood words
    mood_words = [
        "dark", "bright", "melancholic", "happy", "sad", "angry", "peaceful",
        "mysterious", "ethereal", "dreamy", "nostalgic", "epic", "intimate",
        "raw", "polished", "experimental", "traditional", "modern", "vintage",
        "atmospheric", "hypnotic", "chaotic", "serene", "triumphant", "haunting"
    ]
    
    for word in mood_words:
        if word in prompt_lower:
            moods.append(word)
    
    return list(set(moods))


def extract_genre_hints(prompt: str) -> list[str]:
    """Extract genre hints from the prompt."""
    genres = []
    prompt_lower = prompt.lower()
    
    for genre_family, aliases in GENRE_ALIASES.items():
        for alias in aliases:
            if alias in prompt_lower:
                genres.append(alias)
    
    return list(set(genres))


def extract_artist_seeds(prompt: str) -> list[str]:
    """Extract artist names mentioned in the prompt."""
    # Look for patterns like "like [Artist]" or "similar to [Artist]"
    patterns = [
        r"like\s+([A-Z][a-zA-Z\s]+?)(?:\s+and|\s+or|,|$)",
        r"similar to\s+([A-Z][a-zA-Z\s]+?)(?:\s+and|\s+or|,|$)",
        r"in the style of\s+([A-Z][a-zA-Z\s]+?)(?:\s+and|\s+or|,|$)",
    ]
    
    artists = []
    for pattern in patterns:
        matches = re.findall(pattern, prompt)
        artists.extend([m.strip() for m in matches])
    
    return list(set(artists))


def extract_year_range(prompt: str) -> tuple[int | None, int | None]:
    """Extract year constraints from the prompt."""
    prompt_lower = prompt.lower()
    
    # Decade patterns
    decade_match = re.search(r"(\d{2})s|(\d{4})s", prompt_lower)
    if decade_match:
        if decade_match.group(1):
            decade = int(decade_match.group(1))
            if decade < 30:
                decade += 2000
            else:
                decade += 1900
        else:
            decade = int(decade_match.group(2))
        return (decade, decade + 9)
    
    # Year range patterns
    range_match = re.search(r"(\d{4})\s*[-–to]+\s*(\d{4})", prompt_lower)
    if range_match:
        return (int(range_match.group(1)), int(range_match.group(2)))
    
    # Single year
    year_match = re.search(r"from\s+(\d{4})|in\s+(\d{4})", prompt_lower)
    if year_match:
        year = int(year_match.group(1) or year_match.group(2))
        return (year, year)
    
    return (None, None)


def extract_abstract_concepts(prompt: str) -> list[str]:
    """Extract abstract concepts that need semantic interpretation."""
    # These are phrases that can't be matched literally but need embedding similarity
    concepts = []
    
    # The whole prompt is an abstract concept
    concepts.append(prompt)
    
    # Also extract quoted phrases as specific concepts
    quoted = re.findall(r'"([^"]+)"', prompt)
    concepts.extend(quoted)
    
    # Extract "for X" patterns (e.g., "for a rainy day", "for working out")
    for_patterns = re.findall(r"for\s+(?:a\s+)?([^,\.]+?)(?:,|\.|$)", prompt.lower())
    concepts.extend([p.strip() for p in for_patterns if len(p.strip()) > 3])
    
    return list(set(concepts))


def generate_waypoints(arc_type: ArcType, num_waypoints: int = 5) -> list[TrajectoryWaypoint]:
    """Generate trajectory waypoints based on arc type."""
    waypoints = []
    
    # Energy curves for different arc types
    energy_curves = {
        ArcType.STEADY: lambda x: 0.5,
        ArcType.RISE: lambda x: 0.2 + 0.6 * x,
        ArcType.FALL: lambda x: 0.8 - 0.6 * x,
        ArcType.PEAK: lambda x: 0.3 + 0.7 * (1 - abs(2 * x - 1)),
        ArcType.VALLEY: lambda x: 0.7 - 0.4 * (1 - abs(2 * x - 1)),
        ArcType.WAVE: lambda x: 0.5 + 0.3 * __import__('math').sin(x * 3.14159 * 2),
        ArcType.JOURNEY: lambda x: 0.4 + 0.2 * x + 0.3 * (1 - abs(2 * x - 0.7)) if x < 0.85 else 0.3,
    }
    
    curve = energy_curves.get(arc_type, energy_curves[ArcType.STEADY])
    
    for i in range(num_waypoints):
        position = i / (num_waypoints - 1) if num_waypoints > 1 else 0.5
        energy = max(0.0, min(1.0, curve(position)))
        waypoints.append(TrajectoryWaypoint(position=position, energy=energy))
    
    return waypoints


def parse_prompt(prompt: str, target_size: int = 20) -> PlaylistIntent:
    """Parse a natural language prompt into a structured PlaylistIntent."""
    logger.info(f"Parsing prompt: {prompt[:100]}...")
    
    # Generate embedding for the full prompt
    prompt_embedding = generate_embedding(prompt)
    
    # Extract components
    arc_type = detect_arc_type(prompt)
    mood_keywords = extract_mood_keywords(prompt)
    genre_hints = extract_genre_hints(prompt)
    artist_seeds = extract_artist_seeds(prompt)
    year_range = extract_year_range(prompt)
    abstract_concepts = extract_abstract_concepts(prompt)
    
    # Generate waypoints
    waypoints = generate_waypoints(arc_type)
    
    # Enrich waypoints with mood embeddings
    for i, wp in enumerate(waypoints):
        # Create a description for this phase
        phase_descriptions = {
            0: f"opening: {prompt}",
            len(waypoints) - 1: f"closing: {prompt}",
        }
        wp.description = phase_descriptions.get(i, f"middle phase: {prompt}")
        wp.mood_embedding = generate_embedding(wp.description)
    
    intent = PlaylistIntent(
        raw_prompt=prompt,
        prompt_embedding=prompt_embedding,
        arc_type=arc_type,
        target_size=target_size,
        mood_keywords=mood_keywords,
        genre_hints=genre_hints,
        artist_seeds=artist_seeds,
        waypoints=waypoints,
        year_range=year_range,
        abstract_concepts=abstract_concepts,
    )
    
    logger.info(f"Parsed intent: arc={arc_type}, moods={mood_keywords}, genres={genre_hints}")
    return intent
