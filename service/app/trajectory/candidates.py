"""
Position-based candidate pool generation.

Implements the v4 architecture:
1. Single semantic search for global candidate pool
2. Re-score candidates per playlist position against trajectory target
3. Adaptive pool sizing based on library size
"""

import logging
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from app.database_pg import get_connection
from app.embeddings.generator import generate_embedding
from app.trajectory.curves import TrajectoryPoint
from app.trajectory.gravity import GravityAnchors, compute_gravity_penalty
from app.trajectory.intent import PlaylistIntent, DimensionWeights, ArcType, PromptType, _ALIAS_TO_FAMILY, _BROAD_GENRES

logger = logging.getLogger(__name__)


def _coerce_embedding(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return value.astype(float, copy=False).tolist()
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype=float).tolist()
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        if not stripped:
            return None
        parsed = np.fromstring(stripped, sep=",", dtype=float)
        return parsed.tolist() if parsed.size > 0 else None
    return np.asarray(value, dtype=float).tolist()


@dataclass
class CandidateTrack:
    """A track candidate with scoring components."""
    id: str
    title: str
    artist_name: str
    artist_id: str | None
    album_name: str
    year: int | None
    duration_ms: int
    file_path: str | None = None

    # Embeddings
    embedding: list[float] | None = None

    # Profile (4D)
    energy: float = 0.5
    tempo: float = 0.5
    darkness: float = 0.5
    texture: float = 0.5

    # Cluster info
    cluster_id: int | None = None
    cluster_weight: float = 1.0

    # Genre tags (for genre continuity and Jaccard scoring)
    genres: list = field(default_factory=list)  # list[str]

    # Acoustic features (from track_audio_features, optional)
    bpm_norm: float | None = None
    loudness_norm: float | None = None
    brightness_norm: float | None = None
    playcount: int = 0
    listeners: int = 0

    # Scoring components (all normalized 0-1)
    semantic_score: float = 0.0   # combined retrieval: 0.65*cosine + 0.35*keyword
    keyword_score: float = 0.0    # raw BM25 score (before normalization)
    trajectory_score: float = 0.0
    gravity_penalty: float = 0.0
    duration_penalty: float = 0.0
    year_score: float = 0.0       # soft year-range bonus/penalty
    genre_match_score: float = 0.0  # Jaccard(intent.genre_hints, track.genres)
    usage_penalty: float = 0.0     # time-decayed track usage penalty
    impact_score: float = 0.0
    admissibility_score: float = 0.0
    negative_constraint_penalty: float = 0.0
    tourist_match_penalty: float = 0.0

    # Adaptive scoring weights (set per-prompt by generate_position_pools)
    _w_semantic: float = 0.25
    _w_trajectory: float = 0.35
    _w_genre: float = 0.20
    _w_gravity: float = 0.15
    _w_duration: float = 0.10
    _w_impact: float = 0.0

    @property
    def total_score(self) -> float:
        return (
            self.semantic_score * self._w_semantic +
            self.trajectory_score * self._w_trajectory +
            self.genre_match_score * self._w_genre +
            self.impact_score * self._w_impact +
            self.year_score -
            self.gravity_penalty * self._w_gravity -
            self.duration_penalty * self._w_duration -
            self.negative_constraint_penalty -
            self.tourist_match_penalty -
            self.usage_penalty
        )

    def profile_array(self) -> np.ndarray:
        """Return profile as numpy array."""
        return np.array([self.energy, self.tempo, self.darkness, self.texture])


def compute_genre_match_score(
    track: CandidateTrack,
    hint_set: set[str],
    primary_hint_set: set[str],
) -> float:
    if not hint_set or not track.genres:
        return 0.0

    genre_set_raw = {g.lower() for g in track.genres}
    genre_set_with_families: set[str] = set(genre_set_raw)
    for genre_name in genre_set_raw:
        family = _ALIAS_TO_FAMILY.get(genre_name)
        if family:
            genre_set_with_families.add(family)

    weight_sum = 0.0
    n_tags = len(genre_set_raw)
    for genre_name in genre_set_with_families:
        if genre_name not in hint_set:
            continue
        if genre_name in _BROAD_GENRES:
            weight_sum += 0.25
        elif genre_name in primary_hint_set:
            weight_sum += 1.0
        else:
            weight_sum += 0.5

    return min(1.0, weight_sum / n_tags) if n_tags > 0 else 0.0


def compute_negative_constraint_penalty(
    track: CandidateTrack,
    avoid_keywords: list[str],
) -> float:
    if not avoid_keywords:
        return 0.0

    haystack_parts = [track.title or "", track.artist_name or "", track.album_name or ""]
    haystack_parts.extend(track.genres or [])
    haystack = " ".join(haystack_parts).lower()
    haystack_tokens = {token for token in re.findall(r"[a-z0-9]+", haystack) if len(token) >= 2}

    penalty = 0.0
    for phrase in avoid_keywords:
        normalized = phrase.lower().strip()
        if not normalized:
            continue
        if normalized in haystack:
            penalty += 0.25
            continue
        phrase_tokens = [
            token for token in re.findall(r"[a-z0-9]+", normalized)
            if len(token) >= 2 and token not in {"too", "very", "really", "sounds", "sound"}
        ]
        if not phrase_tokens:
            continue
        overlap = sum(1 for token in phrase_tokens if token in haystack_tokens)
        if overlap == len(phrase_tokens):
            penalty += 0.18
        elif overlap >= 2:
            penalty += 0.10

    return min(0.45, penalty)


