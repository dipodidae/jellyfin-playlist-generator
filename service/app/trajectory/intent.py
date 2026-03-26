"""
Intent extraction from natural language prompts.

Parses user prompts into structured intent objects that define:
- Mood/energy trajectory (arc shape)
- Genre/style preferences
- Temporal constraints
- Abstract concepts to interpret
- Prompt type classification (genre-focused vs arc-focused vs mixed)

Supports LLM-powered parsing (gpt-4o-mini) with fallback to keyword-based parsing.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import openai

from app.config import settings
from app.embeddings.generator import generate_embedding
from app.trajectory.curves import TrajectoryCurve, TrajectoryPoint, generate_trajectory_curve

logger = logging.getLogger(__name__)


class PromptType(str, Enum):
    """Classification of prompt intent for adaptive scoring."""
    GENRE = "genre"      # Genre/style-focused (e.g. "coldwave", "thrash metal")
    ARC = "arc"          # Arc/mood-focused (e.g. "wind down for sleep")
    MIXED = "mixed"      # Both genre + arc signals (e.g. "build from doom to thrash")


class GenreMode(str, Enum):
    """Controls how strictly genre identity is enforced during generation."""
    STRICT = "strict"           # Hard filter: only tracks with strong target-genre probability
    BALANCED = "balanced"       # Soft weighting: target genres preferred, adjacent allowed
    EXPLORATORY = "exploratory" # Light pull toward target genre; open to adjacent styles


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
    """A point along the playlist trajectory (5D)."""
    position: float  # 0.0 to 1.0 (start to end)
    energy: float    # 0.0 to 1.0
    tempo: float = 0.5
    darkness: float = 0.5
    texture: float = 0.5
    era: float = 0.5  # normalized temporal position (0=earliest, 1=latest)
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
    era: float = 0.0  # default zero — no temporal preference unless detected

    def normalize(self) -> "DimensionWeights":
        """Normalize weights to sum to 1, with min/max clamping."""
        total = self.energy + self.tempo + self.darkness + self.texture + self.era
        if total == 0:
            return DimensionWeights()

        # Normalize
        e = self.energy / total
        t = self.tempo / total
        d = self.darkness / total
        x = self.texture / total
        er = self.era / total

        # Clamp core dims to [0.10, 0.45], era to [0.0, 0.20]
        e = max(0.10, min(0.45, e))
        t = max(0.10, min(0.45, t))
        d = max(0.10, min(0.45, d))
        x = max(0.10, min(0.45, x))
        er = max(0.0, min(0.20, er))

        # Re-normalize after clamping
        total = e + t + d + x + er
        return DimensionWeights(
            energy=e / total,
            tempo=t / total,
            darkness=d / total,
            texture=x / total,
            era=er / total,
        )

    def as_dict(self) -> dict[str, float]:
        d = {
            "energy": self.energy,
            "tempo": self.tempo,
            "darkness": self.darkness,
            "texture": self.texture,
        }
        if self.era > 0:
            d["era"] = self.era
        return d


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
    impact_preference: float = 0.0

    # Prompt type classification (for adaptive scoring)
    prompt_type: PromptType = PromptType.MIXED

    # Mood/style
    mood_keywords: list[str] = field(default_factory=list)
    genre_hints: list[str] = field(default_factory=list)
    genre_hints_primary: set[str] = field(default_factory=set)  # pre-expansion hints (lowercased)
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

    # Temporal trajectory (era dimension)
    era_mode: str = "none"  # none, chronological, reverse, locked, arc

    # Abstract concepts for semantic matching
    abstract_concepts: list[str] = field(default_factory=list)

    # Genre Manifold System
    genre_mode: GenreMode = GenreMode.BALANCED
    genre_centroids: dict[str, list[float]] = field(default_factory=dict)


_GENRE_MODE_STRICT_SIGNALS = [
    "only", "strictly", "pure", "nothing but", "exclusively", "just",
]
_GENRE_MODE_EXPLORATORY_SIGNALS = [
    "adjacent", "explore", "venture", "discover", "similar", "journey",
    "blend", "mix of", "crossover", "influences",
]


def detect_genre_mode(prompt: str, genre_hints: list[str], arc_type: ArcType) -> GenreMode:
    """Classify how strictly to enforce genre identity.

    STRICT:      User is asking for a tightly scoped genre ("only thrash", short genre-only).
    EXPLORATORY: User wants adjacent/cross-genre exploration or has explicit journey arc.
    BALANCED:    Default for most prompts.
    """
    p = prompt.lower()

    if any(sig in p for sig in _GENRE_MODE_STRICT_SIGNALS) and genre_hints:
        return GenreMode.STRICT

    # Short, genre-only prompt with no arc signals → likely strict
    words = prompt.split()
    if genre_hints and len(words) <= 4 and arc_type == ArcType.STEADY:
        return GenreMode.STRICT

    if any(sig in p for sig in _GENRE_MODE_EXPLORATORY_SIGNALS):
        return GenreMode.EXPLORATORY

    if arc_type in (ArcType.JOURNEY, ArcType.WAVE):
        return GenreMode.EXPLORATORY

    return GenreMode.BALANCED


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

# ---------------------------------------------------------------------------
# Comprehensive genre taxonomy built from actual library data (400 genres +
# 2 296 Last.fm artist tags).  Every alias is stored **lowercase**.
#
# The dict maps canonical genre family → list of aliases that a user might
# type in a prompt.  `extract_genre_hints()` walks this to recognise genres.
# ---------------------------------------------------------------------------
GENRE_ALIASES: dict[str, list[str]] = {
    # --- Metal super-families ------------------------------------------
    "black metal": [
        "black metal", "atmospheric black metal", "depressive black metal",
        "raw black metal", "melodic black metal", "symphonic black metal",
        "avant-garde black metal", "pagan black metal", "post-black metal",
        "blackgaze", "dsbm", "nsbm", "ambient black metal",
        "progressive folk black metal", "folk black metal",
        "crust black metal", "industrial black metal", "blackened",
        "svartmetall", "bestial black metal", "black 'n' roll",
    ],
    "death metal": [
        "death metal", "melodic death metal", "technical death metal",
        "brutal death metal", "old school death metal", "death-doom metal",
        "blackened death metal", "deathgrind", "experimental death metal",
        "death thrash", "progressive death metal", "slam",
    ],
    "thrash metal": [
        "thrash metal", "thrash", "crossover thrash", "bay area thrash",
        "teutonic thrash", "blackened thrash", "blackened thrash metal",
        "technical thrash metal", "technical thrash", "progressive thrash metal",
        "speed thrash metal", "black thrash metal", "power thrash metal",
        "avantgarde thrash metal", "speed thrash",
    ],
    "doom metal": [
        "doom metal", "doom", "funeral doom metal", "funeral doom",
        "traditional doom metal", "trad doom metal", "epic doom metal",
        "death-doom metal", "doom death metal", "stoner doom metal",
        "sludge metal", "sludge", "drone metal", "blackened doom metal",
    ],
    "heavy metal": [
        "heavy metal", "classic heavy metal",
        "epic heavy metal", "traditional heavy metal",
    ],
    "nwobhm": [
        "nwobhm", "new wave of british heavy metal",
    ],
    "speed metal": [
        "speed metal",
    ],
    "power metal": [
        "power metal", "symphonic metal", "operatic metal",
        "operatic symphonic metal", "symphonic power metal",
    ],
    "progressive metal": [
        "progressive metal", "prog metal",
    ],
    "glam metal": [
        "glam metal", "hair metal",
    ],
    "aor": [
        "aor", "arena rock", "melodic rock", "melodic hard rock",
        "adult oriented rock",
    ],
    "grindcore": [
        "grindcore", "deathgrind", "goregrind", "powerviolence",
        "noisecore", "grind",
    ],
    "industrial metal": [
        "industrial metal", "industrial rock", "industrial gothic metal",
        "electronic industrial metal", "nu metal",
    ],
    "metalcore": [
        "metalcore", "deathcore", "mathcore", "post-hardcore", "screamo",
    ],
    "groove metal": [
        "groove metal",
    ],
    "viking metal": [
        "viking metal", "viking", "pagan metal",
    ],
    "gothic metal": [
        "gothic metal", "gothic", "goth metal",
    ],
    "folk metal": [
        "folk metal",
    ],
    "avant-garde metal": [
        "avant-garde metal", "avantgarde", "avant-garde",
    ],

    # --- Rock families -------------------------------------------------
    "rock": [
        "rock", "classic rock", "hard rock", "blues rock", "psychedelic rock",
        "acid rock", "garage rock", "stoner rock", "southern rock",
        "progressive rock", "art rock", "krautrock", "space rock",
        "psychedelic space rock", "boogie rock", "arena rock",
        "alternative rock", "indie rock", "noise rock", "experimental rock",
        "heavy psych", "occult rock",
    ],
    "punk": [
        "punk", "punk rock", "hardcore punk", "d-beat", "crust punk",
        "crust", "oi", "proto-punk", "post-punk", "art punk",
        "dance-punk", "pop punk", "metal punk",
    ],
    "post-punk": [
        "post-punk", "gothic rock", "goth", "deathrock", "batcave",
    ],
    "grunge": [
        "grunge",
    ],
    "shoegaze": [
        "shoegaze", "dream pop", "blackgaze",
    ],
    "post-rock": [
        "post-rock",
    ],

    # --- Electronic families -------------------------------------------
    "electronic": [
        "electronic", "electro", "electronica",
    ],
    "industrial": [
        "industrial", "ebm", "dark electro", "power electronics",
        "rhythmic noise", "death industrial", "martial industrial",
        "futurepop", "electro-industrial", "industrial techno",
    ],
    "synth-pop": [
        "synth-pop", "synthpop", "synth pop", "electropop",
        "minimal synth", "minimal wave",
    ],
    "coldwave": [
        "coldwave", "cold wave", "minimal wave", "minimal synth",
    ],
    "darkwave": [
        "darkwave", "dark wave", "ethereal", "ethereal wave",
        "neoclassical darkwave",
    ],
    "new wave": [
        "new wave", "neue deutsche welle", "ndw", "no wave",
    ],
    "techno": [
        "techno", "acid house", "house", "acid techno",
        "industrial techno",
    ],
    "ambient": [
        "ambient", "dark ambient", "space ambient", "ritual ambient",
        "drone", "dungeon synth", "winter synth", "berlin school",
    ],
    "synthwave": [
        "synthwave", "retrowave",
    ],
    "trance": [
        "trance",
    ],
    "downtempo": [
        "downtempo", "trip hop", "trip-hop", "chillout", "lo-fi",
        "leftfield",
    ],
    "drum and bass": [
        "drum and bass", "drum n bass", "breakcore",
    ],
    "disco": [
        "disco", "alternative dance", "dance", "dance-rock",
    ],

    # --- Hip-hop -------------------------------------------------------
    "hip-hop": [
        "hip-hop", "hip hop", "rap", "boom bap", "gangsta rap",
        "east coast hip hop", "southern hip hop", "hardcore hip hop",
        "conscious hip hop", "jazz rap", "pop rap", "trap",
        "horrorcore",
    ],

    # --- Jazz ----------------------------------------------------------
    "jazz": [
        "jazz", "free jazz", "avant-garde jazz", "jazz fusion",
        "hard bop", "contemporary jazz", "dark jazz",
        "post-bop", "big band", "swing",
    ],

    # --- Classical & orchestral ----------------------------------------
    "classical": [
        "classical", "modern classical", "neoclassical",
        "orchestral", "chamber", "symphony",
    ],

    # --- Folk & acoustic -----------------------------------------------
    "folk": [
        "folk", "folk rock", "neofolk", "dark folk",
        "apocalyptic folk", "singer-songwriter", "acoustic",
        "americana", "celtic",
    ],
    "neofolk": [
        "neofolk", "dark folk", "apocalyptic folk", "martial",
    ],

    # --- Noise & experimental ------------------------------------------
    "noise": [
        "noise", "harsh noise", "noise rock", "power electronics",
        "musique concrete", "glitch", "illbient",
    ],
    "experimental": [
        "experimental", "avant-garde", "avantgarde",
    ],

    # --- Blues, soul, funk, reggae, world -------------------------------
    "blues": [
        "blues", "blues rock", "british blues",
    ],
    "pop": [
        "pop", "pop rock", "art pop", "indie pop", "psychedelic pop",
    ],
    "reggae": [
        "reggae", "dub",
    ],
    "funk": [
        "funk", "soul",
    ],
    "spoken word": [
        "spoken word",
    ],
}

# Build a fast reverse-lookup: normalised alias → canonical family.
_ALIAS_TO_FAMILY: dict[str, str] = {}
for _fam, _aliases in GENRE_ALIASES.items():
    for _a in _aliases:
        _ALIAS_TO_FAMILY[_a.lower()] = _fam


# Related genre families — bidirectional sibling relationships.
# When a genre hint maps to one of these families, the related families'
# primary aliases are added to the hint set (for Jaccard scoring and pool queries).
_RELATED_FAMILIES: dict[str, list[str]] = {
    "coldwave": ["darkwave", "post-punk", "synth-pop", "new wave"],
    "darkwave": ["coldwave", "post-punk", "synth-pop"],
    "post-punk": ["darkwave", "new wave", "gothic rock"],
    "synth-pop": ["darkwave", "new wave", "coldwave"],
    "new wave": ["post-punk", "synth-pop"],
    "gothic rock": ["post-punk", "darkwave"],
    "thrash metal": ["speed metal", "heavy metal"],
    "speed metal": ["thrash metal", "heavy metal", "power metal"],
    "heavy metal": ["nwobhm", "speed metal"],
    "nwobhm": ["heavy metal", "speed metal"],
    "power metal": ["heavy metal", "speed metal", "progressive metal"],
    "progressive metal": ["power metal", "heavy metal"],
    "glam metal": ["aor", "hard rock"],
    "aor": ["glam metal"],
    "black metal": ["death metal"],
    "death metal": ["black metal", "thrash metal"],
    "doom metal": ["heavy metal"],
    "shoegaze": ["dream pop", "post-rock"],
    "industrial": ["ebm", "industrial metal"],
    "industrial metal": ["industrial"],
    "grunge": ["alternative rock"],
    "progressive rock": ["art rock", "krautrock"],
    "punk": ["hardcore"],
    "hardcore": ["punk"],
}


# Broad umbrella genres that should never be added via expansion and should
# be discounted when scoring.  These match huge portions of the library and
# dilute the specificity of a subgenre prompt.
_BROAD_GENRES: set[str] = {
    "rock", "pop", "metal", "electronic", "punk",
    "classic rock", "hard rock", "alternative rock",
}


def expand_genre_hints(genre_hints: list[str]) -> list[str]:
    """Expand genre hints with closely related sibling genres.

    Uses the _ALIAS_TO_FAMILY lookup and _RELATED_FAMILIES mapping to add
    related genre families' primary names.  This ensures the Jaccard scoring
    and genre pool queries cast a wider net for niche genres that have small
    pools (e.g. coldwave → also pulls in darkwave, post-punk tracks).

    The original hints are always preserved first, followed by expansions,
    deduplicated in order.  Broad umbrella genres (rock, pop, metal, etc.)
    are **never** added via expansion — they must come from the user's prompt
    directly.
    """
    if not genre_hints:
        return genre_hints

    expanded: list[str] = list(genre_hints)  # preserve originals first
    seen = {h.lower() for h in genre_hints}

    for hint in genre_hints:
        # Resolve to canonical family
        family = _ALIAS_TO_FAMILY.get(hint.lower(), hint.lower())
        related = _RELATED_FAMILIES.get(family, [])
        for rel_family in related:
            if rel_family not in seen and rel_family not in _BROAD_GENRES:
                seen.add(rel_family)
                expanded.append(rel_family)

    return expanded


def get_primary_genre_hints(genre_hints: list[str]) -> set[str]:
    """Return the set of primary (non-expanded) genre hints, lowercased.

    These are the hints that came directly from the prompt / LLM, before
    expansion.  Used for tiered genre scoring: primary matches get full
    weight, expanded matches get partial weight.
    """
    if not genre_hints:
        return set()

    primary: set[str] = set()
    for h in genre_hints:
        family = _ALIAS_TO_FAMILY.get(h.lower(), h.lower())
        primary.add(h.lower())
        primary.add(family)
    return primary


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
    """Extract genre hints from the prompt using the comprehensive taxonomy.

    Uses case-insensitive matching with word-boundary awareness so that
    "coldwave" matches even when the user wrote "Coldwave" or "cold wave".
    """
    genres: set[str] = set()
    prompt_lower = prompt.lower()

    # Check every alias in the taxonomy
    for _family, aliases in GENRE_ALIASES.items():
        for alias in aliases:
            # Use word-boundary matching to avoid false positives
            # (e.g. "ambient" shouldn't match inside "ambidextrous")
            pattern = r'(?:^|[\s,;/\-"(])' + re.escape(alias) + r'(?:[\s,;/\-")]|$)'
            if re.search(pattern, prompt_lower):
                genres.add(alias)

    # Fallback: also check individual tokens directly against alias set
    # for very short prompts like "coldwave" or "thrash"
    tokens = re.split(r'[\s,;/]+', prompt_lower)
    for token in tokens:
        token = token.strip('"\'()')
        if token in _ALIAS_TO_FAMILY:
            genres.add(token)
        # Also check 2-gram and 3-gram tokens
    for i in range(len(tokens) - 1):
        bigram = f"{tokens[i]} {tokens[i+1]}".strip('"\'()')
        if bigram in _ALIAS_TO_FAMILY:
            genres.add(bigram)
    for i in range(len(tokens) - 2):
        trigram = f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}".strip('"\'()')
        if trigram in _ALIAS_TO_FAMILY:
            genres.add(trigram)

    return list(genres)


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


# Temporal trajectory detection patterns
_ERA_CHRONOLOGICAL_SIGNALS = [
    "chronological", "through the decades", "through the years",
    "evolution of", "history of", "early to late", "oldest to newest",
    "from the beginning", "timeline", "progression through",
    "how .+ evolved", "from .+ to modern",
]
_ERA_REVERSE_SIGNALS = [
    "reverse chronological", "newest to oldest", "modern to classic",
    "late to early", "backwards through", "reverse timeline",
]
_ERA_LOCKED_SIGNALS = [
    "only from", "strictly from", "nothing outside",
]


def detect_era_mode(
    prompt: str,
    year_range: tuple[int | None, int | None],
    arc_type: ArcType,
) -> str:
    """Detect temporal trajectory mode from the prompt.

    Returns one of: none, chronological, reverse, locked, arc.
    """
    p = prompt.lower()

    # Explicit reverse chronological signals
    for sig in _ERA_REVERSE_SIGNALS:
        if re.search(sig, p):
            return "reverse"

    # Explicit chronological signals
    for sig in _ERA_CHRONOLOGICAL_SIGNALS:
        if re.search(sig, p):
            return "chronological"

    # Locked era: strict year constraint with narrow range
    yr0, yr1 = year_range
    if yr0 and yr1:
        span = yr1 - yr0
        for sig in _ERA_LOCKED_SIGNALS:
            if sig in p:
                return "locked"
        # Very narrow range (≤5 years) implies locked
        if span <= 5:
            return "locked"
        # Wide range (>15 years) with journey/wave arc implies chronological
        if span > 15 and arc_type in (ArcType.JOURNEY, ArcType.RISE):
            return "chronological"

    return "none"


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


def extract_impact_preference(prompt: str) -> float:
    """Extract impact preference from the prompt."""
    prompt_lower = prompt.lower()
    positive_terms = [
        "banger", "bangers", "hit", "hits", "anthem", "anthems",
        "classic", "classics", "best known", "best-known",
        "crowd pleaser", "crowd-pleaser", "crowd pleasers", "crowd-pleasers",
        "peak time", "peak-time", "standout", "killer tracks", "killers",
    ]
    negative_terms = [
        "deep cut", "deep cuts", "obscure", "leftfield", "non-obvious",
        "non obvious", "b-side", "b sides", "album cut", "album cuts",
    ]

    score = 0.0
    for term in positive_terms:
        if term in prompt_lower:
            score += 0.35
    for term in negative_terms:
        if term in prompt_lower:
            score -= 0.40

    if "mainstream" in prompt_lower and not any(
        phrase in prompt_lower
        for phrase in ("no mainstream", "avoid mainstream", "without mainstream", "not mainstream")
    ):
        score += 0.20

    return max(0.0, min(1.0, score))


def extract_avoid_keywords(prompt: str) -> list[str]:
    """Extract avoid keywords from the prompt."""
    prompt_lower = prompt.lower()
    patterns = [
        r"(?:^|[\s,])no\s+([^,.;]+)",
        r"avoid\s+([^,.;]+)",
        r"without\s+([^,.;]+)",
        r"not too\s+([^,.;]+)",
    ]

    phrases: list[str] = []
    for pattern in patterns:
        phrases.extend(re.findall(pattern, prompt_lower))

    expanded: list[str] = []
    for phrase in phrases:
        phrase = phrase.strip(" \"'()")
        if not phrase:
            continue
        parts = re.split(r"\s+(?:and|or)\s+|,", phrase)
        for part in parts:
            cleaned = part.strip(" \"'()")
            if len(cleaned) >= 2:
                expanded.append(cleaned)

    return list(dict.fromkeys(expanded))


def classify_prompt_type(
    genre_hints: list[str],
    arc_type: ArcType,
    arc_confidence: float,
    mood_keywords: list[str],
    prompt: str,
) -> PromptType:
    """Classify prompt as genre-focused, arc-focused, or mixed.

    Used by the adaptive scoring system to rebalance weights:
    - genre-focused → boost genre/BM25 weight, reduce trajectory weight
    - arc-focused   → boost trajectory weight, reduce genre weight
    - mixed         → balanced weights (current defaults)
    """
    has_genres = len(genre_hints) > 0
    has_strong_arc = arc_confidence >= 0.7 and arc_type != ArcType.STEADY

    if has_genres and has_strong_arc:
        return PromptType.MIXED
    if has_genres:
        return PromptType.GENRE
    if has_strong_arc:
        return PromptType.ARC
    # Short prompts with mood keywords but no genre → arc
    if mood_keywords and not has_genres:
        return PromptType.ARC
    return PromptType.MIXED


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


_LLM_INTENT_SYSTEM_PROMPT = """\
You are a music playlist intent parser. Given a user's natural language prompt, \
extract structured parameters for a playlist generation engine.

