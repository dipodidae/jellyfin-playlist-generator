"""Genre Manifold System (GMS) — offline build and query-time helpers.

Computes probabilistic genre identity vectors for each track using a weighted ensemble:
  0.35  kNN neighbourhood voting (embedding cosine similarity)
  0.30  Last.fm artist tag matching
  0.25  Direct track_genres tag matching
  0.10  Audio heuristics (BPM, brightness, loudness)

Results stored in:
  track_genre_probabilities  — per-track probability vector
  genre_manifold             — per-genre centroid embedding (384-dim)

Query-time helpers:
  get_genre_centroids()           — load centroids for a list of genre hints
  compute_genre_probability_score() — score a track against target genres
  compute_genre_drift_penalty()   — measure cumulative genre drift in a beam
  get_adjacent_genres()           — GENRE_GRAPH hop traversal with weight decay
"""

import json
import logging
import time
from collections import defaultdict
from typing import Callable

import numpy as np

from app.database_pg import get_connection
from app.trajectory.intent import GENRE_ALIASES, _ALIAS_TO_FAMILY, _BROAD_GENRES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Weighted genre adjacency graph
# ---------------------------------------------------------------------------
# edge weight = stylistic proximity [0, 1]; used for hop-decay expansion.
# Key design decision: thrash ≠ nwobhm ≠ speed — they are connected but
# at controlled distance so STRICT mode doesn't leak across subgenres.

GENRE_GRAPH: dict[str, dict[str, float]] = {
    "thrash metal": {
        "speed metal": 0.50,
        "death metal": 0.45,
        "heavy metal": 0.30,
        "black metal": 0.30,
        "groove metal": 0.25,
        "metalcore": 0.25,
    },
    "speed metal": {
        "thrash metal": 0.50,
        "heavy metal": 0.60,
        "nwobhm": 0.50,
        "power metal": 0.35,
    },
    "heavy metal": {
        "nwobhm": 0.70,
        "speed metal": 0.60,
        "doom metal": 0.25,
        "power metal": 0.35,
        "aor": 0.20,
    },
    "nwobhm": {
        "heavy metal": 0.70,
        "speed metal": 0.50,
        "power metal": 0.30,
        "doom metal": 0.20,
    },
    "death metal": {
        "thrash metal": 0.45,
        "black metal": 0.45,
        "doom metal": 0.30,
        "grindcore": 0.40,
    },
    "black metal": {
        "death metal": 0.45,
        "thrash metal": 0.30,
        "doom metal": 0.35,
        "ambient": 0.20,
        "atmospheric black metal": 0.70,
    },
    "doom metal": {
        "heavy metal": 0.30,
        "death metal": 0.30,
        "black metal": 0.35,
        "ambient": 0.25,
        "gothic metal": 0.35,
    },
    "power metal": {
        "heavy metal": 0.45,
        "speed metal": 0.40,
        "progressive metal": 0.35,
        "nwobhm": 0.30,
    },
    "progressive metal": {
        "power metal": 0.35,
        "heavy metal": 0.30,
        "progressive rock": 0.40,
        "doom metal": 0.20,
    },
    "grindcore": {
        "death metal": 0.40,
        "punk": 0.35,
        "thrash metal": 0.30,
    },
    "gothic metal": {
        "doom metal": 0.40,
        "darkwave": 0.40,
        "post-punk": 0.30,
        "industrial metal": 0.25,
    },
    "industrial metal": {
        "industrial": 0.65,
        "heavy metal": 0.35,
        "thrash metal": 0.25,
    },
    "metalcore": {
        "thrash metal": 0.30,
        "death metal": 0.35,
        "punk": 0.35,
    },
    "viking metal": {
        "black metal": 0.45,
        "folk metal": 0.55,
        "death metal": 0.30,
        "doom metal": 0.25,
    },
    "folk metal": {
        "viking metal": 0.55,
        "heavy metal": 0.30,
        "folk": 0.40,
    },
    "avant-garde metal": {
        "progressive metal": 0.40,
        "experimental": 0.50,
        "doom metal": 0.25,
    },
    "coldwave": {
        "darkwave": 0.80,
        "post-punk": 0.70,
        "synth-pop": 0.55,
        "new wave": 0.60,
        "industrial": 0.30,
    },
    "darkwave": {
        "coldwave": 0.80,
        "post-punk": 0.65,
        "gothic metal": 0.35,
        "synth-pop": 0.45,
        "new wave": 0.50,
    },
    "post-punk": {
        "darkwave": 0.65,
        "coldwave": 0.65,
        "new wave": 0.60,
        "punk": 0.50,
        "shoegaze": 0.30,
        "gothic metal": 0.30,
    },
    "synth-pop": {
        "coldwave": 0.55,
        "darkwave": 0.45,
        "new wave": 0.70,
        "electronic": 0.35,
    },
    "new wave": {
        "post-punk": 0.60,
        "synth-pop": 0.70,
        "coldwave": 0.55,
        "punk": 0.35,
    },
    "industrial": {
        "industrial metal": 0.65,
        "electronic": 0.40,
        "noise": 0.40,
        "darkwave": 0.30,
        "coldwave": 0.25,
        "ebm": 0.65,
    },
    "ambient": {
        "electronic": 0.40,
        "experimental": 0.35,
        "doom metal": 0.20,
        "post-rock": 0.30,
        "neofolk": 0.20,
    },
    "shoegaze": {
        "post-rock": 0.55,
        "post-punk": 0.40,
        "ambient": 0.30,
    },
    "punk": {
        "hardcore punk": 0.65,
        "post-punk": 0.50,
        "new wave": 0.40,
        "grindcore": 0.35,
        "metalcore": 0.30,
    },
    "rock": {
        "hard rock": 0.70,
        "heavy metal": 0.40,
        "progressive rock": 0.45,
    },
    "jazz": {
        "blues": 0.45,
        "experimental": 0.35,
        "ambient": 0.20,
    },
    "folk": {
        "neofolk": 0.65,
        "rock": 0.30,
        "ambient": 0.20,
        "folk metal": 0.35,
    },
    "neofolk": {
        "folk": 0.65,
        "ambient": 0.35,
        "industrial": 0.25,
        "folk metal": 0.30,
    },
    "noise": {
        "industrial": 0.45,
        "experimental": 0.55,
        "grindcore": 0.30,
    },
    "experimental": {
        "noise": 0.55,
        "ambient": 0.35,
        "avant-garde metal": 0.40,
        "jazz": 0.35,
    },
    "post-rock": {
        "shoegaze": 0.55,
        "ambient": 0.40,
        "progressive rock": 0.35,
    },
}


