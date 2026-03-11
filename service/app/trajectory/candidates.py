"""
Position-based candidate pool generation.

Implements the v4 architecture:
1. Single semantic search for global candidate pool
2. Re-score candidates per playlist position against trajectory target
3. Adaptive pool sizing based on library size
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.database_pg import get_connection
from app.trajectory.curves import TrajectoryPoint
from app.trajectory.gravity import GravityAnchors, compute_gravity_penalty
from app.trajectory.intent import PlaylistIntent, DimensionWeights

logger = logging.getLogger(__name__)


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
    
    # Scoring components (all normalized 0-1)
    semantic_score: float = 0.0
    trajectory_score: float = 0.0
    gravity_penalty: float = 0.0
    duration_penalty: float = 0.0
    
    # Computed total
    _total_score: float | None = None
    
    @property
    def total_score(self) -> float:
        """Compute total score with v4 weights."""
        if self._total_score is not None:
            return self._total_score
        
        # v4 scoring formula (normalized components)
        return (
            self.semantic_score * 0.25 +
            self.trajectory_score * 0.35 -
            self.gravity_penalty * 0.15 -
            self.duration_penalty * 0.10
        )
    
    def profile_array(self) -> np.ndarray:
        """Return profile as numpy array."""
        return np.array([self.energy, self.tempo, self.darkness, self.texture])


def get_adaptive_pool_size(library_size: int) -> int:
    """Calculate adaptive pool size based on library size."""
    size = int(math.sqrt(library_size) * 1.5)
    return max(25, min(80, size))


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
            # Build query with optional year filter
            year_filter = ""
            params = [embedding_array.tolist()]
            
            if year_range[0]:
                year_filter += " AND t.year >= %s"
                params.append(year_range[0])
            if year_range[1]:
                year_filter += " AND t.year <= %s"
                params.append(year_range[1])
            
            params.append(limit)
            
            # Query with semantic similarity ordering
            cur.execute(f"""
                SELECT 
                    t.id, t.title, t.artist_name, t.artist_id, t.album_name, 
                    t.year, t.duration_ms,
                    te.embedding,
                    tp.energy, tp.darkness, tp.tempo, tp.texture,
                    tf.file_path,
                    1 - (te.embedding <=> %s::vector) as similarity
                FROM tracks t
                LEFT JOIN track_embeddings te ON t.id = te.track_id
                LEFT JOIN track_profiles tp ON t.id = tp.track_id
                LEFT JOIN track_files tf ON t.id = tf.track_id
                WHERE te.embedding IS NOT NULL
                {year_filter}
                ORDER BY te.embedding <=> %s::vector
                LIMIT %s
            """, params[:1] + params + [embedding_array.tolist()])
            
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
            embedding=row[7] if row[7] else None,
            energy=row[8] if row[8] is not None else 0.5,
            darkness=row[9] if row[9] is not None else 0.5,
            tempo=row[10] if row[10] is not None else 0.5,
            texture=row[11] if row[11] is not None else 0.5,
            file_path=row[12],
            semantic_score=row[13] if row[13] is not None else 0.0,
        ))
    
    logger.info(f"Semantic search returned {len(candidates)} candidates")
    return candidates


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


def generate_position_pools(
    intent: PlaylistIntent,
    anchors: GravityAnchors,
    pool_size: int | None = None,
) -> list[list[CandidateTrack]]:
    """
    Generate candidate pools for each playlist position.
    
    This is the core v4 algorithm:
    1. Single semantic search for global candidates
    2. Re-score each candidate per position against trajectory target
    3. Select top-k for each position pool
    """
    # Determine pool size
    if pool_size is None:
        library_size = get_library_size()
        pool_size = get_adaptive_pool_size(library_size)
    
    # Scale global search limit based on playlist size
    global_limit = min(400, pool_size * intent.target_size // 2)
    
    # Single semantic search
    global_candidates = semantic_search(
        intent.prompt_embedding,
        limit=global_limit,
        year_range=intent.year_range,
    )
    
    if not global_candidates:
        logger.warning("No candidates found in semantic search")
        return []
    
    position_pools: list[list[CandidateTrack]] = []
    prev_duration: int | None = None
    
    for position in range(intent.target_size):
        # Get trajectory target at this position
        t = position / (intent.target_size - 1) if intent.target_size > 1 else 0.5
        target = intent.trajectory_curve.evaluate(t)
        
        # Score all candidates for this position
        scored_candidates: list[tuple[CandidateTrack, float]] = []
        
        for track in global_candidates:
            # Trajectory match
            traj_score = score_trajectory_match(track, target, intent.dimension_weights)
            
            # Gravity penalty
            grav_penalty = compute_gravity_penalty(
                track.embedding, anchors, position=t
            ) if track.embedding else 0.0
            
            # Duration penalty
            dur_penalty = score_duration_compatibility(
                track.duration_ms, prev_duration
            )
            
            # Update track scores
            track.trajectory_score = traj_score
            track.gravity_penalty = grav_penalty
            track.duration_penalty = dur_penalty
            
            # Compute total for sorting
            total = track.total_score
            scored_candidates.append((track, total))
        
        # Sort by total score and take top pool_size
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        pool = [track for track, _ in scored_candidates[:pool_size]]
        position_pools.append(pool)
        
        # Update prev_duration for next position (use median of pool)
        if pool:
            durations = sorted([t.duration_ms for t in pool if t.duration_ms > 0])
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
