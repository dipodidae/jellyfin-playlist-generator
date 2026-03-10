"""
Playlist composer - selects and orders tracks to match a trajectory.

Uses embeddings, artist similarity, and energy estimation to:
1. Find candidate tracks matching the intent
2. Score candidates for each trajectory phase
3. Compose final playlist with smooth transitions
"""

import logging
import random
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.database import get_connection
from app.trajectory.intent import PlaylistIntent, TrajectoryWaypoint

logger = logging.getLogger(__name__)


@dataclass
class ScoredTrack:
    """A track with its relevance scores."""
    id: str
    title: str
    artist_name: str
    artist_id: str | None
    album_name: str
    year: int | None
    duration_ms: int
    embedding: list[float] | None
    
    # Scores
    semantic_score: float = 0.0      # Embedding similarity to intent
    genre_score: float = 0.0         # Genre/tag match
    artist_score: float = 0.0        # Artist similarity to seeds
    energy_score: float = 0.0        # Energy level match
    diversity_penalty: float = 0.0   # Penalty for too similar to selected
    
    @property
    def total_score(self) -> float:
        return (
            self.semantic_score * 0.4 +
            self.genre_score * 0.2 +
            self.artist_score * 0.2 +
            self.energy_score * 0.2 -
            self.diversity_penalty
        )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def get_candidate_tracks(
    intent: PlaylistIntent,
    limit: int = 500,
) -> list[ScoredTrack]:
    """Fetch candidate tracks from the database."""
    conn = get_connection()
    
    # Build query with optional filters
    query = """
        SELECT 
            t.id, t.title, t.artist_name, t.artist_id, t.album_name, t.year, t.duration_ms,
            te.embedding
        FROM tracks t
        LEFT JOIN track_embeddings te ON t.id = te.track_id
        WHERE 1=1
    """
    params = []
    
    # Year filter
    if intent.year_range[0]:
        query += " AND t.year >= ?"
        params.append(intent.year_range[0])
    if intent.year_range[1]:
        query += " AND t.year <= ?"
        params.append(intent.year_range[1])
    
    # Prefer tracks with embeddings
    query += " ORDER BY te.embedding IS NOT NULL DESC, RANDOM()"
    query += f" LIMIT {limit}"
    
    results = conn.execute(query, params).fetchall()
    conn.close()
    
    candidates = []
    for row in results:
        embedding = row[7] if row[7] else None
        candidates.append(ScoredTrack(
            id=row[0],
            title=row[1],
            artist_name=row[2] or "Unknown",
            artist_id=row[3],
            album_name=row[4] or "Unknown",
            year=row[5],
            duration_ms=row[6] or 0,
            embedding=embedding,
        ))
    
    logger.info(f"Found {len(candidates)} candidate tracks")
    return candidates


def get_artist_similarity_map(artist_ids: list[str]) -> dict[str, dict[str, float]]:
    """Get similarity scores between artists."""
    if not artist_ids:
        return {}
    
    conn = get_connection()
    
    placeholders = ",".join(["?" for _ in artist_ids])
    results = conn.execute(f"""
        SELECT artist_id, similar_artist_id, similarity
        FROM artist_similarity
        WHERE artist_id IN ({placeholders}) OR similar_artist_id IN ({placeholders})
    """, artist_ids + artist_ids).fetchall()
    
    conn.close()
    
    similarity_map: dict[str, dict[str, float]] = {}
    for artist_id, similar_id, similarity in results:
        if artist_id not in similarity_map:
            similarity_map[artist_id] = {}
        similarity_map[artist_id][similar_id] = similarity
        
        # Bidirectional
        if similar_id not in similarity_map:
            similarity_map[similar_id] = {}
        similarity_map[similar_id][artist_id] = similarity
    
    return similarity_map


def get_artist_ids_by_name(artist_names: list[str]) -> list[str]:
    """Look up artist IDs by name."""
    if not artist_names:
        return []
    
    conn = get_connection()
    placeholders = ",".join(["?" for _ in artist_names])
    results = conn.execute(f"""
        SELECT id FROM artists WHERE LOWER(name) IN ({placeholders})
    """, [n.lower() for n in artist_names]).fetchall()
    conn.close()
    
    return [r[0] for r in results]


def score_candidates(
    candidates: list[ScoredTrack],
    intent: PlaylistIntent,
    waypoint: TrajectoryWaypoint,
) -> list[ScoredTrack]:
    """Score candidates for a specific trajectory waypoint."""
    
    # Get seed artist IDs for similarity scoring
    seed_artist_ids = get_artist_ids_by_name(intent.artist_seeds)
    artist_similarity = get_artist_similarity_map(seed_artist_ids)
    
    for track in candidates:
        # Semantic score (embedding similarity)
        if track.embedding and waypoint.mood_embedding:
            track.semantic_score = cosine_similarity(track.embedding, waypoint.mood_embedding)
        elif track.embedding and intent.prompt_embedding:
            track.semantic_score = cosine_similarity(track.embedding, intent.prompt_embedding)
        else:
            track.semantic_score = 0.3  # Default for tracks without embeddings
        
        # Artist similarity score
        if track.artist_id and seed_artist_ids:
            max_sim = 0.0
            for seed_id in seed_artist_ids:
                if seed_id in artist_similarity and track.artist_id in artist_similarity[seed_id]:
                    max_sim = max(max_sim, artist_similarity[seed_id][track.artist_id])
                # Direct match
                if track.artist_id == seed_id:
                    max_sim = 1.0
            track.artist_score = max_sim
        
        # Energy score (estimated from various signals)
        # This is a simplified heuristic - could be improved with audio features
        energy_estimate = estimate_track_energy(track, intent)
        energy_diff = abs(energy_estimate - waypoint.energy)
        track.energy_score = max(0, 1 - energy_diff)
    
    return candidates