def get_adjacent_genres(genre: str, radius: int = 1) -> dict[str, float]:
    """BFS to `radius` hops from `genre`; weight = product of edge weights along path.

    Returns {genre_family: weight} for all genres reachable within `radius` hops.
    Source genre is not included. Broad genres filtered out at radius < 3.
    """
    family = _ALIAS_TO_FAMILY.get(genre.lower(), genre.lower())

    visited: dict[str, float] = {}
    frontier: list[tuple[str, float]] = [(family, 1.0)]

    for _ in range(radius):
        next_frontier: list[tuple[str, float]] = []
        for current, current_weight in frontier:
            for neighbor, edge_weight in GENRE_GRAPH.get(current, {}).items():
                new_weight = current_weight * edge_weight
                if neighbor == family:
                    continue
                if neighbor not in visited or new_weight > visited[neighbor]:
                    visited[neighbor] = new_weight
                    next_frontier.append((neighbor, new_weight))
        frontier = next_frontier
        if not frontier:
            break

    if radius < 3:
        visited = {g: w for g, w in visited.items() if g not in _BROAD_GENRES}

    return visited


# ---------------------------------------------------------------------------
# Internal data loaders
# ---------------------------------------------------------------------------

def _coerce_embedding(raw) -> np.ndarray | None:
    if raw is None:
        return None
    if isinstance(raw, np.ndarray):
        return raw.astype(np.float32, copy=False)
    if isinstance(raw, (list, tuple)):
        return np.asarray(raw, dtype=np.float32)
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("["):
            s = s[1:-1]
        arr = np.fromstring(s, sep=",", dtype=np.float32)
        return arr if arr.size > 0 else None
    return np.asarray(raw, dtype=np.float32)


