"""
Dual-anchor gravity well system for stylistic coherence.

Prevents playlist drift by pulling tracks toward two anchors:
1. Prompt anchor: embedding of the user's prompt
2. Scene anchor: weighted centroid of top semantic matches

Gravity strength varies by arc type - tighter for steady playlists,
looser for journey/exploration arcs.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GravityAnchors:
    """Dual anchors for gravity well computation."""
    prompt_anchor: np.ndarray  # Embedding of user prompt
    scene_anchor: np.ndarray   # Weighted centroid of top matches
    gravity_strength: float = 0.5  # Overall gravity multiplier

    @classmethod
    def from_embeddings(
        cls,
        prompt_embedding: list[float],
        top_track_embeddings: list[list[float]],
        top_track_scores: list[float],
        arc_type: str = "steady",
    ) -> "GravityAnchors":
        """
        Create gravity anchors from prompt and top semantic matches.
        
        Args:
            prompt_embedding: Embedding vector of user prompt
            top_track_embeddings: Embeddings of top N semantic matches
            top_track_scores: Semantic similarity scores for weighting
            arc_type: Arc type to determine gravity strength
            
        Returns:
            GravityAnchors instance
        """
        prompt_anchor = np.array(prompt_embedding)
        
        # Compute weighted centroid for scene anchor
        if top_track_embeddings and top_track_scores:
            embeddings = np.array(top_track_embeddings)
            scores = np.array(top_track_scores)
            
            # Normalize scores to sum to 1
            weights = scores / scores.sum() if scores.sum() > 0 else np.ones(len(scores)) / len(scores)
            
            # Weighted average
            scene_anchor = np.average(embeddings, axis=0, weights=weights)
        else:
            # Fall back to prompt anchor if no matches
            scene_anchor = prompt_anchor.copy()
        
        # Gravity strength by arc type
        gravity_map = {
            "steady": 0.8,
            "rise": 0.5,
            "fall": 0.5,
            "peak": 0.4,
            "valley": 0.5,
            "wave": 0.4,
            "journey": 0.3,
        }
        gravity_strength = gravity_map.get(arc_type.lower(), 0.5)
        
        return cls(
            prompt_anchor=prompt_anchor,
            scene_anchor=scene_anchor,
            gravity_strength=gravity_strength,
        )


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """
    Compute cosine distance between two vectors.
    
    Returns value in [0, 2] where 0 = identical, 2 = opposite.
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a == 0 or norm_b == 0:
        return 1.0  # Undefined, return neutral
    
    similarity = np.dot(a, b) / (norm_a * norm_b)
    return 1.0 - similarity  # Convert to distance


def compute_gravity_penalty(
    track_embedding: list[float] | np.ndarray,
    anchors: GravityAnchors,
    position: float = 0.5,
    max_penalty: float = 0.35,
) -> float:
    """
    Compute gravity penalty for a track.
    
    The penalty increases with distance from anchors, pulling tracks
    toward the stylistic center defined by the prompt and top matches.
    
    Args:
        track_embedding: Track's embedding vector
        anchors: GravityAnchors with prompt and scene anchors
        position: Position in playlist [0, 1] - allows looser gravity at edges
        max_penalty: Cap to prevent gravity from dominating scoring
        
    Returns:
        Gravity penalty in [0, max_penalty]
    """
    if track_embedding is None:
        return 0.0
    
    track_vec = np.array(track_embedding) if not isinstance(track_embedding, np.ndarray) else track_embedding
    
    # Distance to prompt anchor (weight: 0.6)
    prompt_dist = cosine_distance(track_vec, anchors.prompt_anchor)
    
    # Distance to scene anchor (weight: 0.4)
    scene_dist = cosine_distance(track_vec, anchors.scene_anchor)
    
    # Combined distance (normalized to ~[0, 1])
    combined_dist = prompt_dist * 0.6 + scene_dist * 0.4
    
    # Apply gravity strength
    raw_penalty = combined_dist * anchors.gravity_strength
    
    # Position-based modulation: slightly looser at playlist edges
    # This allows more variety in intro/outro
    edge_factor = 1.0 - 0.2 * (1.0 - abs(2 * position - 1))
    modulated_penalty = raw_penalty * edge_factor
    
    # Cap the penalty
    return min(modulated_penalty, max_penalty)


def compute_bridge_bonus(
    track_embedding: list[float] | np.ndarray,
    cluster_centroids: list[np.ndarray],
    cluster_ids: list[int],
    from_cluster: int | None,
    to_cluster: int | None,
    max_bonus: float = 0.15,
) -> float:
    """
    Compute bonus for tracks that bridge between clusters.
    
    A track is a good bridge if it's close to both cluster centroids,
    enabling smooth transitions between different styles.
    
    Args:
        track_embedding: Track's embedding vector
        cluster_centroids: List of cluster centroid vectors
        cluster_ids: Corresponding cluster IDs
        from_cluster: Source cluster (previous track's cluster)
        to_cluster: Target cluster (desired next cluster)
        max_bonus: Maximum bridge bonus
        
    Returns:
        Bridge bonus in [0, max_bonus]
    """
    if track_embedding is None or not cluster_centroids:
        return 0.0
    
    if from_cluster is None or to_cluster is None:
        return 0.0
    
    if from_cluster == to_cluster:
        return 0.0  # No bridging needed within same cluster
    
    track_vec = np.array(track_embedding) if not isinstance(track_embedding, np.ndarray) else track_embedding
    
    # Find centroids for source and target clusters
    from_centroid = None
    to_centroid = None
    
    for centroid, cid in zip(cluster_centroids, cluster_ids):
        if cid == from_cluster:
            from_centroid = centroid
        if cid == to_cluster:
            to_centroid = centroid
    
    if from_centroid is None or to_centroid is None:
        return 0.0
    
    # Track is a good bridge if close to both clusters
    dist_from = cosine_distance(track_vec, from_centroid)
    dist_to = cosine_distance(track_vec, to_centroid)
    
    # Average proximity (lower is better)
    avg_dist = (dist_from + dist_to) / 2
    
    # Convert to bonus (closer = higher bonus)
    # A track at distance 0.3 from both gets max bonus
    if avg_dist < 0.5:
        bonus = max_bonus * (1.0 - avg_dist / 0.5)
    else:
        bonus = 0.0
    
    return bonus
