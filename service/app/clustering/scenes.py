"""
Artist scene clustering for stylistic grouping.

V5 pipeline — HDBSCAN + UMAP with tag-enriched embeddings:
1. Load track-averaged artist embeddings
2. Generate artist-level tag embeddings from Last.fm tags
3. Blend track + tag embeddings (configurable weight)
4. UMAP dimensionality reduction (384 → N dims)
5. HDBSCAN density-based clustering (auto cluster count, noise detection)
6. Merge overly-similar clusters (cosine threshold)
7. Soft-assign noise points to nearest centroid (low weight)
8. Compute multi-cluster membership weights
9. Save to database
10. Post-hoc assign small artists to nearest centroid
11. Compute and log cluster quality metrics (tag coherence)

Public interface unchanged from v4:
- generate_clusters() → stats dict
- get_cluster_centroids() → (centroids, cluster_ids)
- get_track_cluster() → (cluster_id, weight)
"""

import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import hdbscan
import numpy as np
import umap

from app.config import settings
from app.database_pg import get_connection

logger = logging.getLogger(__name__)


@dataclass
class ClusterInfo:
    """Information about a scene cluster."""
    cluster_id: int
    name: str
    centroid: np.ndarray  # In original 384-dim space (for DB storage & bridge scoring)
    size: int


# ---------------------------------------------------------------------------
# 1. Embedding loading & enrichment
# ---------------------------------------------------------------------------

def _coerce_embedding(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return value.astype(float, copy=False)
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype=float)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        if not stripped:
            return None
        return np.fromstring(stripped, sep=",", dtype=float)
    return np.asarray(value, dtype=float)


def get_artist_embeddings() -> dict[str, np.ndarray]:
    """Fetch artist embeddings (track-averaged) from database.

    Artists must have at least ``cluster_min_tracks`` embedded tracks to be
    included (configurable via CLUSTER_MIN_TRACKS env var).
    """
    t0 = time.perf_counter()
    min_tracks = settings.cluster_min_tracks
    embeddings = {}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, AVG(te.embedding) as avg_embedding
                FROM artists a
                JOIN track_artists ta ON a.id = ta.artist_id
                JOIN track_embeddings te ON ta.track_id = te.track_id
                WHERE te.embedding IS NOT NULL
                GROUP BY a.id
                HAVING COUNT(te.embedding) >= %s
            """, (min_tracks,))

            for row in cur.fetchall():
                artist_id = str(row[0])
                embedding = _coerce_embedding(row[1])
                if embedding is not None and embedding.size > 0:
                    embeddings[artist_id] = embedding

    elapsed = time.perf_counter() - t0
    logger.info(
        "Loaded %d artist embeddings (min_tracks=%d) in %.1fs",
        len(embeddings), min_tracks, elapsed,
    )
    return embeddings


def _get_artist_tags() -> dict[str, list[tuple[str, int]]]:
    """Fetch Last.fm tags per artist.

    Returns:
        Mapping of artist_id → [(tag_name, weight), ...] sorted by weight desc.
    """
    t0 = time.perf_counter()
    artist_tags: dict[str, list[tuple[str, int]]] = {}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, lt.name, alt.weight
                FROM artist_lastfm_tags alt
                JOIN artists a ON a.id = alt.artist_id
                JOIN lastfm_tags lt ON lt.id = alt.tag_id
                ORDER BY a.id, alt.weight DESC
            """)
            for row in cur.fetchall():
                aid = str(row[0])
                if aid not in artist_tags:
                    artist_tags[aid] = []
                artist_tags[aid].append((row[1], row[2]))

    elapsed = time.perf_counter() - t0
    logger.info("Loaded tags for %d artists in %.1fs", len(artist_tags), elapsed)
    return artist_tags


