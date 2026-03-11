"""
Artist scene clustering for stylistic grouping.

Implements v4 multi-cluster membership:
- Primary cluster (weight >= 0.7)
- Optional secondary cluster(s) if weight >= 0.2
- Cap at 3 clusters per artist
- Weights computed from embedding distance to centroids
"""

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import KMeans

from app.database_pg import get_connection

logger = logging.getLogger(__name__)


@dataclass
class ClusterInfo:
    """Information about a scene cluster."""
    cluster_id: int
    name: str
    centroid: np.ndarray
    size: int


def get_artist_embeddings() -> dict[str, np.ndarray]:
    """Fetch all artist embeddings from database."""
    embeddings = {}
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get artist embeddings (computed from track embeddings)
            cur.execute("""
                SELECT a.id, AVG(te.embedding) as avg_embedding
                FROM artists a
                JOIN track_artists ta ON a.id = ta.artist_id
                JOIN track_embeddings te ON ta.track_id = te.track_id
                WHERE te.embedding IS NOT NULL
                GROUP BY a.id
                HAVING COUNT(te.embedding) >= 3
            """)
            
            for row in cur.fetchall():
                artist_id = str(row[0])
                embedding = np.array(row[1]) if row[1] else None
                if embedding is not None:
                    embeddings[artist_id] = embedding
    
    logger.info(f"Loaded {len(embeddings)} artist embeddings")
    return embeddings


def compute_clusters(
    embeddings: dict[str, np.ndarray],
    n_clusters: int = 20,
) -> tuple[list[ClusterInfo], dict[str, list[tuple[int, float]]]]:
    """
    Compute scene clusters from artist embeddings.
    
    Returns:
        Tuple of (cluster_infos, artist_cluster_weights)
        where artist_cluster_weights maps artist_id -> [(cluster_id, weight), ...]
    """
    if not embeddings:
        return [], {}
    
    artist_ids = list(embeddings.keys())
    embedding_matrix = np.array([embeddings[aid] for aid in artist_ids])
    
    # Normalize embeddings
    norms = np.linalg.norm(embedding_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embedding_matrix = embedding_matrix / norms
    
    # Fit KMeans
    n_clusters = min(n_clusters, len(artist_ids))
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embedding_matrix)
    centroids = kmeans.cluster_centers_
    
    # Build cluster info
    cluster_infos = []
    for i in range(n_clusters):
        size = int(np.sum(labels == i))
        cluster_infos.append(ClusterInfo(
            cluster_id=i,
            name=f"scene_{i}",
            centroid=centroids[i],
            size=size,
        ))
    
    # Compute multi-cluster weights for each artist
    artist_cluster_weights: dict[str, list[tuple[int, float]]] = {}
    
    for idx, artist_id in enumerate(artist_ids):
        artist_emb = embedding_matrix[idx]
        
        # Compute similarity to all centroids
        similarities = []
        for cluster in cluster_infos:
            sim = float(np.dot(artist_emb, cluster.centroid))
            similarities.append((cluster.cluster_id, sim))
        
        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Normalize to weights
        total_sim = sum(max(0, s) for _, s in similarities[:3])
        if total_sim > 0:
            weights = [
                (cid, max(0, sim) / total_sim)
                for cid, sim in similarities[:3]
            ]
        else:
            weights = [(similarities[0][0], 1.0)]
        
        # Filter by threshold and cap at 3
        filtered_weights = [
            (cid, w) for cid, w in weights
            if w >= 0.2  # Secondary threshold
        ][:3]
        
        # Ensure at least primary cluster
        if not filtered_weights:
            filtered_weights = [(similarities[0][0], 1.0)]
        
        artist_cluster_weights[artist_id] = filtered_weights
    
    logger.info(f"Computed {n_clusters} clusters for {len(artist_ids)} artists")
    return cluster_infos, artist_cluster_weights


