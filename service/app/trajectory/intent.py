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
from app.trajectory.curves import TrajectoryCurve, TrajectoryPoint, generate_trajectory_curve

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
    """A point along the playlist trajectory (4D)."""
    position: float  # 0.0 to 1.0 (start to end)
    energy: float    # 0.0 to 1.0
    tempo: float = 0.5
    darkness: float = 0.5
    texture: float = 0.5
    phase_label: str = ""  # intro/build/peak/resolve
    mood_embedding: list[float] | None = None
    description: str = ""


@dataclass
class DimensionWeights:
    """Weights for trajectory dimensions derived from prompt."""
    energy: float = 0.25
    tempo: float = 0.25
    darkness: float = 0.25
    texture: float = 0.25

    def normalize(self) -> "DimensionWeights":
        """Normalize weights to sum to 1, with min/max clamping."""
        total = self.energy + self.tempo + self.darkness + self.texture
        if total == 0:
            return DimensionWeights()

        # Normalize
        e = self.energy / total
        t = self.tempo / total
        d = self.darkness / total
        x = self.texture / total

        # Clamp to [0.15, 0.45]
        e = max(0.15, min(0.45, e))
        t = max(0.15, min(0.45, t))
        d = max(0.15, min(0.45, d))
        x = max(0.15, min(0.45, x))

        # Re-normalize after clamping
        total = e + t + d + x
        return DimensionWeights(
            energy=e / total,
            tempo=t / total,
            darkness=d / total,
            texture=x / total,
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "energy": self.energy,
            "tempo": self.tempo,
            "darkness": self.darkness,
            "texture": self.texture,
        }


@dataclass
class PlaylistIntent:
    """Structured representation of user's playlist intent."""
    raw_prompt: str
    prompt_embedding: list[float]

    # Core parameters
    arc_type: ArcType = ArcType.STEADY
    arc_confidence: float = 0.5  # Confidence in arc detection [0, 1]
    target_size: int = 20
    target_duration_minutes: int | None = None

    # Mood/style
    mood_keywords: list[str] = field(default_factory=list)
    genre_hints: list[str] = field(default_factory=list)
    artist_seeds: list[str] = field(default_factory=list)

    # Trajectory (4D curve)
    trajectory_curve: TrajectoryCurve | None = None
    waypoints: list[TrajectoryWaypoint] = field(default_factory=list)  # Sampled from curve
    dimension_weights: DimensionWeights = field(default_factory=DimensionWeights)

    # Base dimension values (from prompt analysis)
    base_energy: float = 0.5
    base_darkness: float = 0.5
    base_tempo: float = 0.5
    base_texture: float = 0.5

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


def detect_arc_type(
    prompt: str,
    genre_hints: list[str] | None = None,
) -> tuple[ArcType, float]:
    """Detect the trajectory arc type from prompt keywords.

    When no arc keywords match but genre hints are present and the prompt is
    short (< 6 words), defaults to JOURNEY instead of STEADY.  This gives
    genre-only prompts (e.g. "true evil 80s thrash") a wider candidate gravity
    (0.3) rather than the maximum-tightness steady-state tunnel (0.8).

    Returns:
        Tuple of (arc_type, confidence) where confidence is [0, 1]
    """
    prompt_lower = prompt.lower()

    # Count matches per arc type
    arc_scores: dict[ArcType, int] = {}

    for arc_type, keywords in ARC_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword in prompt_lower:
                score += 1
        if score > 0:
            arc_scores[arc_type] = score

    if not arc_scores:
        # Fallback: if genre hints are present and prompt is short, explore
        if genre_hints and len(prompt.split()) < 6:
            return ArcType.JOURNEY, 0.5
        return ArcType.STEADY, 0.3  # Low confidence default

    # Find best match
    best_arc = max(arc_scores, key=arc_scores.get)
    best_score = arc_scores[best_arc]

    # Check for conflicting signals
    total_matches = sum(arc_scores.values())
    if total_matches > best_score:
        # Multiple arc types detected - lower confidence
        confidence = 0.5 + 0.3 * (best_score / total_matches)
    else:
        # Single clear match
        confidence = 0.7 + 0.1 * min(best_score, 3)  # Cap at 1.0

    return best_arc, min(1.0, confidence)


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


def extract_dimension_weights(prompt: str, mood_keywords: list[str]) -> DimensionWeights:
    """Extract dimension weights from prompt analysis.

    Emphasizes dimensions that are most relevant to the prompt.
    """
    prompt_lower = prompt.lower()
    all_keywords = mood_keywords + prompt_lower.split()

    # Keywords that emphasize each dimension
    energy_emphasis = ["energetic", "intense", "powerful", "calm", "relaxing", "chill",
                       "workout", "party", "sleep", "focus", "driving"]
    tempo_emphasis = ["fast", "slow", "upbeat", "downtempo", "quick", "leisurely",
                      "racing", "plodding", "brisk"]
    darkness_emphasis = ["dark", "bright", "light", "gloomy", "cheerful", "melancholic",
                         "depressing", "uplifting", "sinister", "evil", "happy"]
    texture_emphasis = ["dense", "sparse", "complex", "simple", "layered", "minimal",
                        "busy", "atmospheric", "thick", "thin", "heavy", "light"]

    # Count matches
    energy_count = sum(1 for kw in energy_emphasis if kw in prompt_lower)
    tempo_count = sum(1 for kw in tempo_emphasis if kw in prompt_lower)
    darkness_count = sum(1 for kw in darkness_emphasis if kw in prompt_lower)
    texture_count = sum(1 for kw in texture_emphasis if kw in prompt_lower)

    # Base weights + emphasis
    weights = DimensionWeights(
        energy=0.25 + energy_count * 0.1,
        tempo=0.25 + tempo_count * 0.1,
        darkness=0.25 + darkness_count * 0.1,
        texture=0.25 + texture_count * 0.1,
    )

    return weights.normalize()


