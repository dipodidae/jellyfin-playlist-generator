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
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import numpy as np

from app.trajectory.candidates import CandidateTrack
from app.trajectory.gravity import compute_bridge_bonus

logger = logging.getLogger(__name__)


@lru_cache(maxsize=4096)
def _normalize_artist(name: str | None) -> str | None:
    """Normalize artist name for comparison (strip accents, lowercase).

    This ensures variants like "Voivod" / "Voïvod" or "Znöwhite" / "Znowhite"
    are treated as the same artist in distance/penalty constraints.
    """
    if not name:
        return name
    # NFKD decomposition splits e.g. 'ï' into 'i' + combining diaeresis
    decomposed = unicodedata.normalize("NFKD", name)
    # Strip combining characters (accents)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


@dataclass
class SequencerConfig:
    """Configuration for beam search sequencer."""
    beam_width: int = 12
    min_artist_distance: int = 4
    max_cluster_per_window: int = 8
    cluster_window_size: int = 10
    max_duration_ratio: float = 3.0
    lookahead_weight: float = 0.3
    bridge_bonus_weight: float = 0.05
    diversity_threshold: float = 0.8


@dataclass
class BeamPath:
    """A path through candidate pools with cumulative score."""
    tracks: list[CandidateTrack] = field(default_factory=list)
    cumulative_score: float = 0.0

    # Tracking for constraints (keyed by normalized artist name, not ID)
    artist_positions: dict[str, int] = field(default_factory=dict)  # norm_artist -> last position
    artist_counts: dict[str, int] = field(default_factory=dict)     # norm_artist -> total appearances
    cluster_counts: dict[int, int] = field(default_factory=dict)  # cluster_id -> count in window
    track_ids: set = field(default_factory=set)  # track IDs for O(1) duplicate check

    def copy(self) -> "BeamPath":
        """Create a copy of this path."""
        return BeamPath(
            tracks=self.tracks.copy(),
            cumulative_score=self.cumulative_score,
            artist_positions=self.artist_positions.copy(),
            artist_counts=self.artist_counts.copy(),
            cluster_counts=self.cluster_counts.copy(),
            track_ids=self.track_ids.copy(),
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
    pool_cluster_counts: dict[int | None, int] | None = None,
) -> bool:
    """
    Check if candidate is a valid extension of the path.

    Enforces hard constraints:
    - No duplicate tracks
    - Minimum artist distance
    - Maximum cluster repetition in window (adaptive based on pool diversity)
    - Maximum duration ratio
    """
    # No duplicate tracks (use pre-built set for O(1) lookup)
    if candidate.id in path.track_ids:
        return False

    # Artist distance constraint (use normalized name for accent-insensitive matching)
    norm_artist = _normalize_artist(candidate.artist_name)
    if norm_artist and norm_artist in path.artist_positions:
        last_pos = path.artist_positions[norm_artist]
        if position - last_pos < config.min_artist_distance:
            return False

    # Cluster repetition constraint (adaptive)
    if candidate.cluster_id is not None:
        # Count cluster occurrences in recent window
        window_start = max(0, position - config.cluster_window_size)
        window_clusters = [t.cluster_id for t in path.tracks[window_start:]]
        cluster_count = window_clusters.count(candidate.cluster_id)

        # Adapt the limit based on pool cluster diversity:
        # If >80% of the pool is one cluster, allow up to window_size - 2
        # so we only reserve 2 slots for other clusters.
        max_allowed = config.max_cluster_per_window
        if pool_cluster_counts and candidate.cluster_id in pool_cluster_counts:
            pool_total = sum(pool_cluster_counts.values())
            if pool_total > 0:
                dominant_fraction = pool_cluster_counts[candidate.cluster_id] / pool_total
                if dominant_fraction > 0.8:
                    max_allowed = max(config.max_cluster_per_window,
                                      config.cluster_window_size - 2)
                elif dominant_fraction > 0.5:
                    max_allowed = max(config.max_cluster_per_window,
                                      config.cluster_window_size - 4)

        if cluster_count >= max_allowed:
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