## Output Schema (JSON)

Return a JSON object with these fields:

- "arc_type": One of "steady", "rise", "fall", "peak", "valley", "wave", "journey"
  - "steady": Consistent mood/energy throughout
  - "rise": Building energy over time (workout warmup, morning energy)
  - "fall": Decreasing energy (wind down, sleep preparation)
  - "peak": Build to climax then resolve (60% build, 15% peak, 25% resolve)
  - "valley": Start high, dip into calm, return high
  - "wave": Oscillating energy pattern
  - "journey": Narrative arc with intro/build/climax/denouement (most versatile)

- "arc_confidence": Float 0.0-1.0. How clearly the prompt implies a specific arc shape. \
If the user explicitly describes an energy trajectory, use 0.85-1.0. If implied, 0.5-0.7. \
If no arc intent, use 0.3.

- "base_energy": Float 0.0-1.0. Overall energy/intensity level.
  - 0.0-0.2: ambient, drone, minimal
  - 0.3-0.5: mellow, chill, moderate
  - 0.6-0.8: energetic, driving, powerful
  - 0.9-1.0: extreme, crushing, relentless

- "base_darkness": Float 0.0-1.0. Mood darkness/heaviness.
  - 0.0-0.2: bright, uplifting, cheerful
  - 0.3-0.5: neutral, balanced
  - 0.6-0.8: dark, melancholic, heavy
  - 0.9-1.0: extremely dark, oppressive, sinister

