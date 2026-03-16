"""
Position-based candidate pool generation.

Implements the v4 architecture:
1. Single semantic search for global candidate pool
2. Re-score candidates per playlist position against trajectory target
3. Adaptive pool sizing based on library size
"""

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from app.database_pg import get_connection
from app.embeddings.generator import generate_embedding
from app.trajectory.curves import TrajectoryPoint
from app.trajectory.gravity import GravityAnchors, compute_gravity_penalty
from app.trajectory.intent import PlaylistIntent, DimensionWeights, ArcType, PromptType

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

    # Scoring components (all normalized 0-1)
    semantic_score: float = 0.0   # combined retrieval: 0.65*cosine + 0.35*keyword
    keyword_score: float = 0.0    # raw BM25 score (before normalization)
    trajectory_score: float = 0.0
    gravity_penalty: float = 0.0
    duration_penalty: float = 0.0
    year_score: float = 0.0       # soft year-range bonus/penalty
    genre_match_score: float = 0.0  # Jaccard(intent.genre_hints, track.genres)
    usage_penalty: float = 0.0     # time-decayed track usage penalty

    # Adaptive scoring weights (set per-prompt by generate_position_pools)
    _w_semantic: float = 0.25
    _w_trajectory: float = 0.35
    _w_genre: float = 0.20
    _w_gravity: float = 0.15
    _w_duration: float = 0.10

    @property
    def total_score(self) -> float:
        return (
            self.semantic_score * self._w_semantic +
            self.trajectory_score * self._w_trajectory +
            self.genre_match_score * self._w_genre +
            self.year_score -
            self.gravity_penalty * self._w_gravity -
            self.duration_penalty * self._w_duration -
            self.usage_penalty
        )

    def profile_array(self) -> np.ndarray:
        """Return profile as numpy array."""
        return np.array([self.energy, self.tempo, self.darkness, self.texture])