def compute_tourist_match_penalty(
    semantic_score: float,
    genre_match_score: float,
    semantic_floor: float,
) -> float:
    if genre_match_score <= 0.0 or semantic_score >= semantic_floor:
        return 0.0
    gap = max(0.0, semantic_floor - semantic_score)
    return min(0.25, 0.08 + gap * 0.6 + genre_match_score * 0.15)


def compute_impact_score(
    track: CandidateTrack,
    artist_maxima: dict[str, tuple[int, int]],
    global_max_playcount: int,
    global_max_listeners: int,
    impact_preference: float,
) -> float:
    if impact_preference <= 0.0:
        return 0.0

    global_play = math.log1p(max(0, track.playcount)) / math.log1p(max(1, global_max_playcount))
    global_listeners = math.log1p(max(0, track.listeners)) / math.log1p(max(1, global_max_listeners))
    global_score = 0.5 * (global_play + global_listeners)

    within_artist_score = global_score
    if track.artist_id and track.artist_id in artist_maxima:
        max_playcount, max_listeners = artist_maxima[track.artist_id]
        artist_play = (track.playcount / max_playcount) if max_playcount > 0 else 0.0
        artist_listeners = (track.listeners / max_listeners) if max_listeners > 0 else 0.0
        within_artist_score = 0.5 * (artist_play + artist_listeners)

    return min(1.0, (0.45 * global_score + 0.55 * within_artist_score) * impact_preference)


def compute_admissibility_score(
    track: CandidateTrack,
    semantic_floor: float,
) -> float:
    semantic_strength = min(1.0, track.semantic_score / max(semantic_floor, 1e-6))
    return (
        semantic_strength * 0.60 +
        track.genre_match_score * 0.20 +
        max(0.0, track.year_score) * 0.05 +
        track.impact_score * 0.15 -
        track.negative_constraint_penalty * 0.50 -
        track.tourist_match_penalty * 0.35
    )


def get_adaptive_pool_size(library_size: int, target_size: int = 25) -> int:
    """Calculate adaptive pool size based on library and playlist size.

    The pool must be large enough that beam search can find valid
    extensions at every position.  For large playlists the pool needs
    more headroom so artist-distance constraints don't exhaust options.

    The upper cap scales with target_size: small playlists cap at 500,
    but very large playlists (200+ tracks) scale up to 800 to reduce
    the chance of pool exhaustion during beam search.
    """
    base = int(math.sqrt(library_size) * 1.5)
    # Scale up for larger playlists: at least 2x the target size
    scaled = max(base, target_size * 2)
    # Dynamic cap: 500 for small playlists, up to 800 for very large ones
    cap = max(500, min(800, 500 + target_size))
    return max(50, min(cap, scaled))