def _load_all_embeddings() -> tuple[list[str], np.ndarray]:
    """Load all track embeddings. Returns (track_ids, L2-normalised matrix)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.id::text, te.embedding
                FROM track_embeddings te
                JOIN tracks t ON t.id = te.track_id
                WHERE te.embedding IS NOT NULL
                ORDER BY t.id
            """)
            rows = cur.fetchall()

    if not rows:
        return [], np.zeros((0, 384), dtype=np.float32)

    track_ids = [r[0] for r in rows]
    embs = []
    for r in rows:
        e = _coerce_embedding(r[1])
        embs.append(e if e is not None and e.size > 0 else np.zeros(384, dtype=np.float32))

    matrix = np.stack(embs, axis=0)  # (N, 384)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    matrix = matrix / norms
    return track_ids, matrix


def _load_track_lastfm_genres() -> dict[str, dict[str, float]]:
    """track_id → {genre_family: normalised_weight} from Last.fm artist tags."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ta.track_id::text, lt.name, alt.weight
                FROM track_artists ta
                JOIN artist_lastfm_tags alt ON alt.artist_id = ta.artist_id
                JOIN lastfm_tags lt ON lt.id = alt.tag_id
                WHERE ta.role = 'primary'
                  AND alt.weight >= 20
            """)
            rows = cur.fetchall()

    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for track_id, tag_name, weight in rows:
        family = _ALIAS_TO_FAMILY.get(tag_name.lower())
        if family:
            result[track_id][family] += (weight or 0) / 100.0

    out: dict[str, dict[str, float]] = {}
    for tid, dist in result.items():
        total = sum(dist.values())
        if total > 0:
            out[tid] = {k: v / total for k, v in dist.items()}
    return out


def _load_track_direct_genres() -> dict[str, dict[str, float]]:
    """track_id → {genre_family: normalised_count} from track_genres table."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tg.track_id::text, g.name
                FROM track_genres tg
                JOIN genres g ON tg.genre_id = g.id
            """)
            rows = cur.fetchall()

    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for track_id, genre_name in rows:
        family = _ALIAS_TO_FAMILY.get(genre_name.lower(), genre_name.lower())
        if family in GENRE_ALIASES:
            result[track_id][family] += 1.0

    out: dict[str, dict[str, float]] = {}
    for tid, dist in result.items():
        total = sum(dist.values())
        if total > 0:
            out[tid] = {k: v / total for k, v in dist.items()}
    return out


def _load_audio_features() -> dict[str, dict]:
    """track_id → {bpm, loudness, brightness} (all 0-1 normalised)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT track_id::text, bpm_norm, loudness_norm, brightness_norm
                FROM track_audio_features
                WHERE bpm_norm IS NOT NULL
            """)
            rows = cur.fetchall()
    return {
        r[0]: {"bpm": r[1] or 0.5, "loudness": r[2] or 0.5, "brightness": r[3] or 0.5}
        for r in rows
    }


def _audio_heuristic_genres(audio: dict) -> dict[str, float]:
    """Rough genre prior from BPM/loudness/brightness. Returns normalised dict."""
    bpm = audio["bpm"]
    loudness = audio["loudness"]
    brightness = audio["brightness"]
    probs: dict[str, float] = {}

    if bpm < 0.20 and loudness > 0.45:
        probs["doom metal"] = 0.45
    if bpm > 0.60 and loudness > 0.60 and 0.30 < brightness < 0.75:
        probs["thrash metal"] = 0.35
    if bpm > 0.78 and loudness > 0.68:
        probs["death metal"] = 0.25
        probs["grindcore"] = 0.20
    if bpm > 0.50 and brightness < 0.32 and loudness > 0.48:
        probs["black metal"] = 0.30
    if loudness < 0.28 and brightness < 0.30:
        probs["ambient"] = 0.40
    if 0.28 < bpm < 0.52 and loudness < 0.42 and brightness < 0.38:
        probs["darkwave"] = 0.22
        probs["coldwave"] = 0.18

    total = sum(probs.values())
    if total > 0:
        return {k: v / total for k, v in probs.items()}
    return {}


