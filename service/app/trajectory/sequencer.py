"""
Beam search sequencer for playlist path optimization.

Implements the v4 architecture:
1. Beam search through position-based candidate pools
2. Path constraints (no duplicates, artist distance, cluster limits)
3. Transition scoring with lookahead
4. Beam diversity to prevent collapse
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.trajectory.candidates import CandidateTrack
from app.trajectory.gravity import compute_bridge_bonus

logger = logging.getLogger(__name__)


@dataclass
class SequencerConfig:
    """Configuration for beam search sequencer."""
    beam_width: int = 12
    min_artist_distance: int = 6
    max_cluster_per_window: int = 2
    cluster_window_size: int = 10
    max_duration_ratio: float = 2.5
    lookahead_weight: float = 0.3
    bridge_bonus_weight: float = 0.05
    diversity_threshold: float = 0.8


@dataclass
class BeamPath:
    """A path through candidate pools with cumulative score."""
    tracks: list[CandidateTrack] = field(default_factory=list)
    cumulative_score: float = 0.0

    # Tracking for constraints
    artist_positions: dict[str, int] = field(default_factory=dict)  # artist_id -> last position
    cluster_counts: dict[int, int] = field(default_factory=dict)  # cluster_id -> count in window

    def copy(self) -> "BeamPath":
        """Create a copy of this path."""
        return BeamPath(
            tracks=self.tracks.copy(),
            cumulative_score=self.cumulative_score,
            artist_positions=self.artist_positions.copy(),
            cluster_counts=self.cluster_counts.copy(),
        )

    def cluster_sequence(self) -> list[int | None]:
        """Get sequence of cluster IDs for diversity comparison."""
        return [t.cluster_id for t in self.tracks]


def cosine_similarity(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a) if not isinstance(a, np.ndarray) else a
    b_arr = np.array(b) if not isinstance(b, np.ndarray) else b

    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def is_valid_extension(
    path: BeamPath,
    candidate: CandidateTrack,
    position: int,
    config: SequencerConfig,
) -> bool:
    """
    Check if candidate is a valid extension of the path.

    Enforces hard constraints:
    - No duplicate tracks
    - Minimum artist distance
    - Maximum cluster repetition in window
    - Maximum duration ratio
    """
    # No duplicate tracks
    track_ids = {t.id for t in path.tracks}
    if candidate.id in track_ids:
        return False

    # Artist distance constraint
    if candidate.artist_id and candidate.artist_id in path.artist_positions:
        last_pos = path.artist_positions[candidate.artist_id]
        if position - last_pos < config.min_artist_distance:
            return False

    # Cluster repetition constraint
    if candidate.cluster_id is not None:
        # Count cluster occurrences in recent window
        window_start = max(0, position - config.cluster_window_size)
        window_clusters = [t.cluster_id for t in path.tracks[window_start:]]
        cluster_count = window_clusters.count(candidate.cluster_id)
        if cluster_count >= config.max_cluster_per_window:
            return False

    # Duration ratio constraint
    if path.tracks and candidate.duration_ms > 0:
        prev_duration = path.tracks[-1].duration_ms
        if prev_duration > 0:
            ratio = max(candidate.duration_ms, prev_duration) / min(candidate.duration_ms, prev_duration)
            if ratio > config.max_duration_ratio:
                return False

    return True


def score_transition(
    prev_track: CandidateTrack | None,
    curr_track: CandidateTrack,
) -> float:
    """
    Score the transition between two tracks.

    Returns normalized score in [0, 1] where 1 = smooth transition.
    """
    if prev_track is None:
        return 0.5  # Neutral for first track

    scores = []

    # Energy continuity
    energy_diff = abs(prev_track.energy - curr_track.energy)
    scores.append(1.0 - min(energy_diff, 0.5) * 2)  # Normalize to [0, 1]

    # Tempo continuity
    tempo_diff = abs(prev_track.tempo - curr_track.tempo)
    scores.append(1.0 - min(tempo_diff, 0.5) * 2)

    # Embedding similarity (if available)
    if prev_track.embedding and curr_track.embedding:
        sim = cosine_similarity(prev_track.embedding, curr_track.embedding)
        # Prefer moderate similarity (0.5-0.8), penalize too similar or too different
        if sim > 0.9:
            scores.append(0.7)  # Too similar
        elif sim < 0.3:
            scores.append(0.5)  # Too different
        else:
            scores.append(sim)

    # Duration pacing
    if prev_track.duration_ms > 0 and curr_track.duration_ms > 0:
        ratio = max(prev_track.duration_ms, curr_track.duration_ms) / min(prev_track.duration_ms, curr_track.duration_ms)
        if ratio <= 1.5:
            scores.append(1.0)
        elif ratio >= 2.5:
            scores.append(0.5)
        else:
            scores.append(1.0 - (ratio - 1.5) / 2)

    # Genre continuity (prevents style cliff-jumps e.g. thrash → doom)
    if prev_track.genres and curr_track.genres:
        shared = set(prev_track.genres) & set(curr_track.genres)
        genre_score = 0.5
        if shared:
            genre_score += 0.15
            if len(shared) > 1:
                genre_score += 0.10
        else:
            genre_score -= 0.10
        scores.append(min(1.0, max(0.0, genre_score)))

    # Acoustic continuity (only when both tracks have audio features)
    if (
        prev_track.bpm_norm is not None and curr_track.bpm_norm is not None
        and prev_track.loudness_norm is not None and curr_track.loudness_norm is not None
        and prev_track.brightness_norm is not None and curr_track.brightness_norm is not None
    ):
        bpm_score = 1.0 - min(abs(prev_track.bpm_norm - curr_track.bpm_norm) * 2, 1.0)
        loudness_score = 1.0 - min(abs(prev_track.loudness_norm - curr_track.loudness_norm) * 2, 1.0)
        brightness_score = 1.0 - min(abs(prev_track.brightness_norm - curr_track.brightness_norm) * 2, 1.0)
        acoustic_score = bpm_score * 0.4 + loudness_score * 0.4 + brightness_score * 0.2
        scores.append(acoustic_score)

    return sum(scores) / len(scores) if scores else 0.5


def compute_lookahead(
    candidate: CandidateTrack,
    next_pool: list[CandidateTrack] | None,
    config: SequencerConfig,
) -> float:
    """
    Compute average compatibility with next position's pool.

    Helps avoid dead-end transitions.
    """
    if not next_pool or not candidate.embedding:
        return 0.5

    compatibilities = []
    for next_track in next_pool[:10]:  # Sample top 10
        if next_track.embedding:
            sim = cosine_similarity(candidate.embedding, next_track.embedding)
            compatibilities.append(sim)

    return sum(compatibilities) / len(compatibilities) if compatibilities else 0.5


def cluster_sequence_similarity(seq1: list[int | None], seq2: list[int | None]) -> float:
    """
    Compute similarity between two cluster sequences.

    Used for beam diversity.
    """
    if not seq1 or not seq2:
        return 0.0

    min_len = min(len(seq1), len(seq2))
    if min_len == 0:
        return 0.0

    matches = sum(1 for a, b in zip(seq1, seq2) if a == b and a is not None)
    return matches / min_len


def select_diverse_beam(
    candidates: list[tuple[BeamPath, float]],
    width: int,
    diversity_threshold: float = 0.8,
) -> list[BeamPath]:
    """
    Select top paths while maintaining diversity.

    Prevents beam collapse into single style.
    """
    if not candidates:
        return []

    # Sort by score
    sorted_candidates = sorted(candidates, key=lambda x: x[1], reverse=True)

    selected: list[BeamPath] = []

    for path, score in sorted_candidates:
        if len(selected) >= width:
            break

        # Check diversity against already selected
        is_diverse = True
        if selected:
            path_seq = path.cluster_sequence()
            for existing in selected:
                existing_seq = existing.cluster_sequence()
                if cluster_sequence_similarity(path_seq, existing_seq) > diversity_threshold:
                    is_diverse = False
                    break

        # Always include top half, apply diversity filter to rest
        if is_diverse or len(selected) < width // 2:
            selected.append(path)

    return selected


def sequence_playlist(
    position_pools: list[list[CandidateTrack]],
    config: SequencerConfig | None = None,
    cluster_centroids: list[np.ndarray] | None = None,
    cluster_ids: list[int] | None = None,
    transition_bonuses: dict | None = None,
) -> list[CandidateTrack]:
    """
    Sequence playlist using beam search through position pools.

    This is the core v4 sequencing algorithm.
    """
    if not position_pools:
        return []

    if config is None:
        config = SequencerConfig()

    # Initialize beam with empty path
    beam: list[BeamPath] = [BeamPath()]

    for position, candidates in enumerate(position_pools):
        new_candidates: list[tuple[BeamPath, float]] = []

        # Get next pool for lookahead
        next_pool = position_pools[position + 1] if position + 1 < len(position_pools) else None

        for path in beam:
            for candidate in candidates:
                # Check constraints
                if not is_valid_extension(path, candidate, position, config):
                    continue

                # Compute scores
                prev_track = path.tracks[-1] if path.tracks else None
                trans_score = score_transition(prev_track, candidate)
                lookahead = compute_lookahead(candidate, next_pool, config)

                # Bridge bonus (if cluster info available)
                bridge_bonus = 0.0
                if cluster_centroids and cluster_ids and prev_track:
                    bridge_bonus = compute_bridge_bonus(
                        candidate.embedding,
                        cluster_centroids,
                        cluster_ids,
                        prev_track.cluster_id,
                        candidate.cluster_id,
                    )

                # Historical transition bonus (0–0.05, from transition memory)
                trans_bonus = 0.0
                if transition_bonuses and prev_track:
                    trans_bonus = transition_bonuses.get(
                        (str(prev_track.id), str(candidate.id)), 0.0
                    )

                # Total score for this extension
                extension_score = (
                    candidate.total_score +
                    trans_score * 0.2 +
                    lookahead * config.lookahead_weight +
                    bridge_bonus * config.bridge_bonus_weight +
                    trans_bonus
                )

                # Create new path
                new_path = path.copy()
                new_path.tracks.append(candidate)
                new_path.cumulative_score = path.cumulative_score + extension_score

                # Update tracking
                if candidate.artist_id:
                    new_path.artist_positions[candidate.artist_id] = position
                if candidate.cluster_id is not None:
                    new_path.cluster_counts[candidate.cluster_id] = \
                        new_path.cluster_counts.get(candidate.cluster_id, 0) + 1

                new_candidates.append((new_path, new_path.cumulative_score))

        # Select diverse beam
        if new_candidates:
            beam = select_diverse_beam(new_candidates, config.beam_width, config.diversity_threshold)
        else:
            logger.warning(f"No valid candidates at position {position}")
            # Keep current beam, will result in shorter playlist
            break

    if not beam:
        logger.error("Beam search produced no results")
        return []

    # Return best path
    best_path = max(beam, key=lambda p: p.cumulative_score)
    logger.info(f"Sequenced playlist: {len(best_path.tracks)} tracks, score={best_path.cumulative_score:.2f}")

    return best_path.tracks


def compute_playlist_metrics(
    playlist: list[CandidateTrack],
    position_pools: list[list[CandidateTrack]],
) -> dict[str, Any]:
    """
    Compute metrics for observability.
    """
    if not playlist:
        return {}

    # Trajectory deviation
    deviations = []
    for i, track in enumerate(playlist):
        if i < len(position_pools):
            pool = position_pools[i]
            if pool:
                best_traj = max(t.trajectory_score for t in pool)
                deviations.append(best_traj - track.trajectory_score)

    avg_deviation = sum(deviations) / len(deviations) if deviations else 0.0

    # Transition costs
    trans_costs = []
    for i in range(1, len(playlist)):
        cost = 1.0 - score_transition(playlist[i-1], playlist[i])
        trans_costs.append(cost)

    avg_trans_cost = sum(trans_costs) / len(trans_costs) if trans_costs else 0.0

    # Pool entropy (cluster diversity)
    if position_pools:
        entropies = []
        for pool in position_pools:
            clusters = [t.cluster_id for t in pool if t.cluster_id is not None]
            if clusters:
                from collections import Counter
                counts = Counter(clusters)
                total = len(clusters)
                probs = [c / total for c in counts.values()]
                entropy = -sum(p * math.log(p) for p in probs if p > 0)
                entropies.append(entropy)
        pool_entropy = sum(entropies) / len(entropies) if entropies else 0.0
    else:
        pool_entropy = 0.0

    return {
        "trajectory_deviation": avg_deviation,
        "avg_transition_cost": avg_trans_cost,
        "pool_entropy": pool_entropy,
        "playlist_length": len(playlist),
    }
