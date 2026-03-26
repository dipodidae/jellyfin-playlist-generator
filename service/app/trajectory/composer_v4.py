"""
V4 Playlist Composer - Main orchestration module.

Ties together all v4 components:
1. Intent parsing with 5D trajectories (energy, tempo, darkness, texture, era)
2. Gravity anchor computation
3. Position-based candidate pools with curation scoring (banger + MA + RYM)
4. Beam search sequencing with acoustic continuity + era coherence
5. Automatic bridge scoring
"""

import logging
import time
from dataclasses import dataclass, replace as dc_replace
from typing import Any

import numpy as np

from app.trajectory.intent import ArcType, PlaylistIntent, PromptType, parse_prompt, _ALIAS_TO_FAMILY
from app.trajectory.gravity import GravityAnchors
from app.trajectory.candidates import (
    CandidateTrack,
    generate_position_pools,
    get_top_semantic_matches,
)
from app.trajectory.sequencer import (
    SequencerConfig,
    sequence_playlist,
    compute_playlist_metrics,
)
from app.clustering.scenes import get_cluster_centroids, get_track_cluster
from app.observability import (
    log_generation,
    update_track_usage,
    check_cold_start,
)
from app.transitions import load_transition_bonuses, record_transitions

logger = logging.getLogger(__name__)


@dataclass
class PlaylistResult:
    """Result of playlist generation."""
    tracks: list[CandidateTrack]
    intent: PlaylistIntent
    metrics: dict[str, Any]
    generation_time_ms: int


def compose_playlist_v4(
    prompt: str,
    target_size: int = 20,
    config: SequencerConfig | None = None,
) -> PlaylistResult:
    """
    Compose a playlist using the v4 architecture.

    This is the main entry point for playlist generation.
    """
    start_time = time.time()

    logger.info(f"V4 compose: '{prompt[:50]}...', size={target_size}")

    # 1. Parse prompt into intent with 5D trajectory
    intent = parse_prompt(prompt, target_size=target_size)

    # 2. Get top semantic matches for scene anchor
    top_embeddings, top_scores = get_top_semantic_matches(
        intent.prompt_embedding, limit=20
    )

    # 3. Create gravity anchors
    anchors = GravityAnchors.from_embeddings(
        prompt_embedding=intent.prompt_embedding,
        top_track_embeddings=top_embeddings,
        top_track_scores=top_scores,
        arc_type=intent.arc_type.value,
    )

    # 4. Generate position-based candidate pools
    position_pools = generate_position_pools(intent, anchors)

    if not position_pools:
        logger.warning("No candidate pools generated")
        return PlaylistResult(
            tracks=[],
            intent=intent,
            metrics={"error": "no_candidates"},
            generation_time_ms=int((time.time() - start_time) * 1000),
        )

    # 5. Enrich candidates with cluster info
    cluster_centroids, cluster_ids = get_cluster_centroids()

    for pool in position_pools:
        for track in pool:
            if track.artist_id:
                cluster_id, weight = get_track_cluster(track.id, track.artist_id)
                track.cluster_id = cluster_id
                track.cluster_weight = weight

    # 6. Load historical transition bonuses (batch query — no N+1)
    all_candidate_ids = list({t.id for pool in position_pools for t in pool})
    transition_bonuses = load_transition_bonuses(all_candidate_ids)

    # 7. Sequence playlist using beam search
    if config is None:
        config = SequencerConfig()

    # Playlists with a non-STEADY arc need to traverse cluster boundaries;
    # GENRE prompts and STEADY arcs should stay cluster-tight for genre purity.
    if (intent.prompt_type != PromptType.GENRE
            and intent.arc_type != ArcType.STEADY):
        config = dc_replace(config, bridge_bonus_weight=0.10)

    # Pre-compute trajectory energy targets for direction penalty
    n_pos = len(position_pools)
    trajectory_targets = [
        (intent.trajectory_curve.evaluate(i / (n_pos - 1) if n_pos > 1 else 0.5).energy,
         intent.trajectory_curve.evaluate(i / (n_pos - 1) if n_pos > 1 else 0.5).darkness)
        for i in range(n_pos)
    ]

    # Build target genre distribution for drift tracking
    target_genre_dist: dict[str, float] = {}
    if intent.genre_hints_primary:
        primary = list(intent.genre_hints_primary)
        for h in primary:
            fam = _ALIAS_TO_FAMILY.get(h.lower(), h.lower())
            target_genre_dist[fam] = target_genre_dist.get(fam, 0.0) + 1.0
        total = sum(target_genre_dist.values())
        if total > 0:
            target_genre_dist = {k: v / total for k, v in target_genre_dist.items()}

    playlist, seq_metrics = sequence_playlist(
        position_pools,
        config=config,
        cluster_centroids=cluster_centroids,
        cluster_ids=cluster_ids,
        transition_bonuses=transition_bonuses,
        trajectory_targets=trajectory_targets,
        target_genre_dist=target_genre_dist or None,
    )

    # 8. Compute metrics
    metrics = compute_playlist_metrics(playlist, position_pools, seq_metrics)

    generation_time = int((time.time() - start_time) * 1000)
    metrics["generation_time_ms"] = generation_time

    logger.info(f"V4 compose complete: {len(playlist)} tracks in {generation_time}ms")

    # Log generation metrics
    log_generation(
        prompt=prompt,
        arc_type=intent.arc_type.value,
        playlist_length=len(playlist),
        generation_time_ms=generation_time,
        metrics=metrics,
    )

    # Update track usage and record transitions for playlist memory
    update_track_usage([t.id for t in playlist])
    record_transitions([t.id for t in playlist])

    return PlaylistResult(
        tracks=playlist,
        intent=intent,
        metrics=metrics,
        generation_time_ms=generation_time,
    )