def _relaxed_config(base: SequencerConfig, level: int) -> SequencerConfig:
    """Return a progressively relaxed copy of *base* for constraint fallback.

    Level 0 = normal (no relaxation).
    Level 1 = moderate: halve artist distance, increase cluster limit.
    Level 2 = aggressive: artist distance 1, cluster nearly unconstrained.
    Level 3 = emergency: no artist distance, no cluster limit, no duration limit.
    """
    if level <= 0:
        return base
    if level == 1:
        return SequencerConfig(
            beam_width=base.beam_width,
            min_artist_distance=max(2, base.min_artist_distance // 2),
            max_cluster_per_window=base.cluster_window_size - 1,
            cluster_window_size=base.cluster_window_size,
            max_duration_ratio=5.0,
            lookahead_weight=base.lookahead_weight,
            bridge_bonus_weight=base.bridge_bonus_weight,
            diversity_threshold=base.diversity_threshold,
        )
    if level == 2:
        return SequencerConfig(
            beam_width=base.beam_width,
            min_artist_distance=1,
            max_cluster_per_window=base.cluster_window_size,
            cluster_window_size=base.cluster_window_size,
            max_duration_ratio=10.0,
            lookahead_weight=base.lookahead_weight,
            bridge_bonus_weight=base.bridge_bonus_weight,
            diversity_threshold=1.0,  # disable diversity filter
        )
    # level >= 3: emergency — basically no constraints except no duplicates
    return SequencerConfig(
        beam_width=base.beam_width,
        min_artist_distance=0,
        max_cluster_per_window=999,
        cluster_window_size=base.cluster_window_size,
        max_duration_ratio=999.0,
        lookahead_weight=base.lookahead_weight,
        bridge_bonus_weight=base.bridge_bonus_weight,
        diversity_threshold=1.0,
    )


MAX_RELAXATION_LEVELS = 4  # 0..3


def _precompute_candidate_artists(
    candidates: list[CandidateTrack],
) -> list[str | None]:
    """Pre-normalize artist names for all candidates in a pool (once per position)."""
    return [_normalize_artist(c.artist_name) for c in candidates]


def _extend_single_path(
    path: BeamPath,
    candidates: list[CandidateTrack],
    candidate_artists: list[str | None],
    position: int,
    config: SequencerConfig,
    pool_cluster_counts: dict[int | None, int],
    next_pool: list[CandidateTrack] | None,
    cluster_centroids: list[np.ndarray] | None,
    cluster_ids: list[int] | None,
    transition_bonuses: dict | None,
    skip_lookahead: bool = False,
) -> tuple[list[tuple[BeamPath, float]], int]:
    """Extend one beam path at *position*.

    Returns (new_candidates, constraint_rejections).
    """
    new_candidates: list[tuple[BeamPath, float]] = []
    constraint_rejections = 0
    prev_track = path.tracks[-1] if path.tracks else None

    for idx, candidate in enumerate(candidates):
        if not is_valid_extension(path, candidate, position, config,
                                  pool_cluster_counts=pool_cluster_counts):
            constraint_rejections += 1
            continue

        trans_score = score_transition(prev_track, candidate)

        # Skip expensive lookahead at relaxed levels — diminishing returns
        if skip_lookahead:
            lookahead = 0.5  # neutral default
        else:
            lookahead = compute_lookahead(candidate, next_pool, config)

        bridge_bonus = 0.0
        if cluster_centroids and cluster_ids and prev_track and candidate.embedding:
            bridge_bonus = compute_bridge_bonus(
                candidate.embedding,
                cluster_centroids,
                cluster_ids,
                prev_track.cluster_id,
                candidate.cluster_id,
            )

        trans_bonus = 0.0
        if transition_bonuses and prev_track:
            trans_bonus = transition_bonuses.get(
                (str(prev_track.id), str(candidate.id)), 0.0
            )

        extension_score = (
            candidate.total_score +
            trans_score * 0.2 +
            lookahead * config.lookahead_weight +
            bridge_bonus * config.bridge_bonus_weight +
            trans_bonus
        )

        # Soft artist-reuse penalty: discourages the same artist from
        # dominating the playlist, even when the hard distance constraint
        # has been relaxed.  Uses pre-normalized artist name so accent
        # variants (Voivod/Voïvod) are treated as the same artist.
        norm_artist = candidate_artists[idx]
        if norm_artist and norm_artist in path.artist_positions:
            last_pos = path.artist_positions[norm_artist]
            distance = position - last_pos
            artist_count = path.artist_counts.get(norm_artist, 0)
            # Recency: 0.15 for immediate repeat, decaying with distance
            recency_penalty = 0.15 / max(1, distance)
            # Fatigue: accelerating penalty that grows quadratically.
            # 1 prior=0.03, 2=0.06, 3=0.11, 4=0.16, 5=0.22, 6+=0.30 cap
            fatigue_penalty = min(0.30, artist_count * artist_count * 0.015 + artist_count * 0.015)
            extension_score -= (recency_penalty + fatigue_penalty)

        new_path = path.copy()
        new_path.tracks.append(candidate)
        new_path.track_ids.add(candidate.id)
        new_path.cumulative_score = path.cumulative_score + extension_score

        if norm_artist:
            new_path.artist_positions[norm_artist] = position
            new_path.artist_counts[norm_artist] = \
                new_path.artist_counts.get(norm_artist, 0) + 1
        if candidate.cluster_id is not None:
            new_path.cluster_counts[candidate.cluster_id] = \
                new_path.cluster_counts.get(candidate.cluster_id, 0) + 1

        new_candidates.append((new_path, new_path.cumulative_score))

    return new_candidates, constraint_rejections


def _greedy_extend_path(
    path: BeamPath,
    candidates: list[CandidateTrack],
    candidate_artists: list[str | None],
    position: int,
    config: SequencerConfig,
    pool_cluster_counts: dict[int | None, int],
) -> BeamPath | None:
    """Emergency greedy: pick best-scoring valid candidate, no lookahead/bridge.

    Much faster than full beam scoring — used at relaxation level 3.
    """
    best_score = -999.0
    best_candidate = None
    best_norm_artist = None

    for idx, candidate in enumerate(candidates):
        if not is_valid_extension(path, candidate, position, config,
                                  pool_cluster_counts=pool_cluster_counts):
            continue

        score = candidate.total_score
        norm_artist = candidate_artists[idx]
        if norm_artist and norm_artist in path.artist_positions:
            artist_count = path.artist_counts.get(norm_artist, 0)
            score -= min(0.30, artist_count * artist_count * 0.015 + artist_count * 0.015)

        if score > best_score:
            best_score = score
            best_candidate = candidate
            best_norm_artist = norm_artist

    if best_candidate is None:
        return None

    new_path = path.copy()
    new_path.tracks.append(best_candidate)
    new_path.track_ids.add(best_candidate.id)
    new_path.cumulative_score = path.cumulative_score + best_score

    if best_norm_artist:
        new_path.artist_positions[best_norm_artist] = position
        new_path.artist_counts[best_norm_artist] = \
            new_path.artist_counts.get(best_norm_artist, 0) + 1
    if best_candidate.cluster_id is not None:
        new_path.cluster_counts[best_candidate.cluster_id] = \
            new_path.cluster_counts.get(best_candidate.cluster_id, 0) + 1

    return new_path


def sequence_playlist(
    position_pools: list[list[CandidateTrack]],
    config: SequencerConfig | None = None,
    cluster_centroids: list[np.ndarray] | None = None,
    cluster_ids: list[int] | None = None,
    transition_bonuses: dict | None = None,
) -> tuple[list[CandidateTrack], dict[str, Any]]:
    """
    Sequence playlist using beam search through position pools.

    This is the core v4 sequencing algorithm.

    Performance optimizations over naive approach:
    - Only retry dead-end beams at higher relaxation levels (not all beams)
    - Skip expensive lookahead at relaxation level >= 2
    - Greedy fallback at emergency level 3 (no full beam scoring)
    - Pre-normalize candidate artist names once per position
    - Incremental track_ids set on BeamPath (no rebuild per candidate)

    When all beams hit dead ends at a position, the sequencer
    progressively relaxes constraints (artist distance, cluster limits,
    duration ratio) and retries before giving up.
    """
    if not position_pools:
        return [], {}

    if config is None:
        config = SequencerConfig()

    # Metrics tracking
    total_constraint_rejections = 0
    total_beam_dead_ends = 0
    total_relaxations = 0

    # Initialize beam with empty path
    beam: list[BeamPath] = [BeamPath()]

    for position, candidates in enumerate(position_pools):
        # Get next pool for lookahead
        next_pool = position_pools[position + 1] if position + 1 < len(position_pools) else None

        # Precompute per-position data
        pool_cluster_counts: dict[int | None, int] = {}
        for c in candidates:
            pool_cluster_counts[c.cluster_id] = pool_cluster_counts.get(c.cluster_id, 0) + 1
        candidate_artists = _precompute_candidate_artists(candidates)

        # ── Progressive relaxation: only retry beams that were dead-ends ──
        # Accumulate successful extensions across levels; only retry failed beams.
        accumulated_candidates: list[tuple[BeamPath, float]] = []
        remaining_beam = beam  # beams that still need candidates
        used_level = 0

        for level in range(MAX_RELAXATION_LEVELS):
            if not remaining_beam:
                break

            effective_config = _relaxed_config(config, level) if level > 0 else config
            skip_lookahead = level >= 2

            # Emergency level: greedy fallback (much faster)
            if level >= 3:
                for path in remaining_beam:
                    greedy_path = _greedy_extend_path(
                        path, candidates, candidate_artists,
                        position, effective_config, pool_cluster_counts,
                    )
                    if greedy_path:
                        accumulated_candidates.append(
                            (greedy_path, greedy_path.cumulative_score)
                        )
                    else:
                        total_beam_dead_ends += 1
                if level > 0 and len(accumulated_candidates) > len(accumulated_candidates):
                    total_relaxations += 1
                used_level = max(used_level, level)
                break

            # Normal/moderate levels: full scoring per beam path
            level_candidates: list[tuple[BeamPath, float]] = []
            still_stuck: list[BeamPath] = []

            for path in remaining_beam:
                path_results, rejections = _extend_single_path(
                    path, candidates, candidate_artists, position,
                    effective_config, pool_cluster_counts,
                    next_pool if not skip_lookahead else None,
                    cluster_centroids, cluster_ids, transition_bonuses,
                    skip_lookahead=skip_lookahead,
                )
                total_constraint_rejections += rejections

                if path_results:
                    level_candidates.extend(path_results)
                else:
                    still_stuck.append(path)

            if level_candidates:
                accumulated_candidates.extend(level_candidates)
                used_level = max(used_level, level)
                if level > 0:
                    total_relaxations += 1
                    logger.info(
                        f"Position {position}: relaxation level {level} "
                        f"rescued {len(remaining_beam) - len(still_stuck)}/{len(remaining_beam)} beams "
                        f"(artist_dist={effective_config.min_artist_distance}, "
                        f"cluster_max={effective_config.max_cluster_per_window})"
                    )

            remaining_beam = still_stuck
            if still_stuck:
                total_beam_dead_ends += len(still_stuck)

        # Select diverse beam
        if accumulated_candidates:
            effective_config = _relaxed_config(config, used_level) if used_level > 0 else config
            beam = select_diverse_beam(
                accumulated_candidates,
                config.beam_width,
                effective_config.diversity_threshold,
            )
        else:
            logger.warning(
                f"No valid candidates at position {position} even after "
                f"{MAX_RELAXATION_LEVELS} relaxation levels — stopping"
            )
            break

    if not beam:
        logger.error("Beam search produced no results")
        return [], {"beam_dead_ends": total_beam_dead_ends,
                     "constraint_rejections": total_constraint_rejections,
                     "relaxations": total_relaxations}

    # Return best path
    best_path = max(beam, key=lambda p: p.cumulative_score)
    logger.info(
        f"Sequenced playlist: {len(best_path.tracks)} tracks, "
        f"score={best_path.cumulative_score:.2f}, "
        f"dead_ends={total_beam_dead_ends}, "
        f"constraint_rejections={total_constraint_rejections}, "
        f"relaxations={total_relaxations}"
    )

    seq_metrics = {
        "beam_dead_ends": total_beam_dead_ends,
        "constraint_rejections": total_constraint_rejections,
        "relaxations": total_relaxations,
    }

    return best_path.tracks, seq_metrics


def compute_playlist_metrics(
    playlist: list[CandidateTrack],
    position_pools: list[list[CandidateTrack]],
    sequencer_metrics: dict[str, Any] | None = None,
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
        "beam_dead_ends": (sequencer_metrics or {}).get("beam_dead_ends", 0),
        "constraint_rejections": (sequencer_metrics or {}).get("constraint_rejections", 0),
    }