- "base_tempo": Float 0.0-1.0. Speed/BPM tendency.
  - 0.0-0.2: very slow (funeral doom, ambient)
  - 0.3-0.5: moderate (mid-tempo rock, chill electronic)
  - 0.6-0.8: fast (punk, thrash, dance)
  - 0.9-1.0: extreme speed (grindcore, speedcore)

- "base_texture": Float 0.0-1.0. Sonic density and complexity.
  - 0.0-0.2: sparse, minimal, solo
  - 0.3-0.5: moderate, standard arrangement
  - 0.6-0.8: dense, layered, atmospheric
  - 0.9-1.0: wall of sound, maximalist

- "genre_hints": Array of strings. Specific genres/subgenres detected. Use standard genre \
names. IMPORTANT: For genre-focused prompts, ALWAYS include the primary genre AND its \
closest sibling/related genres. For example:
  - "coldwave" → ["coldwave", "darkwave", "minimal wave", "post-punk"]
  - "thrash metal" → ["thrash metal", "speed metal", "heavy metal"]
  - "doom metal" → ["doom metal", "stoner metal", "sludge metal"]
  - "post-punk" → ["post-punk", "gothic rock", "darkwave", "new wave"]
  - "black metal" → ["black metal", "atmospheric black metal"]
  - "aor" → ["aor", "melodic rock", "arena rock", "glam metal"]
  This ensures the playlist engine can find enough tracks in the right musical neighbourhood. \