def estimate_track_energy(track: ScoredTrack, intent: PlaylistIntent) -> float:
    """Estimate a track's energy level (0-1) based on available metadata."""
    # This is a heuristic - ideally we'd have audio features
    energy = 0.5  # Default middle energy
    
    # Genre-based energy hints
    title_lower = track.title.lower()
    artist_lower = track.artist_name.lower()
    
    high_energy_signals = ["fast", "heavy", "thrash", "death", "grind", "power", "speed"]
    low_energy_signals = ["ambient", "drone", "slow", "acoustic", "quiet", "soft"]
    
    for signal in high_energy_signals:
        if signal in title_lower or signal in artist_lower:
            energy += 0.2
    
    for signal in low_energy_signals:
        if signal in title_lower or signal in artist_lower:
            energy -= 0.2
    
    # Duration hint (longer tracks often lower energy, but not always)
    if track.duration_ms:
        if track.duration_ms > 600000:  # > 10 minutes
            energy -= 0.1
        elif track.duration_ms < 180000:  # < 3 minutes
            energy += 0.1
    
    return max(0.0, min(1.0, energy))


def calculate_diversity_penalty(
    track: ScoredTrack,
    selected: list[ScoredTrack],
    artist_weight: float = 0.3,
    embedding_weight: float = 0.2,
) -> float:
    """Calculate penalty for selecting a track too similar to already selected."""
    if not selected:
        return 0.0
    
    penalty = 0.0
    
    # Artist repetition penalty
    recent_artists = [t.artist_id for t in selected[-5:] if t.artist_id]
    if track.artist_id in recent_artists:
        # Higher penalty for more recent repetition
        recency = len(recent_artists) - recent_artists[::-1].index(track.artist_id)
        penalty += artist_weight * (recency / len(recent_artists))
    
    # Embedding similarity penalty (avoid too similar consecutive tracks)
    if track.embedding and selected:
        for prev_track in selected[-3:]:
            if prev_track.embedding:
                sim = cosine_similarity(track.embedding, prev_track.embedding)
                if sim > 0.8:  # Very similar
                    penalty += embedding_weight * (sim - 0.8) * 5
    
    return penalty


def compose_playlist(
    intent: PlaylistIntent,
    candidate_pool_size: int = 500,
) -> list[ScoredTrack]:
    """Compose a playlist matching the intent trajectory."""
    logger.info(f"Composing playlist: {intent.target_size} tracks, arc={intent.arc_type}")
    
    # Get candidate tracks
    candidates = get_candidate_tracks(intent, limit=candidate_pool_size)
    
    if not candidates:
        logger.warning("No candidate tracks found")
        return []
    
    selected: list[ScoredTrack] = []
    target_size = intent.target_size
    
    # Assign tracks to trajectory phases
    tracks_per_phase = max(1, target_size // len(intent.waypoints))
    
    for phase_idx, waypoint in enumerate(intent.waypoints):
        # Score candidates for this phase
        scored = score_candidates(candidates.copy(), intent, waypoint)
        
        # Determine how many tracks for this phase
        if phase_idx == len(intent.waypoints) - 1:
            # Last phase gets remaining tracks
            phase_target = target_size - len(selected)
        else:
            phase_target = tracks_per_phase
        
        # Select tracks for this phase
        for _ in range(phase_target):
            if not scored:
                break
            
            # Update diversity penalties
            for track in scored:
                track.diversity_penalty = calculate_diversity_penalty(track, selected)
            
            # Sort by total score
            scored.sort(key=lambda t: t.total_score, reverse=True)
            
            # Temperature-based selection (add some randomness)
            temperature = 0.3
            top_k = min(10, len(scored))
            weights = [np.exp(scored[i].total_score / temperature) for i in range(top_k)]
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]
            
            # Weighted random selection from top candidates
            idx = random.choices(range(top_k), weights=weights)[0]
            selected_track = scored.pop(idx)
            selected.append(selected_track)
            
            # Remove from candidates to avoid re-selection
            candidates = [c for c in candidates if c.id != selected_track.id]
            scored = [s for s in scored if s.id != selected_track.id]
    
    logger.info(f"Composed playlist with {len(selected)} tracks")
    return selected


def smooth_transitions(playlist: list[ScoredTrack]) -> list[ScoredTrack]:
    """Reorder playlist for smoother transitions between adjacent tracks."""
    if len(playlist) <= 2:
        return playlist
    
    # Keep first and last tracks fixed (anchor points)
    first = playlist[0]
    last = playlist[-1]
    middle = playlist[1:-1]
    
    if not middle:
        return playlist
    
    # Simple greedy reordering based on embedding similarity
    reordered = [first]
    remaining = middle.copy()
    
    while remaining:
        current = reordered[-1]
        
        if current.embedding:
            # Find most similar track
            best_idx = 0
            best_sim = -1
            
            for i, track in enumerate(remaining):
                if track.embedding:
                    sim = cosine_similarity(current.embedding, track.embedding)
                    # Balance similarity with avoiding too much similarity
                    adjusted_sim = sim if sim < 0.9 else sim - 0.2
                    if adjusted_sim > best_sim:
                        best_sim = adjusted_sim
                        best_idx = i
            
            reordered.append(remaining.pop(best_idx))
        else:
            # No embedding, just take next
            reordered.append(remaining.pop(0))
    
    reordered.append(last)
    return reordered