def get_library_size() -> int:
    """Get total number of tracks in library."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tracks")
            return cur.fetchone()[0]


def semantic_search(
    prompt_embedding: list[float],
    limit: int = 400,
    year_range: tuple[int | None, int | None] = (None, None),
) -> list[CandidateTrack]:
    """
    Perform single semantic search for global candidate pool.

    Uses pgvector for efficient similarity search.
    """
    embedding_array = np.array(prompt_embedding)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Build params in SQL order: SELECT similarity, year filters, ORDER BY, LIMIT
            year_filter = ""
            year_params: list = []

            if year_range[0]:
                year_filter += " AND t.year >= %s"
                year_params.append(year_range[0])
            if year_range[1]:
                year_filter += " AND t.year <= %s"
                year_params.append(year_range[1])

            emb = embedding_array.tolist()
            query_params = [emb] + year_params + [emb, limit]

            # Query with semantic similarity ordering
            cur.execute(f"""
                SELECT
                    t.id, t.title,
                    a.name as artist_name,
                    ta.artist_id,
                    al.title as album_name,
                    t.year, t.duration_ms,
                    te.embedding,
                    tp.energy, tp.darkness, tp.tempo, tp.texture,
                    tf.path,
                    1 - (te.embedding <=> %s::vector) as similarity,
                    ARRAY(
                        SELECT g.name FROM track_genres tg2
                        JOIN genres g ON tg2.genre_id = g.id
                        WHERE tg2.track_id = t.id
                    ) AS genres,
                    taf.bpm_norm, taf.loudness_norm, taf.brightness_norm,
                    COALESCE(ls.playcount, 0), COALESCE(ls.listeners, 0)
                FROM tracks t
                LEFT JOIN track_embeddings te ON t.id = te.track_id
                LEFT JOIN track_profiles tp ON t.id = tp.track_id
                LEFT JOIN track_files tf ON t.id = tf.track_id AND tf.missing_since IS NULL
                LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
                LEFT JOIN artists a ON ta.artist_id = a.id
                LEFT JOIN track_albums tal ON tal.track_id = t.id
                LEFT JOIN albums al ON tal.album_id = al.id
                LEFT JOIN track_audio_features taf ON t.id = taf.track_id
                LEFT JOIN lastfm_stats ls ON t.id = ls.track_id
                WHERE te.embedding IS NOT NULL
                {year_filter}
                ORDER BY te.embedding <=> %s::vector
                LIMIT %s
            """, query_params)

            results = cur.fetchall()

    candidates = []
    for row in results:
        candidates.append(CandidateTrack(
            id=str(row[0]),
            title=row[1] or "Unknown",
            artist_name=row[2] or "Unknown",
            artist_id=str(row[3]) if row[3] else None,
            album_name=row[4] or "Unknown",
            year=row[5],
            duration_ms=row[6] or 0,
            embedding=_coerce_embedding(row[7]),
            energy=row[8] if row[8] is not None else 0.5,
            darkness=row[9] if row[9] is not None else 0.5,
            tempo=row[10] if row[10] is not None else 0.5,
            texture=row[11] if row[11] is not None else 0.5,
            file_path=row[12],
            semantic_score=row[13] if row[13] is not None else 0.0,
            genres=list(row[14]) if row[14] else [],
            bpm_norm=row[15],
            loudness_norm=row[16],
            brightness_norm=row[17],
            playcount=int(row[18] or 0),
            listeners=int(row[19] or 0),
        ))

    logger.info(f"Semantic search returned {len(candidates)} candidates")
    return candidates


# ---------------------------------------------------------------------------
# BM25 keyword search (Fix 8)
# ---------------------------------------------------------------------------

GENRE_SYNONYMS: dict[str, str] = {
    # Mood / attitude descriptors → genre/tag expansions
    "evil": "dark black metal thrash metal",
    "filthy": "raw sludge crust punk",
    "bestial": "war metal bestial black metal",
    "teutonic": "german thrash teutonic thrash",
    "necro": "raw black metal lo-fi",
    "evil thrash": "thrash metal dark blackened thrash",
    "satanic": "black metal dark satanic",
    "brutal": "death metal brutal death metal",
    "pure evil": "black metal dark thrash metal",
    "true": "black metal raw",
    "kvlt": "black metal raw underground",
    "grim": "black metal depressive raw",
    "occult": "occult rock black metal ritual",
    "ritual": "ritual ambient dark ambient neofolk",
    "bleak": "depressive post-punk coldwave darkwave",
    "cold": "coldwave cold wave minimal wave post-punk",
    "frozen": "black metal atmospheric ambient",
    "icy": "coldwave atmospheric black metal",
    "nocturnal": "dark ambient gothic darkwave",
    "urban": "post-punk ebm coldwave darkwave",
    "industrial": "industrial ebm power electronics",
    "raw": "raw black metal punk crust",
    "underground": "underground raw lo-fi",
    "old school": "old school death metal classic nwobhm",
    "classic": "classic rock nwobhm heavy metal",
    "progressive": "progressive metal progressive rock",
    "atmospheric": "atmospheric black metal ambient post-rock",
    "melodic": "melodic death metal melodic black metal",
    "technical": "technical death metal technical thrash",
    "crushing": "doom metal sludge death metal",
    "heavy": "heavy metal doom metal sludge",
    "fast": "thrash metal speed metal grindcore",
    "slow": "doom metal funeral doom drone ambient",
    "noisy": "noise harsh noise noise rock",
    "ethereal": "ethereal darkwave dream pop shoegaze",
    "dreamy": "dream pop shoegaze ambient",
    "hypnotic": "krautrock techno psychedelic trance",
    "groovy": "stoner rock groove metal funk",
    "psychedelic": "psychedelic rock psychedelic space rock acid rock",
    "epic": "epic heavy metal epic doom metal symphonic power metal",
    "majestic": "symphonic metal power metal epic",
    "sinister": "black metal dark death metal",
    "aggressive": "thrash metal death metal hardcore punk",
    "melancholic": "doom metal gothic darkwave depressive",
    "triumphant": "power metal epic heavy metal",
    "mechanical": "industrial ebm techno",
    "minimal": "minimal wave minimal synth coldwave",
    "lo-fi": "lo-fi raw underground",
    "vintage": "nwobhm classic rock heavy metal",
    "80s": "new wave synth-pop nwobhm thrash metal coldwave",
    "70s": "classic rock heavy metal progressive rock krautrock punk",
    "90s": "grunge alternative rock death metal black metal",
}


def expand_query(prompt: str) -> str:
    """Expand underground/niche genre terms for better BM25 recall."""
    expanded = prompt.lower()
    for term, replacement in GENRE_SYNONYMS.items():
        if term in expanded:
            expanded = expanded.replace(term, f"{term} {replacement}")
    return expanded


def keyword_search(
    prompt: str,
    limit: int = 200,
    genre_hints: list[str] | None = None,
) -> list["CandidateTrack"]:
    """BM25 full-text search using Postgres tsvector / ts_rank.

    Uses OR semantics so any matching term contributes to the rank,
    rather than requiring ALL terms to be present.

    When genre_hints are provided, builds the query from those instead
    of the raw prompt expansion for more focused results.
    """
    import re

    if genre_hints:
        # Use genre hints directly — these are the parsed, authoritative genre terms
        raw_text = " ".join(genre_hints)
    else:
        raw_text = expand_query(prompt)

    # Build an OR-based tsquery from cleaned terms
    raw_words = raw_text.lower().split()
    clean_words: list[str] = []
    for w in raw_words:
        w = re.sub(r"[^a-z0-9\-]", "", w)
        if not w:
            continue
        parts = [p for p in w.split("-") if p]
        clean_words.extend(parts)
    # Deduplicate preserving order
    clean_words = list(dict.fromkeys(clean_words))
    if not clean_words:
        return []
    or_query = " | ".join(clean_words)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    t.id, t.title,
                    a.name as artist_name,
                    ta.artist_id,
                    al.title as album_name,
                    t.year, t.duration_ms,
                    tf.path,
                    tp.energy, tp.darkness, tp.tempo, tp.texture,
                    ts_rank(t.search_vector,
                            to_tsquery('simple', %s)) AS keyword_score,
                    ARRAY(
                        SELECT g.name FROM track_genres tg2
                        JOIN genres g ON tg2.genre_id = g.id
                        WHERE tg2.track_id = t.id
                    ) AS genres,
                    taf.bpm_norm, taf.loudness_norm, taf.brightness_norm,
                    COALESCE(ls.playcount, 0), COALESCE(ls.listeners, 0)
                FROM tracks t
                LEFT JOIN track_profiles tp ON t.id = tp.track_id
                LEFT JOIN track_files tf ON t.id = tf.track_id
                    AND tf.missing_since IS NULL
                LEFT JOIN track_artists ta ON ta.track_id = t.id
                    AND ta.role = 'primary'
                LEFT JOIN artists a ON ta.artist_id = a.id
                LEFT JOIN track_albums tal ON tal.track_id = t.id
                LEFT JOIN albums al ON tal.album_id = al.id
                LEFT JOIN track_audio_features taf ON t.id = taf.track_id
                LEFT JOIN lastfm_stats ls ON t.id = ls.track_id
                WHERE t.search_vector @@ to_tsquery('simple', %s)
                ORDER BY keyword_score DESC
                LIMIT %s
            """, (or_query, or_query, limit))
            rows = cur.fetchall()

    candidates = []
    for row in rows:
        candidates.append(CandidateTrack(
            id=str(row[0]),
            title=row[1] or "Unknown",
            artist_name=row[2] or "Unknown",
            artist_id=str(row[3]) if row[3] else None,
            album_name=row[4] or "Unknown",
            year=row[5],
            duration_ms=row[6] or 0,
            file_path=row[7],
            energy=row[8] if row[8] is not None else 0.5,
            darkness=row[9] if row[9] is not None else 0.5,
            tempo=row[10] if row[10] is not None else 0.5,
            texture=row[11] if row[11] is not None else 0.5,
            keyword_score=float(row[12]) if row[12] is not None else 0.0,
            semantic_score=0.0,
            genres=list(row[13]) if row[13] else [],
            bpm_norm=row[14],
            loudness_norm=row[15],
            brightness_norm=row[16],
            playcount=int(row[17] or 0),
            listeners=int(row[18] or 0),
        ))

    logger.info(f"BM25 keyword search returned {len(candidates)} candidates")
    return candidates