def _generate_tag_embeddings(
    artist_ids: list[str],
    artist_tags: dict[str, list[tuple[str, int]]],
) -> dict[str, np.ndarray]:
    """Generate embeddings from artist Last.fm tags.

    For each artist, builds a weighted text from their top tags and embeds it
    using the same sentence-transformer model used for tracks.

    Artists without tags get no tag embedding (they'll use track embedding only).
    """
    from app.embeddings.generator import get_model

    t0 = time.perf_counter()
    texts: list[str] = []
    ids_with_tags: list[str] = []

    for aid in artist_ids:
        tags = artist_tags.get(aid)
        if not tags:
            continue

        # Build weighted tag text: repeat higher-weight tags more
        # Top 15 tags, weight-sorted. Repeat top tags for emphasis.
        top_tags = tags[:15]
        tag_parts = []
        for tag_name, weight in top_tags:
            # Repeat high-weight tags: weight 100 → 3x, weight 50 → 2x, else 1x
            repeats = 3 if weight >= 80 else (2 if weight >= 40 else 1)
            tag_parts.extend([tag_name] * repeats)

        text = ", ".join(tag_parts)
        texts.append(text)
        ids_with_tags.append(aid)

    if not texts:
        logger.info("No artist tags available for tag embedding generation")
        return {}

    model = get_model()
    raw_embeddings = model.encode(texts, batch_size=64, convert_to_numpy=True,
                                  show_progress_bar=False)

    result = {}
    for aid, emb in zip(ids_with_tags, raw_embeddings):
        result[aid] = emb.astype(float)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Generated tag embeddings for %d/%d artists in %.1fs",
        len(result), len(artist_ids), elapsed,
    )
    return result


def _blend_embeddings(
    track_embeddings: dict[str, np.ndarray],
    tag_embeddings: dict[str, np.ndarray],
    tag_weight: float,
) -> dict[str, np.ndarray]:
    """Blend track-averaged and tag-based embeddings.

    final = (1 - tag_weight) * track_emb + tag_weight * tag_emb

    Artists without tag embeddings use track embedding only.
    """
    blended = {}
    enriched_count = 0

    for aid, track_emb in track_embeddings.items():
        tag_emb = tag_embeddings.get(aid)
        if tag_emb is not None and tag_emb.size == track_emb.size:
            blended[aid] = (1 - tag_weight) * track_emb + tag_weight * tag_emb
            enriched_count += 1
        else:
            blended[aid] = track_emb

    logger.info(
        "Blended embeddings: %d/%d artists enriched with tag signal (weight=%.2f)",
        enriched_count, len(track_embeddings), tag_weight,
    )
    return blended


# ---------------------------------------------------------------------------
# 2. UMAP + HDBSCAN clustering
# ---------------------------------------------------------------------------

def _reduce_dimensions(
    embedding_matrix: np.ndarray,
    random_state: int,
) -> np.ndarray:
    """Reduce embedding dimensions with UMAP for better HDBSCAN performance."""
    t0 = time.perf_counter()
    n_samples = len(embedding_matrix)

    # Clamp n_neighbors to sample count
    n_neighbors = min(settings.cluster_umap_n_neighbors, n_samples - 1)
    n_components = min(settings.cluster_umap_n_components, n_samples - 1)

    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=settings.cluster_umap_min_dist,
        metric="cosine",
        random_state=random_state,
        verbose=False,
    )
    reduced = reducer.fit_transform(embedding_matrix)

    elapsed = time.perf_counter() - t0
    logger.info(
        "UMAP reduction: %d → %d dims for %d artists in %.1fs",
        embedding_matrix.shape[1], reduced.shape[1], n_samples, elapsed,
    )
    return reduced


def _run_hdbscan(
    reduced_matrix: np.ndarray,
) -> np.ndarray:
    """Run HDBSCAN clustering on UMAP-reduced embeddings.

    Returns label array where -1 = noise.
    """
    t0 = time.perf_counter()

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=settings.cluster_min_cluster_size,
        min_samples=settings.cluster_min_samples,
        metric="euclidean",  # Euclidean on UMAP output is standard
        cluster_selection_method="eom",  # Excess of Mass (default, good general choice)
    )
    labels = clusterer.fit_predict(reduced_matrix)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int(np.sum(labels == -1))

    elapsed = time.perf_counter() - t0
    logger.info(
        "HDBSCAN: found %d clusters + %d noise points in %.1fs "
        "(min_cluster_size=%d, min_samples=%d)",
        n_clusters, n_noise, elapsed,
        settings.cluster_min_cluster_size, settings.cluster_min_samples,
    )
    return labels