Include 2-4 related genres for the primary genre. Can be empty for non-genre prompts. \
IMPORTANT: Do NOT include broad umbrella genres like "rock", "pop", "metal", "electronic" as \
genre_hints unless the user is specifically asking for those broad categories. For example, \
an AOR prompt should NOT include "rock" or "pop" — only specific subgenres like "melodic rock", \
"arena rock", "soft rock". A thrash metal prompt should NOT include "metal" — only "thrash metal", \
"speed metal", "heavy metal".

- "artist_seeds": Array of strings. Any artist names mentioned or implied. Preserve exact \
spelling and capitalisation as the user likely intends.

- "mood_keywords": Array of strings. Mood/atmosphere descriptors.

- "avoid_keywords": Array of strings. Things the user wants to exclude (from "no ...", \
"avoid ...", "without ...", "not too ...").

- "year_range": Array of [start_year, end_year] or null. Extract decade references \
("80s" = [1980, 1989]), era references ("early punk era" = [1976, 1982]), and explicit years.

- "target_duration_minutes": Integer or null. If the user specifies a duration \
("2 hours", "30 minutes", "1hr"), extract it in minutes. Otherwise null.

- "prompt_type": One of "genre", "arc", "mixed"
  - "genre": Primarily about a specific genre/style
  - "arc": Primarily about an energy/mood trajectory
  - "mixed": Both genre and trajectory elements, or abstract/conceptual prompts