def get_adaptive_pool_size(library_size: int) -> int:
    """Calculate adaptive pool size based on library size."""
    size = int(math.sqrt(library_size) * 1.5)
    return max(50, min(180, size))


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
                    taf.bpm_norm, taf.loudness_norm, taf.brightness_norm
                FROM tracks t
                LEFT JOIN track_embeddings te ON t.id = te.track_id
                LEFT JOIN track_profiles tp ON t.id = tp.track_id
                LEFT JOIN track_files tf ON t.id = tf.track_id AND tf.missing_since IS NULL
                LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
                LEFT JOIN artists a ON ta.artist_id = a.id
                LEFT JOIN track_albums tal ON tal.track_id = t.id
                LEFT JOIN albums al ON tal.album_id = al.id
                LEFT JOIN track_audio_features taf ON t.id = taf.track_id
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
) -> list["CandidateTrack"]:
    """BM25 full-text search using Postgres tsvector / ts_rank."""
    expanded = expand_query(prompt)

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
                            plainto_tsquery('simple', %s)) AS keyword_score,
                    ARRAY(
                        SELECT g.name FROM track_genres tg2
                        JOIN genres g ON tg2.genre_id = g.id
                        WHERE tg2.track_id = t.id
                    ) AS genres,
                    taf.bpm_norm, taf.loudness_norm, taf.brightness_norm
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
                WHERE t.search_vector @@ plainto_tsquery('simple', %s)
                ORDER BY keyword_score DESC
                LIMIT %s
            """, (expanded, expanded, limit))
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
                    taf.bpm_norm, taf.loudness_norm, taf.brightness_norm
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
                WHERE t.id = ANY(%s)
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
            "semantic": 0.30,
            "trajectory": 0.15,
            "genre": 0.35,
            "gravity": 0.10,
            "duration": 0.10,
        }
    elif prompt_type == PromptType.ARC:
        return {
            "semantic": 0.25,
            "trajectory": 0.40,
            "genre": 0.10,
            "gravity": 0.15,
            "duration": 0.10,
        }
    else:  # MIXED
        return {
            "semantic": 0.25,
            "trajectory": 0.35,
            "genre": 0.20,
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
        pool_size = get_adaptive_pool_size(library_size)

    # Scale global search limit based on playlist size
    global_limit = min(400, pool_size * intent.target_size // 2)

    # Get adaptive scoring weights based on prompt type
    weights = get_adaptive_weights(intent.prompt_type)
    w_semantic = weights["semantic"]
    w_trajectory = weights["trajectory"]
    w_genre = weights["genre"]
    w_gravity = weights["gravity"]
    w_duration = weights["duration"]

    logger.info(f"Adaptive weights ({intent.prompt_type.value}): "
                f"sem={w_semantic}, traj={w_trajectory}, genre={w_genre}")

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
    try:
        kw_candidates = keyword_search(intent.raw_prompt, limit=200)
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
    if intent.genre_hints:
        patterns = [f"%{g}%" for g in intent.genre_hints]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT tg.track_id::text
                        FROM track_genres tg
                        JOIN genres g ON tg.genre_id = g.id
                        WHERE g.name ILIKE ANY(%s)
                        LIMIT 500
                    """, (patterns,))
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
    if intent.genre_hints:
        tag_patterns = [f"%{g}%" for g in intent.genre_hints]
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
                        LIMIT 500
                    """, (tag_patterns,))
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
    if yr0 and yr1 and intent.genre_hints:
        patterns = [f"%{g}%" for g in intent.genre_hints]
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
                        LIMIT 300
                    """, (yr0, yr1, patterns))
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

    # Precompute genre hint set for Jaccard scoring
    hint_set = {h.lower() for h in intent.genre_hints} if intent.genre_hints else set()
    # Also add canonical families for the hints so Jaccard is more generous
    from app.trajectory.intent import _ALIAS_TO_FAMILY
    for h in list(hint_set):
        fam = _ALIAS_TO_FAMILY.get(h)
        if fam:
            hint_set.add(fam)

    # Precompute year midpoint for soft year scoring
    year_midpoint: float | None = None
    if yr0 and yr1:
        year_midpoint = (yr0 + yr1) / 2.0

    position_pools: list[list[CandidateTrack]] = []
    prev_duration: int | None = None

    for position in range(intent.target_size):
        # Get trajectory target at this position
        t_norm = position / (intent.target_size - 1) if intent.target_size > 1 else 0.5
        target = intent.trajectory_curve.evaluate(t_norm)

        # Score all candidates for this position
        scored_candidates: list[tuple[CandidateTrack, float]] = []

        for track in global_candidates:
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

            # Soft year scoring (Fix 2)
            year_score = 0.0
            if year_midpoint is not None and track.year:
                distance = abs(track.year - year_midpoint)
                year_score = max(-0.12, 0.08 - distance * 0.01)

            # Genre Jaccard match score (Fix 6)
            genre_match = 0.0
            if hint_set and track.genres:
                genre_set = {g.lower() for g in track.genres}
                # Also add families for track genres
                for g in list(genre_set):
                    fam = _ALIAS_TO_FAMILY.get(g)
                    if fam:
                        genre_set.add(fam)
                intersection = hint_set & genre_set
                union = hint_set | genre_set
                genre_match = len(intersection) / len(union) if union else 0.0

            # Track usage penalty (playlist memory)
            u_penalty = usage_penalties.get(track.id, 0.0)

            scored_track = replace(
                track,
                trajectory_score=traj_score,
                gravity_penalty=grav_penalty,
                duration_penalty=dur_penalty,
                year_score=year_score,
                genre_match_score=genre_match,
                usage_penalty=u_penalty,
                _w_semantic=w_semantic,
                _w_trajectory=w_trajectory,
                _w_genre=w_genre,
                _w_gravity=w_gravity,
                _w_duration=w_duration,
            )

            total = scored_track.total_score
            scored_candidates.append((scored_track, total))

        # Sort by total score and take top pool_size
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        pool = [track for track, _ in scored_candidates[:pool_size]]
        position_pools.append(pool)

        # Update prev_duration for next position (use median of pool)
        if pool:
            durations = sorted([tk.duration_ms for tk in pool if tk.duration_ms > 0])
            if durations:
                prev_duration = durations[len(durations) // 2]

    logger.info(f"Generated {len(position_pools)} position pools, size={pool_size}")
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