def save_clusters(
    cluster_infos: list[ClusterInfo],
    artist_cluster_weights: dict[str, list[tuple[int, float]]],
) -> None:
    """Save cluster assignments to database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create tables if not exist
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scene_clusters (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(100),
                    centroid vector(384),
                    size INTEGER
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS artist_clusters (
                    artist_id UUID REFERENCES artists(id) ON DELETE CASCADE,
                    cluster_id INTEGER REFERENCES scene_clusters(id),
                    weight FLOAT,
                    PRIMARY KEY (artist_id, cluster_id)
                )
            """)
            
            # Clear existing
            cur.execute("DELETE FROM artist_clusters")
            cur.execute("DELETE FROM scene_clusters")
            
            # Insert clusters
            for cluster in cluster_infos:
                cur.execute("""
                    INSERT INTO scene_clusters (id, name, centroid, size)
                    VALUES (%s, %s, %s, %s)
                """, (cluster.cluster_id, cluster.name, 
                      cluster.centroid.tolist(), cluster.size))
            
            # Insert artist assignments
            for artist_id, weights in artist_cluster_weights.items():
                for cluster_id, weight in weights:
                    cur.execute("""
                        INSERT INTO artist_clusters (artist_id, cluster_id, weight)
                        VALUES (%s, %s, %s)
                    """, (artist_id, cluster_id, weight))
            
            conn.commit()
    
    logger.info(f"Saved {len(cluster_infos)} clusters and {len(artist_cluster_weights)} artist assignments")


def get_cluster_centroids() -> tuple[list[np.ndarray], list[int]]:
    """Load cluster centroids from database."""
    centroids = []
    cluster_ids = []
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, centroid FROM scene_clusters ORDER BY id")
            for row in cur.fetchall():
                cluster_ids.append(row[0])
                centroids.append(np.array(row[1]))
    
    return centroids, cluster_ids


def get_track_cluster(track_id: str, artist_id: str | None) -> tuple[int | None, float]:
    """
    Get cluster for a track (via artist).
    
    Returns:
        Tuple of (cluster_id, weight) or (None, 0) if not found
    """
    if not artist_id:
        return None, 0.0
    
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get primary cluster (highest weight)
            cur.execute("""
                SELECT cluster_id, weight
                FROM artist_clusters
                WHERE artist_id = %s
                ORDER BY weight DESC
                LIMIT 1
            """, (artist_id,))
            
            row = cur.fetchone()
            if row:
                return row[0], row[1]
    
    return None, 0.0


def compute_auto_bridge_score(
    track_embedding: np.ndarray,
    cluster_centroids: list[np.ndarray],
    cluster_ids: list[int],
    threshold: float = 0.5,
) -> list[tuple[int, int, float]]:
    """
    Automatically compute bridge scores for a track.
    
    A track is a bridge if it's close to multiple cluster centroids.
    
    Returns:
        List of (cluster_a, cluster_b, bridge_score) tuples
    """
    if not cluster_centroids or track_embedding is None:
        return []
    
    # Compute similarity to all centroids
    similarities = []
    for cid, centroid in zip(cluster_ids, cluster_centroids):
        sim = float(np.dot(track_embedding, centroid) / 
                   (np.linalg.norm(track_embedding) * np.linalg.norm(centroid) + 1e-8))
        similarities.append((cid, sim))
    
    # Sort by similarity
    similarities.sort(key=lambda x: x[1], reverse=True)
    
    # Find pairs where track is close to both
    bridges = []
    for i, (cid_a, sim_a) in enumerate(similarities[:3]):
        for cid_b, sim_b in similarities[i+1:4]:
            if sim_a >= threshold and sim_b >= threshold:
                # Bridge score = harmonic mean of similarities
                bridge_score = 2 * sim_a * sim_b / (sim_a + sim_b)
                bridges.append((cid_a, cid_b, bridge_score))
    
    return bridges


async def generate_clusters(
    n_clusters: int = 20,
    progress_callback: callable = None,
) -> dict[str, Any]:
    """
    Generate scene clusters from artist embeddings.
    
    Returns:
        Stats dict
    """
    stats = {"artists": 0, "clusters": 0}
    
    if progress_callback:
        progress_callback(0, 100, "Loading artist embeddings...")
    
    embeddings = get_artist_embeddings()
    stats["artists"] = len(embeddings)
    
    if not embeddings:
        logger.warning("No artist embeddings found")
        return stats
    
    if progress_callback:
        progress_callback(30, 100, "Computing clusters...")
    
    cluster_infos, artist_weights = compute_clusters(embeddings, n_clusters)
    stats["clusters"] = len(cluster_infos)
    
    if progress_callback:
        progress_callback(70, 100, "Saving clusters...")
    
    save_clusters(cluster_infos, artist_weights)
    
    if progress_callback:
        progress_callback(100, 100, "Clustering complete")
    
    logger.info(f"Clustering complete: {stats}")
    return stats