- "genre_mode": One of "strict", "balanced", "exploratory"
  - "strict": User wants only tracks firmly in the target genre ("only thrash", single genre short prompt)
  - "balanced": Mixed genre+arc prompt or moderate genre signal (default)
  - "exploratory": User wants cross-genre exploration, journey arc, or uses words like "adjacent", "discover", "blend"

- "dimension_weights": Object with "energy", "tempo", "darkness", "texture", "era" as floats. \
The first four should be 0.15-0.45 and sum to ~1.0. "era" is 0.0 by default and only set to \
0.10-0.20 when the prompt has a clear temporal trajectory (e.g. "from 70s to modern", \
"reverse chronological"). Which dimensions matter most for this prompt: if the user talks about \
speed, boost tempo. If about mood, boost darkness. If about intensity, boost energy. \
If about temporal progression, set era to 0.10-0.20 and reduce others proportionally. \
Default: {"energy": 0.25, "tempo": 0.25, "darkness": 0.25, "texture": 0.25, "era": 0.0}.

- "custom_waypoints": Array of objects or null. Only set if the user describes a specific \
trajectory shape (e.g., "start ambient, build to crushing, end with clean guitar"). Each waypoint:
  - "position": Float 0.0-1.0 (where in the playlist)
  - "energy": Float 0.0-1.0
  - "darkness": Float 0.0-1.0
  - "tempo": Float 0.0-1.0
  - "texture": Float 0.0-1.0
  - "era": Float 0.0-1.0 (optional, only if temporal trajectory requested; 0=oldest, 1=newest)
  - "description": Short label for this phase
  If null, the system will generate waypoints from arc_type and base dimensions.