# ---------------------------------------------------------------------------
# 3. Post-clustering merge
# ---------------------------------------------------------------------------

def _compute_centroids(
    labels: np.ndarray,
    embedding_matrix: np.ndarray,
) -> dict[int, np.ndarray]:
    """Compute centroids in original embedding space for each cluster label.

    Excludes noise points (label == -1).
    """
    centroids = {}
    for label in set(labels):
        if label == -1:
            continue
        mask = labels == label
        centroid = embedding_matrix[mask].mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        centroids[label] = centroid
    return centroids


def _merge_similar_clusters(
    labels: np.ndarray,
    embedding_matrix: np.ndarray,
    threshold: float,
) -> np.ndarray:
    """Merge clusters whose centroids exceed cosine similarity threshold.

    Iteratively merges the most similar pair until no pair exceeds threshold.
    Smaller clusters merge into larger ones. Works on original-space embeddings
    so similarity is meaningful.

    Returns updated label array.
    """
    labels = labels.copy()
    merge_count = 0

    while True:
        centroids = _compute_centroids(labels, embedding_matrix)
        cluster_ids = sorted(centroids.keys())

        if len(cluster_ids) < 2:
            break

        # Find most similar pair
        best_sim = -1.0
        best_pair = None

        for i in range(len(cluster_ids)):
            for j in range(i + 1, len(cluster_ids)):
                ci, cj = cluster_ids[i], cluster_ids[j]
                sim = float(np.dot(centroids[ci], centroids[cj]))
                if sim > best_sim:
                    best_sim = sim
                    best_pair = (ci, cj)

        if best_sim < threshold or best_pair is None:
            break

        # Merge smaller into larger
        ci, cj = best_pair
        size_i = int(np.sum(labels == ci))
        size_j = int(np.sum(labels == cj))

        if size_i >= size_j:
            target, source = ci, cj
        else:
            target, source = cj, ci

        labels[labels == source] = target
        merge_count += 1

        logger.info(
            "Merged cluster %d (%d artists) into cluster %d (%d artists) — "
            "cosine similarity %.3f",
            source, min(size_i, size_j), target, max(size_i, size_j), best_sim,
        )

    if merge_count > 0:
        logger.info("Post-clustering merge: %d merges performed", merge_count)
    else:
        logger.info("Post-clustering merge: no clusters exceeded threshold %.2f", threshold)

    return labels


def _relabel_sequential(labels: np.ndarray) -> np.ndarray:
    """Relabel clusters to sequential 0..N-1, preserving noise as -1."""
    labels = labels.copy()
    unique_labels = sorted(set(labels) - {-1})
    label_map = {old: new for new, old in enumerate(unique_labels)}
    label_map[-1] = -1

    return np.array([label_map[l] for l in labels])


# ---------------------------------------------------------------------------
# 4. Noise handling & multi-cluster membership
# ---------------------------------------------------------------------------

def _soft_assign_noise(
    labels: np.ndarray,
    embedding_matrix: np.ndarray,
    centroids: dict[int, np.ndarray],
    noise_weight: float,
) -> tuple[np.ndarray, dict[int, float]]:
    """Assign noise points (-1) to nearest cluster with a low weight.

    Returns:
        - Updated labels (noise points now have a cluster label)
        - Mapping of artist-index → weight for noise points (all get noise_weight)
    """
    noise_mask = labels == -1
    n_noise = int(noise_mask.sum())

    if n_noise == 0 or not centroids:
        return labels, {}

    labels = labels.copy()
    noise_weights: dict[int, float] = {}

    centroid_ids = sorted(centroids.keys())
    centroid_matrix = np.array([centroids[cid] for cid in centroid_ids])

    noise_indices = np.where(noise_mask)[0]
    for idx in noise_indices:
        emb = embedding_matrix[idx]
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        sims = np.dot(centroid_matrix, emb)
        best = int(np.argmax(sims))
        labels[idx] = centroid_ids[best]
        noise_weights[idx] = noise_weight

    logger.info(
        "Soft-assigned %d noise points to nearest clusters (weight=%.2f)",
        n_noise, noise_weight,
    )
    return labels, noise_weights