# ---------------------------------------------------------------------------
# kNN neighbourhood voting
# ---------------------------------------------------------------------------

def _compute_knn_votes(
    track_ids: list[str],
    matrix: np.ndarray,
    lastfm_genres: dict[str, dict[str, float]],
    direct_genres: dict[str, dict[str, float]],
    k: int = 20,
    batch_size: int = 500,
    progress_callback: Callable | None = None,
) -> dict[str, dict[str, float]]:
    """For each track, find top-k neighbours and aggregate their genre distributions."""
    n = len(track_ids)
    result: dict[str, dict[str, float]] = {}

    for batch_start in range(0, n, batch_size):
        batch_end = min(batch_start + batch_size, n)
        batch = matrix[batch_start:batch_end]  # (B, D)
        sims = (batch @ matrix.T).astype(np.float32)  # (B, N)

        for local_i, global_i in enumerate(range(batch_start, batch_end)):
            track_id = track_ids[global_i]
            sim_row = sims[local_i].copy()
            sim_row[global_i] = -2.0  # exclude self

            actual_k = min(k, n - 1)
            if actual_k <= 0:
                result[track_id] = {}
                continue

            top_k_idx = np.argpartition(sim_row, -actual_k)[-actual_k:]
            top_k_idx = top_k_idx[np.argsort(sim_row[top_k_idx])[::-1]]

            votes: dict[str, float] = defaultdict(float)
            total_w = 0.0

            for ni in top_k_idx:
                ni = int(ni)
                sim = float(sim_row[ni])
                if sim <= 0:
                    continue
                total_w += sim
                nid = track_ids[ni]
                for fam, fw in lastfm_genres.get(nid, {}).items():
                    votes[fam] += sim * fw
                for fam, fw in direct_genres.get(nid, {}).items():
                    votes[fam] += sim * fw * 0.5

            if total_w > 0:
                result[track_id] = {fam: w / total_w for fam, w in votes.items()}
            else:
                result[track_id] = {}

        if progress_callback:
            pct = int((batch_end / n) * 60) + 12  # kNN covers 12–72% of total
            progress_callback(pct, 100, f"kNN votes {batch_end}/{n} tracks")

    return result


# ---------------------------------------------------------------------------
# Ensemble
# ---------------------------------------------------------------------------