## Important
- Be musically literate. Understand genre relationships and implications.
- "Crushing doom" implies high darkness, low tempo, high texture, moderate-high energy.
- "Like Neurosis meets Bohren" implies post-metal/doom blended with dark jazz.
- Infer implicit genre hints even if not stated explicitly (e.g., "headbanging" → metal).
- Temporal/era awareness: prompts like "from 70s punk to modern post-punk" or "reverse \
chronological journey through metal" imply a temporal trajectory. Set era dimension weight \
to 0.10-0.20 for these. Simple decade references ("80s thrash") are just year_range filters, \
not temporal trajectories — keep era at 0.0 for those.
- Return ONLY valid JSON, no other text."""


def _parse_prompt_with_llm(prompt: str) -> dict | None:
    """Parse a prompt using OpenAI gpt-4o-mini for rich intent extraction.

    Returns a dict of parsed fields, or None if LLM parsing fails/is unavailable.
    """
    if not settings.openai_api_key:
        logger.debug("OpenAI not configured, skipping LLM intent parsing")
        return None

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _LLM_INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=800,
            temperature=0.3,
        )

        raw = response.choices[0].message.content
        if not raw:
            logger.warning("LLM intent parsing returned empty content")
            return None
        parsed = json.loads(raw.strip())

        # Validate required fields exist and have correct types
        _validate_llm_intent(parsed)

        logger.info(f"LLM intent parsed: arc={parsed.get('arc_type')}, "
                     f"genres={parsed.get('genre_hints', [])}, "
                     f"artists={parsed.get('artist_seeds', [])}, "
                     f"avoid={parsed.get('avoid_keywords', [])}")
        return parsed

    except json.JSONDecodeError as e:
        logger.warning(f"LLM intent parsing returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"LLM intent parsing failed: {e}")
        return None


def _validate_llm_intent(data: dict) -> None:
    """Validate and coerce LLM output to expected types. Raises ValueError on invalid data."""
    # arc_type must be valid
    valid_arcs = {"steady", "rise", "fall", "peak", "valley", "wave", "journey"}
    if data.get("arc_type") not in valid_arcs:
        data["arc_type"] = "journey"

    # Clamp floats to [0, 1]
    for key in ("arc_confidence", "base_energy", "base_darkness", "base_tempo", "base_texture"):
        if key in data:
            try:
                data[key] = max(0.0, min(1.0, float(data[key])))
            except (TypeError, ValueError):
                data[key] = 0.5

    # Lists must be lists of strings
    for key in ("genre_hints", "artist_seeds", "mood_keywords", "avoid_keywords"):
        if key not in data or not isinstance(data[key], list):
            data[key] = []
        else:
            data[key] = [str(item) for item in data[key] if item]

    # year_range: [start, end] or null
    yr = data.get("year_range")
    if isinstance(yr, list) and len(yr) == 2:
        try:
            data["year_range"] = (int(yr[0]), int(yr[1]))
        except (TypeError, ValueError):
            data["year_range"] = (None, None)
    else:
        data["year_range"] = (None, None)

    # target_duration_minutes: int or None
    dur = data.get("target_duration_minutes")
    if dur is not None:
        try:
            data["target_duration_minutes"] = int(dur)
        except (TypeError, ValueError):
            data["target_duration_minutes"] = None

    # prompt_type must be valid
    valid_types = {"genre", "arc", "mixed"}
    if data.get("prompt_type") not in valid_types:
        data["prompt_type"] = "mixed"

    # genre_mode must be valid
    valid_modes = {"strict", "balanced", "exploratory"}
    if data.get("genre_mode") not in valid_modes:
        data["genre_mode"] = "balanced"

    # dimension_weights: normalise
    dw = data.get("dimension_weights")
    if isinstance(dw, dict):
        try:
            weights = DimensionWeights(
                energy=float(dw.get("energy", 0.25)),
                tempo=float(dw.get("tempo", 0.25)),
                darkness=float(dw.get("darkness", 0.25)),
                texture=float(dw.get("texture", 0.25)),
                era=float(dw.get("era", 0.0)),
            )
            data["dimension_weights"] = weights.normalize()
        except (TypeError, ValueError):
            data["dimension_weights"] = DimensionWeights()
    else:
        data["dimension_weights"] = DimensionWeights()

    # custom_waypoints: list of dicts or None
    wps = data.get("custom_waypoints")
    if isinstance(wps, list) and len(wps) >= 2:
        validated = []
        for wp in wps:
            if isinstance(wp, dict):
                try:
                    validated.append({
                        "position": max(0.0, min(1.0, float(wp.get("position", 0.5)))),
                        "energy": max(0.0, min(1.0, float(wp.get("energy", 0.5)))),
                        "darkness": max(0.0, min(1.0, float(wp.get("darkness", 0.5)))),
                        "tempo": max(0.0, min(1.0, float(wp.get("tempo", 0.5)))),
                        "texture": max(0.0, min(1.0, float(wp.get("texture", 0.5)))),
                        "era": max(0.0, min(1.0, float(wp.get("era", 0.5)))),
                        "description": str(wp.get("description", "")),
                    })
                except (TypeError, ValueError):
                    continue
        data["custom_waypoints"] = validated if len(validated) >= 2 else None
    else:
        data["custom_waypoints"] = None


def parse_prompt(prompt: str, target_size: int = 20) -> PlaylistIntent:
    """Parse a natural language prompt into a structured PlaylistIntent.

    Tries LLM-powered parsing first (gpt-4o-mini) for rich semantic understanding,
    then falls back to keyword-based parsing if LLM is unavailable or fails.
    """
    logger.info(f"Parsing prompt: {prompt[:100]}...")

    # Generate embedding for the full prompt (always needed)
    prompt_embedding = generate_embedding(prompt)

    # Try LLM-powered parsing first
    llm_data = _parse_prompt_with_llm(prompt)

    if llm_data is not None:
        return _build_intent_from_llm(prompt, prompt_embedding, llm_data, target_size)

    # Fallback: keyword-based parsing
    logger.info("Using keyword-based prompt parsing (LLM unavailable)")
    return _build_intent_from_keywords(prompt, prompt_embedding, target_size)


def _build_intent_from_llm(
    prompt: str,
    prompt_embedding: list[float],
    data: dict,
    target_size: int,
) -> PlaylistIntent:
    """Build a PlaylistIntent from validated LLM output."""
    arc_type = ArcType(data["arc_type"])
    arc_confidence = data.get("arc_confidence", 0.7)

    # Use LLM's dimension weights (already validated as DimensionWeights)
    dimension_weights = data.get("dimension_weights", DimensionWeights())
    if not isinstance(dimension_weights, DimensionWeights):
        dimension_weights = DimensionWeights()

    base_energy = data.get("base_energy", 0.5)
    base_darkness = data.get("base_darkness", 0.5)
    base_tempo = data.get("base_tempo", 0.5)
    base_texture = data.get("base_texture", 0.5)

    prompt_type = PromptType(data.get("prompt_type", "mixed"))
    genre_hints_raw = data.get("genre_hints", [])
    # Record primary hints (pre-expansion) for tiered genre scoring
    genre_hints_primary = get_primary_genre_hints(genre_hints_raw)
    # Expand with related sibling genres for better pool coverage
    genre_hints = expand_genre_hints(genre_hints_raw) if genre_hints_raw else []
    artist_seeds = data.get("artist_seeds", [])
    mood_keywords = data.get("mood_keywords", [])
    avoid_keywords = list(dict.fromkeys(data.get("avoid_keywords", []) + extract_avoid_keywords(prompt)))
    year_range = data.get("year_range", (None, None))
    target_duration = data.get("target_duration_minutes")
    impact_preference = extract_impact_preference(prompt)

    # Detect temporal trajectory mode
    # If LLM already set era weight > 0, trust it; otherwise use keyword detection default
    era_mode = detect_era_mode(prompt, year_range, arc_type)
    if era_mode != "none" and dimension_weights.era < 0.05:
        dimension_weights.era = 0.12
        dimension_weights = dimension_weights.normalize()
    if era_mode != "none":
        logger.info(f"Temporal mode detected: era_mode={era_mode}, era_weight={dimension_weights.era:.2f}")

    # Generate trajectory curve from LLM's base dimensions and arc type
    trajectory_curve = generate_trajectory_curve(
        arc_type=arc_type.value,
        playlist_length=target_size,
        base_energy=base_energy,
        base_darkness=base_darkness,
        base_tempo=base_tempo,
        base_texture=base_texture,
        era_mode=era_mode,
        era_start=0.0 if era_mode in ("chronological", "arc") else 0.5,
        era_end=1.0 if era_mode in ("chronological", "arc") else 0.5,
    )

    # If LLM provided custom waypoints, use them to override the curve waypoints
    custom_wps = data.get("custom_waypoints")
    if custom_wps and len(custom_wps) >= 2:
        waypoints = [
            TrajectoryWaypoint(
                position=wp["position"],
                energy=wp["energy"],
                darkness=wp["darkness"],
                tempo=wp["tempo"],
                texture=wp["texture"],
                era=wp.get("era", 0.5),
                phase_label=wp.get("description", ""),
                description=wp.get("description", ""),
            )
            for wp in custom_wps
        ]
    else:
        num_waypoints = min(target_size, 10)
        waypoints = generate_waypoints_from_curve(trajectory_curve, num_waypoints)

    # Set waypoint descriptions (mood embeddings removed — unused by v4 pipeline)
    for i, wp in enumerate(waypoints):
        phase_descriptions = {
            0: f"opening: {prompt}",
            len(waypoints) - 1: f"closing: {prompt}",
        }
        wp.description = wp.description or phase_descriptions.get(
            i, f"{wp.phase_label} phase: {prompt}"
        )

    # Extract abstract concepts (still useful for semantic matching)
    abstract_concepts = extract_abstract_concepts(prompt)

    # Genre mode: prefer LLM output, but override with keyword detection if needed
    llm_genre_mode_str = data.get("genre_mode", "balanced")
    genre_mode = GenreMode(llm_genre_mode_str)
    # Keyword detection can sharpen LLM's classification
    kw_genre_mode = detect_genre_mode(prompt, genre_hints_raw, arc_type)
    if kw_genre_mode == GenreMode.STRICT and genre_mode != GenreMode.EXPLORATORY:
        genre_mode = GenreMode.STRICT

    # Load genre centroids from manifold (graceful no-op if table not yet built)
    genre_centroids: dict[str, list[float]] = {}
    if genre_hints_raw:
        try:
            from app.genre.manifold import get_genre_centroids
            genre_centroids = get_genre_centroids(genre_hints_raw)
        except Exception as _gce:
            logger.debug(f"Genre centroids unavailable: {_gce}")

    intent = PlaylistIntent(
        raw_prompt=prompt,
        prompt_embedding=prompt_embedding,
        arc_type=arc_type,
        arc_confidence=arc_confidence,
        target_size=target_size,
        target_duration_minutes=target_duration,
        impact_preference=impact_preference,
        prompt_type=prompt_type,
        mood_keywords=mood_keywords,
        genre_hints=genre_hints,
        genre_hints_primary=genre_hints_primary,
        artist_seeds=artist_seeds,
        trajectory_curve=trajectory_curve,
        waypoints=waypoints,
        dimension_weights=dimension_weights,
        base_energy=base_energy,
        base_darkness=base_darkness,
        base_tempo=base_tempo,
        base_texture=base_texture,
        avoid_keywords=avoid_keywords,
        year_range=year_range,
        era_mode=era_mode,
        abstract_concepts=abstract_concepts,
        genre_mode=genre_mode,
        genre_centroids=genre_centroids,
    )

    logger.info(f"LLM-parsed intent: arc={arc_type} (conf={arc_confidence:.2f}), "
                f"type={prompt_type.value}, genre_mode={genre_mode.value}, "
                f"era_mode={era_mode}, "
                f"moods={mood_keywords}, genres={genre_hints}, "
                f"artists={artist_seeds}, avoid={avoid_keywords}, "
                f"weights={dimension_weights.as_dict()}")
    return intent


def _build_intent_from_keywords(
    prompt: str,
    prompt_embedding: list[float],
    target_size: int,
) -> PlaylistIntent:
    """Build a PlaylistIntent from keyword-based parsing (original logic)."""
    # Extract genre hints first so they can inform arc detection
    genre_hints_raw = extract_genre_hints(prompt)
    # Record primary hints (pre-expansion) for tiered genre scoring
    genre_hints_primary = get_primary_genre_hints(genre_hints_raw)
    # Expand with related sibling genres for better pool coverage
    genre_hints = expand_genre_hints(genre_hints_raw) if genre_hints_raw else []

    # Extract remaining components
    arc_type, arc_confidence = detect_arc_type(prompt, genre_hints=genre_hints)
    mood_keywords = extract_mood_keywords(prompt)
    artist_seeds = extract_artist_seeds(prompt)
    avoid_keywords = extract_avoid_keywords(prompt)
    year_range = extract_year_range(prompt)
    abstract_concepts = extract_abstract_concepts(prompt)
    impact_preference = extract_impact_preference(prompt)

    # Extract dimension weights and base values
    dimension_weights = extract_dimension_weights(prompt, mood_keywords)
    base_dims = extract_base_dimensions(mood_keywords, genre_hints)

    # Classify prompt type for adaptive scoring
    prompt_type = classify_prompt_type(
        genre_hints, arc_type, arc_confidence, mood_keywords, prompt,
    )

    # Detect temporal trajectory mode
    era_mode = detect_era_mode(prompt, year_range, arc_type)
    if era_mode != "none":
        dimension_weights.era = 0.12
        dimension_weights = dimension_weights.normalize()
        logger.info(f"Temporal mode detected: era_mode={era_mode}, era_weight={dimension_weights.era:.2f}")

    # Generate 5D trajectory curve
    trajectory_curve = generate_trajectory_curve(
        arc_type=arc_type.value,
        playlist_length=target_size,
        base_energy=base_dims["energy"],
        base_darkness=base_dims["darkness"],
        base_tempo=base_dims["tempo"],
        base_texture=base_dims["texture"],
        era_mode=era_mode,
        era_start=0.0 if era_mode in ("chronological", "arc") else 0.5,
        era_end=1.0 if era_mode in ("chronological", "arc") else 0.5,
    )

    # Sample waypoints from curve
    num_waypoints = min(target_size, 10)  # Cap at 10 waypoints
    waypoints = generate_waypoints_from_curve(trajectory_curve, num_waypoints)

    # Set waypoint descriptions (mood embeddings removed — unused by v4 pipeline)
    for i, wp in enumerate(waypoints):
        phase_descriptions = {
            0: f"opening: {prompt}",
            len(waypoints) - 1: f"closing: {prompt}",
        }
        wp.description = phase_descriptions.get(i, f"{wp.phase_label} phase: {prompt}")

    genre_mode = detect_genre_mode(prompt, genre_hints_raw, arc_type)

    genre_centroids: dict[str, list[float]] = {}
    if genre_hints_raw:
        try:
            from app.genre.manifold import get_genre_centroids
            genre_centroids = get_genre_centroids(genre_hints_raw)
        except Exception as _gce:
            logger.debug(f"Genre centroids unavailable: {_gce}")

    intent = PlaylistIntent(
        raw_prompt=prompt,
        prompt_embedding=prompt_embedding,
        arc_type=arc_type,
        arc_confidence=arc_confidence,
        target_size=target_size,
        impact_preference=impact_preference,
        prompt_type=prompt_type,
        mood_keywords=mood_keywords,
        genre_hints=genre_hints,
        genre_hints_primary=genre_hints_primary,
        artist_seeds=artist_seeds,
        trajectory_curve=trajectory_curve,
        waypoints=waypoints,
        dimension_weights=dimension_weights,
        base_energy=base_dims["energy"],
        base_darkness=base_dims["darkness"],
        base_tempo=base_dims["tempo"],
        base_texture=base_dims["texture"],
        avoid_keywords=avoid_keywords,
        year_range=year_range,
        era_mode=era_mode,
        abstract_concepts=abstract_concepts,
        genre_mode=genre_mode,
        genre_centroids=genre_centroids,
    )

    logger.info(f"Keyword-parsed intent: arc={arc_type} (conf={arc_confidence:.2f}), "
                f"type={prompt_type.value}, genre_mode={genre_mode.value}, "
                f"era_mode={era_mode}, "
                f"moods={mood_keywords}, genres={genre_hints}, "
                f"weights={dimension_weights.as_dict()}")
    return intent