# ---------------------------------------------------------------------------
# 5. Cluster quality metrics
# ---------------------------------------------------------------------------

def _compute_cluster_quality(
    cluster_infos: list[ClusterInfo],
    artist_cluster_weights: dict[str, list[tuple[int, float]]],
) -> list[dict[str, Any]]:
    """Compute tag coherence metrics per cluster.

    For each cluster, fetches all artist tags and computes:
    - Top tags and their combined weight share
    - Tag concentration (fraction of total weight in top-5 tags)
    - Cluster size

    Logs warnings for clusters with low tag coherence.
    """
    # Build cluster → artist_ids mapping (primary cluster only)
    cluster_artists: dict[int, list[str]] = defaultdict(list)
    for aid, weights in artist_cluster_weights.items():
        if weights:
            primary_cid = weights[0][0]  # Highest weight first
            cluster_artists[primary_cid].append(aid)

    # Fetch all artist tags in one query
    artist_tags: dict[str, list[tuple[str, int]]] = {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, lt.name, alt.weight
                FROM artist_lastfm_tags alt
                JOIN artists a ON a.id = alt.artist_id
                JOIN lastfm_tags lt ON lt.id = alt.tag_id
                ORDER BY a.id, alt.weight DESC
            """)
            for row in cur.fetchall():
                aid = str(row[0])
                if aid not in artist_tags:
                    artist_tags[aid] = []
                artist_tags[aid].append((row[1], row[2]))

    quality_reports = []

    for cluster in cluster_infos:
        cid = cluster.cluster_id
        aids = cluster_artists.get(cid, [])

        # Aggregate tags across all artists in this cluster
        tag_counter: Counter = Counter()
        for aid in aids:
            for tag_name, weight in artist_tags.get(aid, []):
                tag_counter[tag_name] += weight

        total_weight = sum(tag_counter.values())
        top_5 = tag_counter.most_common(5)
        top_5_weight = sum(w for _, w in top_5)

        concentration = top_5_weight / total_weight if total_weight > 0 else 0.0

        report = {
            "cluster_id": cid,
            "name": cluster.name,
            "size": cluster.size,
            "top_tags": [{"tag": name, "weight": w} for name, w in top_5],
            "tag_concentration": round(concentration, 3),
            "total_tag_weight": total_weight,
            "unique_tags": len(tag_counter),
        }
        quality_reports.append(report)

        # Log quality
        tag_summary = ", ".join(f"{name}({w})" for name, w in top_5)
        if concentration < 0.25 and cluster.size > 3:
            logger.warning(
                "Low coherence cluster %s (size=%d, concentration=%.2f): %s",
                cluster.name, cluster.size, concentration, tag_summary,
            )
        else:
            logger.info(
                "Cluster %s (size=%d, concentration=%.2f): %s",
                cluster.name, cluster.size, concentration, tag_summary,
            )

    return quality_reports


# ---------------------------------------------------------------------------
# 6. Main compute & persistence (same interface as v4)
# ---------------------------------------------------------------------------

def compute_clusters(
    embeddings: dict[str, np.ndarray],
    n_clusters: int | None = None,
) -> tuple[list[ClusterInfo], dict[str, list[tuple[int, float]]]]:
    """
    Compute scene clusters from artist embeddings using UMAP + HDBSCAN.

    Args:
        embeddings: Mapping of artist_id -> embedding vector.
        n_clusters: Ignored (kept for interface compatibility).
            HDBSCAN determines cluster count automatically.

    Returns:
        Tuple of (cluster_infos, artist_cluster_weights)
        where artist_cluster_weights maps artist_id -> [(cluster_id, weight), ...]
    """
    if not embeddings:
        return [], {}

    t0 = time.perf_counter()

    artist_ids = list(embeddings.keys())
    embedding_matrix = np.array([embeddings[aid] for aid in artist_ids])

    # Normalize embeddings (original space)
    norms = np.linalg.norm(embedding_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embedding_matrix = embedding_matrix / norms

    # UMAP dimensionality reduction
    reduced = _reduce_dimensions(embedding_matrix, settings.cluster_random_state)

    # HDBSCAN clustering
    labels = _run_hdbscan(reduced)

    n_real_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    if n_real_clusters == 0:
        # HDBSCAN found everything as noise — fall back to single cluster
        logger.warning(
            "HDBSCAN found 0 clusters (all noise). "
            "Consider lowering cluster_min_cluster_size (current=%d) "
            "or cluster_min_samples (current=%d)",
            settings.cluster_min_cluster_size, settings.cluster_min_samples,
        )
        labels = np.zeros(len(artist_ids), dtype=int)

    # Compute centroids in original space (for DB storage and bridge scoring)
    centroids = _compute_centroids(labels, embedding_matrix)

    # Merge overly-similar clusters
    labels = _merge_similar_clusters(
        labels, embedding_matrix, settings.cluster_merge_threshold,
    )

    # Soft-assign noise points
    centroids = _compute_centroids(labels, embedding_matrix)
    labels, noise_weight_map = _soft_assign_noise(
        labels, embedding_matrix, centroids, settings.cluster_noise_weight,
    )

    # Relabel to sequential 0..N-1
    labels = _relabel_sequential(labels)

    # Recompute final centroids after merge + noise assignment
    final_centroids = _compute_centroids(labels, embedding_matrix)
    n_clusters_final = len(final_centroids)

    # Build ClusterInfo objects
    cluster_infos = []
    for cid in sorted(final_centroids.keys()):
        size = int(np.sum(labels == cid))
        cluster_infos.append(ClusterInfo(
            cluster_id=cid,
            name=f"scene_{cid}",
            centroid=final_centroids[cid],
            size=size,
        ))

    # Log cluster size distribution
    sizes = [c.size for c in cluster_infos]
    logger.info(
        "Final clusters: %d clusters — sizes: min=%d, max=%d, mean=%.1f, median=%.1f",
        n_clusters_final, min(sizes), max(sizes), np.mean(sizes), np.median(sizes),
    )

    # Compute multi-cluster weights for each artist
    secondary_threshold = settings.cluster_secondary_weight_threshold
    max_per_artist = settings.cluster_max_per_artist
    artist_cluster_weights: dict[str, list[tuple[int, float]]] = {}
    multi_cluster_count = 0

    for idx, artist_id in enumerate(artist_ids):
        artist_emb = embedding_matrix[idx]

        # Check if this was a noise point (gets reduced max weight)
        is_noise = idx in noise_weight_map
        max_weight = noise_weight_map[idx] if is_noise else 1.0

        # Compute similarity to all final centroids
        similarities = []
        for cluster in cluster_infos:
            sim = float(np.dot(artist_emb, cluster.centroid))
            similarities.append((cluster.cluster_id, sim))

        # Sort by similarity descending
        similarities.sort(key=lambda x: x[1], reverse=True)

        # Normalize to weights (only top candidates)
        top_sims = similarities[:max_per_artist]
        total_sim = sum(max(0, s) for _, s in top_sims)
        if total_sim > 0:
            weights = [
                (cid, max(0, sim) / total_sim * max_weight)
                for cid, sim in top_sims
            ]
        else:
            weights = [(similarities[0][0], max_weight)]

        # Filter by threshold and cap
        filtered_weights = [
            (cid, w) for cid, w in weights
            if w >= secondary_threshold
        ][:max_per_artist]

        # Ensure at least primary cluster
        if not filtered_weights:
            primary_cid = int(labels[idx])
            filtered_weights = [(primary_cid, max_weight)]

        if len(filtered_weights) > 1:
            multi_cluster_count += 1

        artist_cluster_weights[artist_id] = filtered_weights

    total_elapsed = time.perf_counter() - t0
    logger.info(
        "Computed %d clusters for %d artists in %.2fs "
        "(%d artists belong to multiple clusters, "
        "%d noise points soft-assigned at weight %.2f)",
        n_clusters_final, len(artist_ids), total_elapsed,
        multi_cluster_count, len(noise_weight_map),
        settings.cluster_noise_weight,
    )
    return cluster_infos, artist_cluster_weights


def save_clusters(
    cluster_infos: list[ClusterInfo],
    artist_cluster_weights: dict[str, list[tuple[int, float]]],
) -> None:
    """Save cluster assignments to database using a single transaction.

    Uses TRUNCATE + bulk INSERT inside a single transaction so the data is
    never partially missing.
    """
    t0 = time.perf_counter()

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

            # Truncate within the same transaction — atomic swap
            cur.execute("TRUNCATE artist_clusters, scene_clusters CASCADE")

            # Bulk insert clusters
            from psycopg2.extras import execute_values
            cluster_rows = [
                (int(c.cluster_id), c.name, c.centroid.tolist(), int(c.size))
                for c in cluster_infos
            ]
            execute_values(
                cur,
                "INSERT INTO scene_clusters (id, name, centroid, size) VALUES %s",
                cluster_rows,
                template="(%s, %s, %s::vector, %s)",
            )

            # Bulk insert artist assignments
            assignment_rows = [
                (artist_id, int(cluster_id), float(weight))
                for artist_id, weights in artist_cluster_weights.items()
                for cluster_id, weight in weights
            ]
            if assignment_rows:
                execute_values(
                    cur,
                    "INSERT INTO artist_clusters (artist_id, cluster_id, weight) VALUES %s",
                    assignment_rows,
                )

            conn.commit()

    elapsed = time.perf_counter() - t0
    logger.info(
        "Saved %d clusters and %d artist assignments (%d rows) in %.2fs",
        len(cluster_infos), len(artist_cluster_weights),
        len(assignment_rows) if artist_cluster_weights else 0, elapsed,
    )


def get_cluster_centroids() -> tuple[list[np.ndarray], list[int]]:
    """Load cluster centroids from database."""
    centroids = []
    cluster_ids = []

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, centroid FROM scene_clusters ORDER BY id")
            for row in cur.fetchall():
                cluster_ids.append(row[0])
                centroid = _coerce_embedding(row[1])
                if centroid is not None and centroid.size > 0:
                    centroids.append(centroid)
                else:
                    cluster_ids.pop()

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


def assign_small_artists_to_clusters(
    cluster_infos: list[ClusterInfo],
) -> int:
    """
    Post-hoc nearest-centroid assignment for artists with fewer than
    ``cluster_min_tracks`` tracks that were excluded from the main clustering.
    They are assigned to the single nearest cluster with weight 1.0.

    Returns the number of artists assigned.
    """
    if not cluster_infos:
        return 0

    t0 = time.perf_counter()
    centroids = np.array([c.centroid for c in cluster_infos])
    cluster_ids = [c.cluster_id for c in cluster_infos]
    assigned = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Artists with at least 1 embedding but not yet clustered
            cur.execute("""
                SELECT a.id, AVG(te.embedding) as avg_embedding
                FROM artists a
                JOIN track_artists ta ON a.id = ta.artist_id
                JOIN track_embeddings te ON ta.track_id = te.track_id
                WHERE te.embedding IS NOT NULL
                  AND a.id NOT IN (SELECT DISTINCT artist_id FROM artist_clusters)
                GROUP BY a.id
                HAVING COUNT(te.embedding) >= 1
            """)
            rows = cur.fetchall()

        with conn.cursor() as cur:
            for row in rows:
                artist_id = str(row[0])
                emb = _coerce_embedding(row[1])
                if emb is None or emb.size == 0:
                    continue

                norm = np.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm

                sims = np.dot(centroids, emb)
                best_idx = int(np.argmax(sims))
                best_cluster = cluster_ids[best_idx]

                cur.execute("""
                    INSERT INTO artist_clusters (artist_id, cluster_id, weight)
                    VALUES (%s, %s, 1.0)
                    ON CONFLICT (artist_id, cluster_id) DO NOTHING
                """, (artist_id, int(best_cluster)))
                assigned += 1

    elapsed = time.perf_counter() - t0
    logger.info(
        "Post-hoc assigned %d small artists to nearest cluster in %.2fs",
        assigned, elapsed,
    )
    return assigned


# ---------------------------------------------------------------------------
# 7. Main pipeline entry point
# ---------------------------------------------------------------------------

async def generate_clusters(
    n_clusters: int | None = None,
    progress_callback: callable = None,
) -> dict[str, Any]:
    """
    Generate scene clusters from artist embeddings.

    Uses UMAP + HDBSCAN pipeline with tag-enriched embeddings.

    Args:
        n_clusters: Ignored (HDBSCAN auto-determines cluster count).
            Kept for interface compatibility.
        progress_callback: Optional (current, total, message) callback for SSE.

    Returns:
        Stats dict with timing, cluster metrics, and quality reports.
    """
    pipeline_start = time.perf_counter()

    stats: dict[str, Any] = {
        "artists": 0,
        "clusters": 0,
        "auto_tuned": True,  # HDBSCAN always auto-determines
        "algorithm": "hdbscan",
    }

    if progress_callback:
        progress_callback(0, 100, "Loading artist embeddings...")

    # Step 1: Load track-averaged embeddings
    track_embeddings = get_artist_embeddings()
    stats["artists"] = len(track_embeddings)

    if not track_embeddings:
        logger.warning("No artist embeddings found — skipping clustering")
        return stats

    # Step 2: Generate tag-enriched embeddings
    if progress_callback:
        progress_callback(10, 100, "Generating tag embeddings...")

    artist_tags = _get_artist_tags()
    tag_embeddings = _generate_tag_embeddings(
        list(track_embeddings.keys()), artist_tags,
    )

    # Step 3: Blend embeddings
    if progress_callback:
        progress_callback(20, 100, "Blending embeddings...")

    blended = _blend_embeddings(
        track_embeddings, tag_embeddings, settings.cluster_tag_weight,
    )

    # Step 4: Cluster
    if progress_callback:
        progress_callback(30, 100, "UMAP reduction + HDBSCAN clustering...")

    cluster_infos, artist_weights = compute_clusters(blended)
    stats["clusters"] = len(cluster_infos)
    stats["final_cluster_count"] = len(cluster_infos)

    # Step 5: Save
    if progress_callback:
        progress_callback(70, 100, "Saving clusters...")

    save_clusters(cluster_infos, artist_weights)

    # Step 6: Post-hoc assign small artists
    if progress_callback:
        progress_callback(80, 100, "Assigning small artists...")

    small_assigned = assign_small_artists_to_clusters(cluster_infos)
    stats["small_artists_assigned"] = small_assigned

    # Step 7: Quality metrics
    if progress_callback:
        progress_callback(90, 100, "Computing cluster quality metrics...")

    quality_reports = _compute_cluster_quality(cluster_infos, artist_weights)
    stats["quality"] = quality_reports

    # Summary stats
    concentrations = [r["tag_concentration"] for r in quality_reports]
    if concentrations:
        stats["avg_tag_concentration"] = round(
            sum(concentrations) / len(concentrations), 3,
        )
        low_coherence = sum(1 for c in concentrations if c < 0.25)
        stats["low_coherence_clusters"] = low_coherence

    pipeline_elapsed = time.perf_counter() - pipeline_start
    stats["total_time_seconds"] = round(pipeline_elapsed, 2)

    if progress_callback:
        progress_callback(100, 100, "Clustering complete")

    logger.info(
        "Clustering pipeline complete in %.1fs: %d clusters, "
        "avg tag concentration=%.3f, %d low-coherence clusters",
        pipeline_elapsed, stats["clusters"],
        stats.get("avg_tag_concentration", 0),
        stats.get("low_coherence_clusters", 0),
    )
    return stats