def _ensemble(
    track_id: str,
    knn: dict[str, float],
    lastfm: dict[str, dict[str, float]],
    direct: dict[str, dict[str, float]],
    audio: dict[str, dict],
) -> dict[str, float]:
    """Weighted ensemble of all genre signals for one track."""
    ensemble: dict[str, float] = defaultdict(float)
    for fam, w in knn.items():
        ensemble[fam] += 0.35 * w
    for fam, w in lastfm.get(track_id, {}).items():
        ensemble[fam] += 0.30 * w
    for fam, w in direct.get(track_id, {}).items():
        ensemble[fam] += 0.25 * w
    if track_id in audio:
        for fam, w in _audio_heuristic_genres(audio[track_id]).items():
            ensemble[fam] += 0.10 * w

    if not ensemble:
        return {}

    total = sum(ensemble.values())
    pruned = {fam: w / total for fam, w in ensemble.items() if w / total >= 0.02}
    total2 = sum(pruned.values())
    return {fam: w / total2 for fam, w in pruned.items()} if total2 > 0 else {}


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_genre_manifold(progress_callback: Callable | None = None) -> dict:
    """Offline build: compute genre prob vectors for all tracks + genre centroids.

    Called by /enrich/genre-manifold/stream. progress_callback(current, total, msg).
    """
    def report(cur, tot, msg):
        logger.info(f"[GMS] {msg}")
        if progress_callback:
            progress_callback(cur, tot, msg)

    t0 = time.time()

    report(0, 100, "Loading track embeddings...")
    track_ids, matrix = _load_all_embeddings()
    n = len(track_ids)
    if n == 0:
        return {"processed": 0, "success": 0, "failed": 0, "skipped": 0, "centroids": 0}

    report(5, 100, f"Loaded {n} embeddings. Loading Last.fm tags...")
    lastfm = _load_track_lastfm_genres()

    report(8, 100, "Loading direct genre tags...")
    direct = _load_track_direct_genres()

    report(10, 100, "Loading audio features...")
    audio = _load_audio_features()

    report(12, 100, "Computing kNN neighbourhood votes...")
    knn_votes = _compute_knn_votes(
        track_ids, matrix, lastfm, direct, k=20, batch_size=500,
        progress_callback=progress_callback,
    )

    report(75, 100, "Building ensemble genre probabilities...")
    track_probs: dict[str, dict[str, float]] = {
        tid: _ensemble(tid, knn_votes.get(tid, {}), lastfm, direct, audio)
        for tid in track_ids
    }

    report(80, 100, "Writing to track_genre_probabilities...")
    success = failed = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS track_genre_probabilities (
                    track_id    UUID PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                    genre_probs JSONB NOT NULL DEFAULT '{}',
                    top_genre   TEXT,
                    computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            try:
                from psycopg2.extras import execute_values
                rows_to_insert = [
                    (tid, json.dumps(probs), max(probs, key=probs.get) if probs else None)
                    for tid, probs in track_probs.items()
                ]
                execute_values(cur, """
                    INSERT INTO track_genre_probabilities
                        (track_id, genre_probs, top_genre, computed_at)
                    VALUES %s
                    ON CONFLICT (track_id) DO UPDATE
                        SET genre_probs = EXCLUDED.genre_probs,
                            top_genre   = EXCLUDED.top_genre,
                            computed_at = EXCLUDED.computed_at
                """, rows_to_insert, template="(%s::uuid, %s::jsonb, %s, now())")
                success = len(rows_to_insert)
            except Exception as e:
                logger.warning(f"Batch upsert failed, falling back: {e}")
                conn.rollback()
                for tid, probs in track_probs.items():
                    try:
                        cur.execute("""
                            INSERT INTO track_genre_probabilities
                                (track_id, genre_probs, top_genre, computed_at)
                            VALUES (%s::uuid, %s::jsonb, %s, now())
                            ON CONFLICT (track_id) DO UPDATE
                                SET genre_probs = EXCLUDED.genre_probs,
                                    top_genre   = EXCLUDED.top_genre,
                                    computed_at = EXCLUDED.computed_at
                        """, (tid, json.dumps(probs), max(probs, key=probs.get) if probs else None))
                        success += 1
                    except Exception as e2:
                        logger.debug(f"Track {tid} upsert failed: {e2}")
                        failed += 1
        conn.commit()

    report(90, 100, "Computing genre centroids...")
    tid_to_idx = {tid: i for i, tid in enumerate(track_ids)}
    genre_embs: dict[str, list[tuple[np.ndarray, float]]] = defaultdict(list)
    for tid, probs in track_probs.items():
        if tid not in tid_to_idx:
            continue
        emb = matrix[tid_to_idx[tid]]
        for fam, prob in probs.items():
            if prob >= 0.10:
                genre_embs[fam].append((emb, prob))

    centroids_written = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS genre_manifold (
                    genre_family TEXT PRIMARY KEY,
                    centroid     VECTOR(384),
                    track_count  INTEGER NOT NULL DEFAULT 0,
                    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            for fam, pairs in genre_embs.items():
                if len(pairs) < 3:
                    continue
                embs_arr = np.stack([e for e, _ in pairs])
                ws = np.array([w for _, w in pairs])
                ws /= ws.sum()
                centroid = np.average(embs_arr, axis=0, weights=ws)
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid /= norm
                vec_str = "[" + ",".join(f"{v:.6f}" for v in centroid.tolist()) + "]"
                try:
                    cur.execute("""
                        INSERT INTO genre_manifold
                            (genre_family, centroid, track_count, updated_at)
                        VALUES (%s, %s::vector, %s, now())
                        ON CONFLICT (genre_family) DO UPDATE
                            SET centroid    = EXCLUDED.centroid,
                                track_count = EXCLUDED.track_count,
                                updated_at  = EXCLUDED.updated_at
                    """, (fam, vec_str, len(pairs)))
                    centroids_written += 1
                except Exception as e:
                    logger.warning(f"Centroid write failed for {fam}: {e}")
        conn.commit()

    elapsed = round(time.time() - t0, 1)
    report(100, 100, f"Done: {success} tracks, {centroids_written} centroids, {elapsed}s")
    logger.info(f"[GMS] Built: {success} tracks, {centroids_written} centroids in {elapsed}s")

    return {
        "processed": n,
        "success": success,
        "failed": failed,
        "skipped": 0,
        "centroids": centroids_written,
    }


# ---------------------------------------------------------------------------
# Query-time helpers
# ---------------------------------------------------------------------------

def get_genre_centroids(genre_hints: list[str]) -> dict[str, list[float]]:
    """Fetch centroid vectors from genre_manifold for the given genre hints."""
    if not genre_hints:
        return {}
    families = list({_ALIAS_TO_FAMILY.get(h.lower(), h.lower()) for h in genre_hints})
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT genre_family, centroid::text
                    FROM genre_manifold
                    WHERE genre_family = ANY(%s)
                """, (families,))
                rows = cur.fetchall()
    except Exception as e:
        logger.warning(f"get_genre_centroids failed: {e}")
        return {}

    result: dict[str, list[float]] = {}
    for fam, raw in rows:
        if raw is None:
            continue
        s = raw.strip()
        if s.startswith("["):
            s = s[1:-1]
        vec = np.fromstring(s, sep=",", dtype=np.float32)
        if vec.size > 0:
            result[fam] = vec.tolist()
    return result


def build_hybrid_query_embedding(
    prompt_embedding: list[float],
    genre_centroids: dict[str, list[float]],
    genre_mode: str,
) -> list[float]:
    """Blend prompt embedding with genre centroid mean for biased retrieval.

    α controls how strongly the genre centroid pulls the query vector:
      strict      α=0.55 — genre dominates retrieval direction
      balanced    α=0.30 — moderate pull
      exploratory α=0.12 — minimal pull
    """
    if not genre_centroids:
        return prompt_embedding

    alpha = {"strict": 0.55, "balanced": 0.30, "exploratory": 0.12}.get(genre_mode, 0.30)

    centroid_mean = np.mean(
        [np.array(v, dtype=np.float32) for v in genre_centroids.values()], axis=0
    )

    query = np.array(prompt_embedding, dtype=np.float32) + alpha * centroid_mean
    norm = np.linalg.norm(query)
    if norm > 0:
        query /= norm
    return query.tolist()


def compute_genre_probability_score(
    track_probs: dict[str, float],
    target_genres: list[str],
    adjacent_genres: dict[str, float],
    genre_mode: str,
) -> float:
    """Score a track's genre probability against target genres.

    STRICT:      direct P(target genres) only
    BALANCED:    direct + 0.4 * adjacent contribution
    EXPLORATORY: same as balanced at 0.5x total
    """
    if not track_probs:
        return 0.0

    target_families = {_ALIAS_TO_FAMILY.get(g.lower(), g.lower()) for g in target_genres}
    direct = min(1.0, sum(track_probs.get(f, 0.0) for f in target_families))

    if genre_mode == "strict":
        return direct

    adj = 0.0
    for adj_fam, adj_w in adjacent_genres.items():
        fam = _ALIAS_TO_FAMILY.get(adj_fam.lower(), adj_fam.lower())
        if fam not in target_families:
            adj += track_probs.get(fam, 0.0) * adj_w
    adj = min(0.40, adj)

    score = min(1.0, direct + 0.4 * adj)
    return score * 0.5 if genre_mode == "exploratory" else score


def compute_genre_drift_penalty(
    cumulative_dist: dict[str, float],
    target_dist: dict[str, float],
) -> float:
    """L1 distance between running and target genre distributions [0, 1].

    Values above 0.35 signal the beam has drifted significantly from the
    target genre manifold.
    """
    if not cumulative_dist or not target_dist:
        return 0.0
    all_g = set(cumulative_dist) | set(target_dist)
    drift = sum(abs(cumulative_dist.get(g, 0.0) - target_dist.get(g, 0.0)) for g in all_g)
    return min(1.0, drift / 2.0)