def extract_base_dimensions(mood_keywords: list[str], genre_hints: list[str]) -> dict[str, float]:
    """Extract base dimension values from mood and genre keywords."""
    from app.profiles.generator import ENERGY_KEYWORDS, DARKNESS_KEYWORDS, TEMPO_KEYWORDS, TEXTURE_KEYWORDS

    all_tags = mood_keywords + genre_hints

    if not all_tags:
        return {"energy": 0.5, "darkness": 0.5, "tempo": 0.5, "texture": 0.5}

    # Score each dimension
    def score_dim(keyword_map: dict[str, float]) -> float:
        scores = []
        for tag in all_tags:
            tag_lower = tag.lower()
            if tag_lower in keyword_map:
                scores.append(keyword_map[tag_lower])
            else:
                # Partial match
                for kw, val in keyword_map.items():
                    if kw in tag_lower or tag_lower in kw:
                        scores.append(val)
                        break
        return sum(scores) / len(scores) if scores else 0.5

    return {
        "energy": score_dim(ENERGY_KEYWORDS),
        "darkness": score_dim(DARKNESS_KEYWORDS),
        "tempo": score_dim(TEMPO_KEYWORDS),
        "texture": score_dim(TEXTURE_KEYWORDS),
    }


def generate_waypoints_from_curve(
    curve: TrajectoryCurve,
    num_waypoints: int = 5,
) -> list[TrajectoryWaypoint]:
    """Generate trajectory waypoints by sampling the curve."""
    points = curve.sample(num_waypoints)

    return [
        TrajectoryWaypoint(
            position=p.position,
            energy=p.energy,
            tempo=p.tempo,
            darkness=p.darkness,
            texture=p.texture,
            phase_label=p.phase_label,
        )
        for p in points
    ]


def generate_waypoints(arc_type: ArcType, num_waypoints: int = 5) -> list[TrajectoryWaypoint]:
    """Generate trajectory waypoints based on arc type (legacy compatibility)."""
    curve = generate_trajectory_curve(arc_type.value, num_waypoints)
    return generate_waypoints_from_curve(curve, num_waypoints)


def parse_prompt(prompt: str, target_size: int = 20) -> PlaylistIntent:
    """Parse a natural language prompt into a structured PlaylistIntent."""
    logger.info(f"Parsing prompt: {prompt[:100]}...")

    # Generate embedding for the full prompt
    prompt_embedding = generate_embedding(prompt)

    # Extract genre hints first so they can inform arc detection
    genre_hints = extract_genre_hints(prompt)

    # Extract remaining components
    arc_type, arc_confidence = detect_arc_type(prompt, genre_hints=genre_hints)
    mood_keywords = extract_mood_keywords(prompt)
    artist_seeds = extract_artist_seeds(prompt)
    year_range = extract_year_range(prompt)
    abstract_concepts = extract_abstract_concepts(prompt)

    # Extract dimension weights and base values
    dimension_weights = extract_dimension_weights(prompt, mood_keywords)
    base_dims = extract_base_dimensions(mood_keywords, genre_hints)

    # Generate 4D trajectory curve
    trajectory_curve = generate_trajectory_curve(
        arc_type=arc_type.value,
        playlist_length=target_size,
        base_energy=base_dims["energy"],
        base_darkness=base_dims["darkness"],
        base_tempo=base_dims["tempo"],
        base_texture=base_dims["texture"],
    )

    # Sample waypoints from curve
    num_waypoints = min(target_size, 10)  # Cap at 10 waypoints
    waypoints = generate_waypoints_from_curve(trajectory_curve, num_waypoints)

    # Enrich waypoints with mood embeddings
    for i, wp in enumerate(waypoints):
        phase_descriptions = {
            0: f"opening: {prompt}",
            len(waypoints) - 1: f"closing: {prompt}",
        }
        wp.description = phase_descriptions.get(i, f"{wp.phase_label} phase: {prompt}")
        wp.mood_embedding = generate_embedding(wp.description)

    intent = PlaylistIntent(
        raw_prompt=prompt,
        prompt_embedding=prompt_embedding,
        arc_type=arc_type,
        arc_confidence=arc_confidence,
        target_size=target_size,
        mood_keywords=mood_keywords,
        genre_hints=genre_hints,
        artist_seeds=artist_seeds,
        trajectory_curve=trajectory_curve,
        waypoints=waypoints,
        dimension_weights=dimension_weights,
        base_energy=base_dims["energy"],
        base_darkness=base_dims["darkness"],
        base_tempo=base_dims["tempo"],
        base_texture=base_dims["texture"],
        year_range=year_range,
        abstract_concepts=abstract_concepts,
    )

    logger.info(f"Parsed intent: arc={arc_type} (conf={arc_confidence:.2f}), "
                f"moods={mood_keywords}, genres={genre_hints}, "
                f"weights={dimension_weights.as_dict()}")
    return intent