def compose_playlist_v4_streaming(
    prompt: str,
    target_size: int = 20,
    config: SequencerConfig | None = None,
    progress_callback: callable = None,
) -> PlaylistResult:
    """
    Compose playlist with progress callbacks for streaming.
    """
    start_time = time.time()

    def report(step: int, total: int, message: str):
        if progress_callback:
            progress_callback(step, total, message)

    report(1, 8, "Understanding your prompt...")
    intent = parse_prompt(prompt, target_size=target_size)

    report(2, 8, "Computing gravity anchors...")
    top_embeddings, top_scores = get_top_semantic_matches(
        intent.prompt_embedding, limit=20
    )
    anchors = GravityAnchors.from_embeddings(
        prompt_embedding=intent.prompt_embedding,
        top_track_embeddings=top_embeddings,
        top_track_scores=top_scores,
        arc_type=intent.arc_type.value,
    )

    report(3, 8, "Generating candidate pools...")
    position_pools = generate_position_pools(intent, anchors)

    if not position_pools:
        return PlaylistResult(
            tracks=[],
            intent=intent,
            metrics={"error": "no_candidates"},
            generation_time_ms=int((time.time() - start_time) * 1000),
        )

    report(4, 8, "Loading cluster data...")
    cluster_centroids, cluster_ids = get_cluster_centroids()

    for pool in position_pools:
        for track in pool:
            if track.artist_id:
                cluster_id, weight = get_track_cluster(track.id, track.artist_id)
                track.cluster_id = cluster_id
                track.cluster_weight = weight

    report(5, 8, "Sequencing playlist...")
    all_candidate_ids = list({t.id for pool in position_pools for t in pool})
    transition_bonuses = load_transition_bonuses(all_candidate_ids)

    if config is None:
        config = SequencerConfig()

    # Playlists with a non-STEADY arc need to traverse cluster boundaries;
    # GENRE prompts and STEADY arcs should stay cluster-tight for genre purity.
    if (intent.prompt_type != PromptType.GENRE
            and intent.arc_type != ArcType.STEADY):
        config = dc_replace(config, bridge_bonus_weight=0.10)

    # Pre-compute trajectory energy targets for direction penalty
    n_pos = len(position_pools)
    trajectory_targets = [
        (intent.trajectory_curve.evaluate(i / (n_pos - 1) if n_pos > 1 else 0.5).energy,
         intent.trajectory_curve.evaluate(i / (n_pos - 1) if n_pos > 1 else 0.5).darkness)
        for i in range(n_pos)
    ]

    target_genre_dist: dict[str, float] = {}
    if intent.genre_hints_primary:
        primary = list(intent.genre_hints_primary)
        for h in primary:
            fam = _ALIAS_TO_FAMILY.get(h.lower(), h.lower())
            target_genre_dist[fam] = target_genre_dist.get(fam, 0.0) + 1.0
        total = sum(target_genre_dist.values())
        if total > 0:
            target_genre_dist = {k: v / total for k, v in target_genre_dist.items()}

    playlist, seq_metrics = sequence_playlist(
        position_pools,
        config=config,
        cluster_centroids=cluster_centroids,
        cluster_ids=cluster_ids,
        transition_bonuses=transition_bonuses,
        trajectory_targets=trajectory_targets,
        target_genre_dist=target_genre_dist or None,
    )

    report(6, 8, "Computing metrics...")
    metrics = compute_playlist_metrics(playlist, position_pools, seq_metrics)

    generation_time = int((time.time() - start_time) * 1000)
    metrics["generation_time_ms"] = generation_time

    record_transitions([t.id for t in playlist])

    return PlaylistResult(
        tracks=playlist,
        intent=intent,
        metrics=metrics,
        generation_time_ms=generation_time,
    )





def get_trajectory_visualization(
    playlist: list[CandidateTrack],
    intent: PlaylistIntent,
) -> dict[str, Any]:
    """
    Generate trajectory visualization data.
    """
    target_curve = []
    actual_curve = []

    for i in range(len(playlist)):
        t = i / (len(playlist) - 1) if len(playlist) > 1 else 0.5
        target = intent.trajectory_curve.evaluate(t)
        track = playlist[i]

        target_curve.append({
            "position": t,
            "energy": target.energy,
            "tempo": target.tempo,
            "darkness": target.darkness,
            "texture": target.texture,
        })

        actual_curve.append({
            "position": t,
            "energy": track.energy,
            "tempo": track.tempo,
            "darkness": track.darkness,
            "texture": track.texture,
        })

    # Compute deviation
    deviations = []
    for target, actual in zip(target_curve, actual_curve):
        dev = sum(
            abs(target[dim] - actual[dim])
            for dim in ["energy", "tempo", "darkness", "texture"]
        ) / 4
        deviations.append(dev)

    avg_deviation = sum(deviations) / len(deviations) if deviations else 0.0

    return {
        "target_curve": target_curve,
        "actual_curve": actual_curve,
        "deviation_score": round(avg_deviation, 3),
    }