def _fetch_candidates_by_ids(
    track_ids: list[str],
) -> list["CandidateTrack"]:
    """Batch-fetch CandidateTrack metadata for a list of track IDs.

    Used to hydrate genre/year pool results without N+1 queries.
    """
    if not track_ids:
        return []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    t.id, t.title,
                    a.name as artist_name,
                    ta.artist_id,
                    al.title as album_name,
                    t.year, t.duration_ms,
                    tf.path,
                    tp.energy, tp.darkness, tp.tempo, tp.texture,
                    ARRAY(
                        SELECT g.name FROM track_genres tg2
                        JOIN genres g ON tg2.genre_id = g.id
                        WHERE tg2.track_id = t.id
                    ) AS genres,
                    taf.bpm_norm, taf.loudness_norm, taf.brightness_norm,
                    COALESCE(ls.playcount, 0), COALESCE(ls.listeners, 0)
                FROM tracks t
                LEFT JOIN track_profiles tp ON t.id = tp.track_id
                LEFT JOIN track_files tf ON t.id = tf.track_id
                    AND tf.missing_since IS NULL
                LEFT JOIN track_artists ta ON ta.track_id = t.id
                    AND ta.role = 'primary'
                LEFT JOIN artists a ON ta.artist_id = a.id
                LEFT JOIN track_albums tal ON tal.track_id = t.id
                LEFT JOIN albums al ON tal.album_id = al.id
                LEFT JOIN track_audio_features taf ON t.id = taf.track_id
                LEFT JOIN lastfm_stats ls ON t.id = ls.track_id
                WHERE t.id = ANY(%s::uuid[])
            """, (track_ids,))
            rows = cur.fetchall()

    candidates = []
    for row in rows:
        candidates.append(CandidateTrack(
            id=str(row[0]),
            title=row[1] or "Unknown",
            artist_name=row[2] or "Unknown",
            artist_id=str(row[3]) if row[3] else None,
            album_name=row[4] or "Unknown",
            year=row[5],
            duration_ms=row[6] or 0,
            file_path=row[7],
            energy=row[8] if row[8] is not None else 0.5,
            darkness=row[9] if row[9] is not None else 0.5,
            tempo=row[10] if row[10] is not None else 0.5,
            texture=row[11] if row[11] is not None else 0.5,
            genres=list(row[12]) if row[12] else [],
            bpm_norm=row[13],
            loudness_norm=row[14],
            brightness_norm=row[15],
            playcount=int(row[16] or 0),
            listeners=int(row[17] or 0),
            semantic_score=0.0,
        ))

    return candidates


def build_phase_queries(intent: PlaylistIntent) -> list[str]:
    """
    Build phase-specific text queries for multi-query semantic retrieval.

    For non-STEADY arcs, expands the base prompt with phase descriptions
    (intro/peak/resolve) to widen the candidate pool.
    """
    prompt = intent.raw_prompt
    arc = intent.arc_type

    phase_map: dict[ArcType, list[str]] = {
        ArcType.RISE: [
            f"{prompt} quiet gentle intro",
            f"{prompt} energetic intense climax",
        ],
        ArcType.FALL: [
            f"{prompt} high energy opening",
            f"{prompt} gentle quiet fade outro",
        ],
        ArcType.PEAK: [
            f"{prompt} calm subdued intro",
            f"{prompt} intense explosive peak climax",
            f"{prompt} resolve mellow denouement",
        ],
        ArcType.VALLEY: [
            f"{prompt} high energy opening",
            f"{prompt} subdued quiet center",
        ],
        ArcType.WAVE: [
            f"{prompt} build energy rise",
            f"{prompt} peak intense climax",
            f"{prompt} resolve calm",
        ],
        ArcType.JOURNEY: [
            f"{prompt} intro beginning",
            f"{prompt} peak intense climax",
            f"{prompt} resolve ending denouement",
        ],
    }

    return phase_map.get(arc, [prompt])


def multi_query_semantic_search(
    intent: PlaylistIntent,
    limit_per_query: int = 200,
    year_range: tuple[int | None, int | None] = (None, None),
) -> list["CandidateTrack"]:
    """
    Run semantic search for each arc phase query and union results.

    Tracks appearing in multiple queries retain the highest semantic score.
    """
    phase_queries = build_phase_queries(intent)
    pool_map: dict[str, "CandidateTrack"] = {}

    for query in phase_queries:
        embedding = generate_embedding(query)
        candidates = semantic_search(embedding, limit=limit_per_query, year_range=year_range)
        for c in candidates:
            if c.id not in pool_map or c.semantic_score > pool_map[c.id].semantic_score:
                pool_map[c.id] = c

    logger.info(
        f"Multi-query search: {len(phase_queries)} queries → {len(pool_map)} unique candidates"
    )
    return list(pool_map.values())


def score_trajectory_match(
    track: CandidateTrack,
    target: TrajectoryPoint,
    weights: DimensionWeights,
) -> float:
    """
    Score how well a track matches the trajectory target.

    Returns normalized score in [0, 1] where 1 = perfect match.
    """
    # Compute weighted distance
    track_profile = track.profile_array()
    target_profile = target.as_array()
    weight_array = np.array([weights.energy, weights.tempo, weights.darkness, weights.texture])

    # Weighted absolute difference
    diff = np.abs(track_profile - target_profile)
    weighted_diff = np.sum(diff * weight_array)

    # Convert to similarity (max possible diff is 1.0 with normalized weights)
    return max(0.0, 1.0 - weighted_diff)


def score_duration_compatibility(
    track_duration_ms: int,
    prev_duration_ms: int | None,
    max_ratio: float = 2.5,
) -> float:
    """
    Score duration compatibility with previous track.

    Returns penalty in [0, 1] where 0 = good, 1 = bad.
    """
    if prev_duration_ms is None or prev_duration_ms == 0 or track_duration_ms == 0:
        return 0.0

    ratio = max(track_duration_ms, prev_duration_ms) / min(track_duration_ms, prev_duration_ms)

    if ratio <= 1.5:
        return 0.0  # Good compatibility
    elif ratio >= max_ratio:
        return 0.3  # Max penalty
    else:
        # Linear interpolation
        return 0.3 * (ratio - 1.5) / (max_ratio - 1.5)


# ---------------------------------------------------------------------------
# Adaptive scoring weights per prompt type  (Phase 3b)
# ---------------------------------------------------------------------------

def get_adaptive_weights(prompt_type: PromptType) -> dict[str, float]:
    """Return scoring weights tuned for the prompt classification.

    Genre-focused prompts boost genre Jaccard + semantic (which includes BM25)
    and reduce trajectory weight.  Arc-focused prompts do the opposite.
    """
    if prompt_type == PromptType.GENRE:
        return {
            "semantic": 0.38,
            "trajectory": 0.10,
            "genre": 0.27,
            "gravity": 0.15,
            "duration": 0.10,
        }
    elif prompt_type == PromptType.ARC:
        return {
            "semantic": 0.30,
            "trajectory": 0.30,
            "genre": 0.10,
            "gravity": 0.20,
            "duration": 0.10,
        }
    else:  # MIXED
        return {
            "semantic": 0.40,
            "trajectory": 0.20,
            "genre": 0.15,
            "gravity": 0.15,
            "duration": 0.10,
        }


def generate_position_pools(
    intent: PlaylistIntent,
    anchors: GravityAnchors,
    pool_size: int | None = None,
) -> list[list[CandidateTrack]]:
    """
    Generate candidate pools for each playlist position.

    V4 algorithm (extended):
    1. Semantic (pgvector) search → global candidate pool
       - For genre-focused prompts: enhance query text with genre names
    2. BM25 keyword search → merge via combined retrieval score
       - BM25 matches boosted for genre-focused prompts
    3. Genre-filtered pool → union for intent.genre_hints
    4. Year+genre pool → union when year_range + genre_hints present
    5. Apply track usage penalties (playlist memory)
    6. Re-score each candidate per position against trajectory target
    7. Select top-k for each position pool
    """
    from app.observability import get_track_usage_penalties

    # Determine pool size
    if pool_size is None:
        library_size = get_library_size()
        pool_size = get_adaptive_pool_size(library_size, target_size=intent.target_size)

    # Scale global search limit based on playlist size
    global_limit = max(400, min(1000, pool_size * 3))

    # Get adaptive scoring weights based on prompt type
    weights = get_adaptive_weights(intent.prompt_type)
    w_semantic = weights["semantic"]
    w_trajectory = weights["trajectory"]
    w_genre = weights["genre"]
    w_gravity = weights["gravity"]
    w_duration = weights["duration"]
    w_impact = min(0.12, 0.12 * intent.impact_preference)

    logger.info(f"Adaptive weights ({intent.prompt_type.value}): "
                f"sem={w_semantic}, traj={w_trajectory}, genre={w_genre}, impact={w_impact}")

    # --- 1. Semantic search (multi-query for non-STEADY arcs) ---
    # For genre-focused prompts, enhance the embedding query with genre names
    # so the embedding space is pushed toward the right neighbourhood.
    search_embedding = intent.prompt_embedding
    if intent.prompt_type == PromptType.GENRE and intent.genre_hints:
        genre_text = " ".join(intent.genre_hints)
        enhanced_query = f"{intent.raw_prompt} {genre_text}"
        search_embedding = generate_embedding(enhanced_query)
        logger.info(f"Enhanced semantic query for genre prompt: +'{genre_text}'")

    if intent.arc_type == ArcType.STEADY:
        semantic_candidates = semantic_search(
            search_embedding,
            limit=global_limit,
            year_range=intent.year_range,
        )
    else:
        semantic_candidates = multi_query_semantic_search(
            intent,
            limit_per_query=global_limit,
            year_range=intent.year_range,
        )

    # Build a mutable pool keyed by track ID
    pool_map: dict[str, CandidateTrack] = {c.id: c for c in semantic_candidates}

    # --- 2. BM25 keyword search + merge ---
    bm25_limit = max(200, min(500, pool_size * 2))
    try:
        kw_candidates = keyword_search(intent.raw_prompt, limit=bm25_limit,
                                           genre_hints=intent.genre_hints)
        if kw_candidates:
            # Normalize keyword scores
            max_kw = max(c.keyword_score for c in kw_candidates) or 1.0
            # For genre-focused prompts, give BM25 matches a bigger boost
            kw_weight = 0.50 if intent.prompt_type == PromptType.GENRE else 0.35
            sem_weight = 1.0 - kw_weight

            for c in kw_candidates:
                norm_kw = c.keyword_score / max_kw
                if c.id in pool_map:
                    # Existing: combine retrieval scores
                    existing = pool_map[c.id]
                    combined = sem_weight * existing.semantic_score + kw_weight * norm_kw
                    pool_map[c.id] = replace(
                        existing,
                        keyword_score=norm_kw,
                        semantic_score=combined,
                    )
                else:
                    # New from BM25: give them a meaningful semantic score
                    # so they can compete with pure-semantic results
                    pool_map[c.id] = replace(
                        c,
                        keyword_score=norm_kw,
                        semantic_score=kw_weight * norm_kw,
                    )
    except Exception as e:
        logger.warning(f"BM25 keyword search failed (search_vector may not exist yet): {e}")

    # --- 3. Genre-based secondary pool (Fix 1) ---
    # Filter out broad umbrella genres from pool queries to avoid pulling
    # thousands of irrelevant tracks (e.g. "rock" would match half the library).
    specific_genre_hints = [g for g in intent.genre_hints
                           if g.lower() not in _BROAD_GENRES]
    genre_pool_limit = max(500, min(2000, pool_size * 5))
    if specific_genre_hints:
        patterns = [f"%{g}%" for g in specific_genre_hints]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT tg.track_id::text
                        FROM track_genres tg
                        JOIN genres g ON tg.genre_id = g.id
                        WHERE g.name ILIKE ANY(%s)
                        LIMIT %s
                    """, (patterns, genre_pool_limit))
                    genre_ids = [row[0] for row in cur.fetchall()
                                 if row[0] not in pool_map]

            if genre_ids:
                genre_tracks = _fetch_candidates_by_ids(genre_ids)
                for t in genre_tracks:
                    # Give genre-pool tracks a baseline genre_match_score
                    # so they aren't invisible when merged
                    t_with_score = replace(t, semantic_score=0.15)
                    pool_map[t.id] = t_with_score
                logger.info(f"Genre pool added {len(genre_tracks)} candidates")
        except Exception as e:
            logger.warning(f"Genre pool query failed: {e}")

    # --- 3b. Last.fm artist tag pool (covers artist-level tags) ---
    if specific_genre_hints:
        tag_patterns = [f"%{g}%" for g in specific_genre_hints]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT ta.track_id::text
                        FROM track_artists ta
                        JOIN artist_lastfm_tags alt ON alt.artist_id = ta.artist_id
                        JOIN lastfm_tags lt ON lt.id = alt.tag_id
                        WHERE lt.name ILIKE ANY(%s)
                          AND alt.weight >= 50
                        LIMIT %s
                    """, (tag_patterns, genre_pool_limit))
                    tag_ids = [row[0] for row in cur.fetchall()
                               if row[0] not in pool_map]

            if tag_ids:
                tag_tracks = _fetch_candidates_by_ids(tag_ids)
                for t in tag_tracks:
                    pool_map[t.id] = replace(t, semantic_score=0.15)
                logger.info(f"Artist-tag pool added {len(tag_tracks)} candidates")
        except Exception as e:
            logger.warning(f"Artist-tag pool query failed: {e}")

    # --- 4. Year+genre third pool (Fix 2) ---
    yr0, yr1 = intent.year_range
    if yr0 and yr1 and specific_genre_hints:
        patterns = [f"%{g}%" for g in specific_genre_hints]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT t.id::text
                        FROM tracks t
                        JOIN track_genres tg ON tg.track_id = t.id
                        JOIN genres g ON tg.genre_id = g.id
                        WHERE t.year BETWEEN %s AND %s
                          AND g.name ILIKE ANY(%s)
                        LIMIT %s
                    """, (yr0, yr1, patterns, genre_pool_limit))
                    year_ids = [row[0] for row in cur.fetchall()
                                if row[0] not in pool_map]

            if year_ids:
                year_tracks = _fetch_candidates_by_ids(year_ids)
                for t in year_tracks:
                    pool_map[t.id] = t
                logger.info(f"Year+genre pool added {len(year_tracks)} candidates")
        except Exception as e:
            logger.warning(f"Year+genre pool query failed: {e}")

    global_candidates = list(pool_map.values())

    if not global_candidates:
        logger.warning("No candidates found across all pool sources")
        return []

    logger.info(f"Total global candidate pool: {len(global_candidates)} tracks")

    # --- 5. Fetch track usage penalties (playlist memory) ---
    all_ids = [c.id for c in global_candidates]
    usage_penalties = get_track_usage_penalties(all_ids)

    # Precompute genre hint set for scoring.
    # We build two sets: primary_hint_set (from LLM / keyword extraction) and
    # expanded_hint_set (added by expand_genre_hints).  Primary matches get
    # full weight; expanded matches get partial weight.  Broad umbrella genres
    # (rock, pop, etc.) get heavily discounted to prevent them from making every track score 1.0.
    hint_set = {h.lower() for h in intent.genre_hints} if intent.genre_hints else set()
    # Also add canonical families for the hints
    for h in list(hint_set):
        fam = _ALIAS_TO_FAMILY.get(h)
        if fam:
            hint_set.add(fam)

    # Primary hints: what the user/LLM explicitly requested (pre-expansion)
    primary_hint_set = intent.genre_hints_primary if intent.genre_hints_primary else hint_set.copy()

    # Precompute year midpoint for soft year scoring
    year_midpoint: float | None = None
    if yr0 and yr1:
        year_midpoint = (yr0 + yr1) / 2.0

    semantic_values = [c.semantic_score for c in global_candidates]
    base_semantic_floor = {
        PromptType.GENRE: 0.22,
        PromptType.MIXED: 0.20,
        PromptType.ARC: 0.16,
    }.get(intent.prompt_type, 0.20)
    percentile_floor = float(np.percentile(semantic_values, 30)) if semantic_values else 0.0
    semantic_floor = min(0.40, max(base_semantic_floor, percentile_floor))

    global_max_playcount = max((c.playcount for c in global_candidates), default=1)
    global_max_listeners = max((c.listeners for c in global_candidates), default=1)
    artist_maxima: dict[str, tuple[int, int]] = {}
    for candidate in global_candidates:
        if not candidate.artist_id:
            continue
        existing_playcount, existing_listeners = artist_maxima.get(candidate.artist_id, (0, 0))
        artist_maxima[candidate.artist_id] = (
            max(existing_playcount, candidate.playcount),
            max(existing_listeners, candidate.listeners),
        )

    staged_candidates: list[CandidateTrack] = []
    for track in global_candidates:
        year_score = 0.0
        if year_midpoint is not None and track.year:
            distance = abs(track.year - year_midpoint)
            year_score = max(-0.12, 0.08 - distance * 0.01)

        genre_match = compute_genre_match_score(track, hint_set, primary_hint_set)
        negative_penalty = compute_negative_constraint_penalty(track, intent.avoid_keywords)
        tourist_penalty = compute_tourist_match_penalty(track.semantic_score, genre_match, semantic_floor)
        impact_score = compute_impact_score(
            track,
            artist_maxima,
            global_max_playcount,
            global_max_listeners,
            intent.impact_preference,
        )
        usage_penalty = usage_penalties.get(track.id, 0.0)

        staged_track = replace(
            track,
            year_score=year_score,
            genre_match_score=genre_match,
            impact_score=impact_score,
            negative_constraint_penalty=negative_penalty,
            tourist_match_penalty=tourist_penalty,
            usage_penalty=usage_penalty,
            _w_semantic=w_semantic,
            _w_trajectory=w_trajectory,
            _w_genre=w_genre,
            _w_gravity=w_gravity,
            _w_duration=w_duration,
            _w_impact=w_impact,
        )
        staged_track = replace(
            staged_track,
            admissibility_score=compute_admissibility_score(staged_track, semantic_floor),
        )
        staged_candidates.append(staged_track)

    admissible_candidates = [
        track for track in staged_candidates
        if track.semantic_score >= semantic_floor
        and track.admissibility_score >= 0.35
        and track.negative_constraint_penalty < 0.45
    ]

    if not admissible_candidates:
        logger.warning("Admissibility gate removed all candidates; falling back to top semantic matches")
        staged_candidates.sort(key=lambda track: track.semantic_score, reverse=True)
        admissible_candidates = staged_candidates[:max(pool_size, intent.target_size * 3)]

    logger.info(
        f"Admissibility gate kept {len(admissible_candidates)}/{len(global_candidates)} candidates "
        f"(semantic_floor={semantic_floor:.3f})"
    )

    position_pools: list[list[CandidateTrack]] = []
    prev_duration: int | None = None
    # Pool caching: reuse same pool when trajectory target hasn't changed
    # significantly. For steady arcs all positions produce identical pools;
    # for other arcs nearby positions produce near-identical pools.
    last_pool: list[CandidateTrack] | None = None
    last_target_vec: tuple[float, ...] | None = None
    POOL_REUSE_THRESHOLD = 0.01  # reuse if all dimensions within 1%

    for position in range(intent.target_size):
        # Get trajectory target at this position
        t_norm = position / (intent.target_size - 1) if intent.target_size > 1 else 0.5
        target = intent.trajectory_curve.evaluate(t_norm)

        # Check if we can reuse the last pool
        target_vec = (target.energy, target.tempo, target.darkness, target.texture)
        if (last_target_vec is not None and last_pool is not None and
                all(abs(a - b) < POOL_REUSE_THRESHOLD for a, b in zip(target_vec, last_target_vec))):
            position_pools.append(last_pool)
            continue

        # Score all candidates for this position
        scored_candidates: list[tuple[CandidateTrack, float]] = []

        for track in admissible_candidates:
            # Trajectory match
            traj_score = score_trajectory_match(track, target, intent.dimension_weights)

            # Gravity penalty
            grav_penalty = compute_gravity_penalty(
                track.embedding, anchors, position=t_norm
            ) if track.embedding else 0.0

            # Duration penalty
            dur_penalty = score_duration_compatibility(
                track.duration_ms, prev_duration
            )

            scored_track = replace(
                track,
                trajectory_score=traj_score,
                gravity_penalty=grav_penalty,
                duration_penalty=dur_penalty,
                _w_semantic=w_semantic,
                _w_trajectory=w_trajectory,
                _w_genre=w_genre,
                _w_gravity=w_gravity,
                _w_duration=w_duration,
                _w_impact=w_impact,
            )

            total = scored_track.total_score
            scored_candidates.append((scored_track, total))

        # Sort by total score and take top pool_size
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        pool = [track for track, _ in scored_candidates[:pool_size]]
        position_pools.append(pool)

        # Cache for reuse by adjacent positions with similar targets
        last_pool = pool
        last_target_vec = target_vec

        # Update prev_duration for next position (use median of pool)
        if pool:
            durations = sorted([tk.duration_ms for tk in pool if tk.duration_ms > 0])
            if durations:
                prev_duration = durations[len(durations) // 2]

    pools_reused = sum(1 for i in range(1, len(position_pools))
                       if position_pools[i] is position_pools[i-1])
    logger.info(f"Generated {len(position_pools)} position pools, size={pool_size}"
                f" ({pools_reused} reused from adjacent)")
    return position_pools


def get_top_semantic_matches(
    prompt_embedding: list[float],
    limit: int = 20,
) -> tuple[list[list[float]], list[float]]:
    """
    Get top semantic matches for computing scene anchor.

    Returns:
        Tuple of (embeddings, scores)
    """
    candidates = semantic_search(prompt_embedding, limit=limit)

    embeddings = [c.embedding for c in candidates if c.embedding]
    scores = [c.semantic_score for c in candidates if c.embedding]

    return embeddings, scores
