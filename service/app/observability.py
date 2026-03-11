"""
Observability and caching for v4 playlist generation.

Implements:
- Generation metrics logging
- Track usage memory with time decay
- TTL caching for embeddings and semantic search
- Cold start handling
"""

import logging
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.database_pg import get_connection

logger = logging.getLogger(__name__)


# Simple TTL cache implementation
_cache: dict[str, tuple[Any, float]] = {}
_cache_ttl = 300  # 5 minutes default


def cache_get(key: str) -> Any | None:
    """Get value from cache if not expired."""
    if key in _cache:
        value, expires_at = _cache[key]
        if time.time() < expires_at:
            return value
        else:
            del _cache[key]
    return None


def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    """Set value in cache with TTL."""
    expires_at = time.time() + (ttl or _cache_ttl)
    _cache[key] = (value, expires_at)


def cache_clear() -> None:
    """Clear all cached values."""
    _cache.clear()


def log_generation(
    prompt: str,
    arc_type: str,
    playlist_length: int,
    generation_time_ms: int,
    metrics: dict[str, Any],
) -> None:
    """Log playlist generation metrics to database."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO playlist_generation_log (
                        prompt, arc_type, playlist_length, generation_time_ms,
                        trajectory_deviation, pool_entropy, avg_transition_cost,
                        beam_dead_ends, constraint_rejections, bridge_tracks_used
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    prompt[:1000],  # Truncate long prompts
                    arc_type,
                    playlist_length,
                    generation_time_ms,
                    metrics.get("trajectory_deviation", 0),
                    metrics.get("pool_entropy", 0),
                    metrics.get("avg_transition_cost", 0),
                    metrics.get("beam_dead_ends", 0),
                    metrics.get("constraint_rejections", 0),
                    metrics.get("bridge_tracks_used", 0),
                ))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to log generation metrics: {e}")


def update_track_usage(track_ids: list[str]) -> None:
    """Update track usage for playlist memory."""
    if not track_ids:
        return
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for track_id in track_ids:
                    cur.execute("""
                        INSERT INTO track_usage (track_id, last_used_at, usage_count)
                        VALUES (%s, now(), 1)
                        ON CONFLICT (track_id) DO UPDATE SET
                            last_used_at = now(),
                            usage_count = track_usage.usage_count + 1
                    """, (track_id,))
                conn.commit()
    except Exception as e:
        logger.error(f"Failed to update track usage: {e}")


def get_track_usage_penalty(track_id: str, decay_days: float = 30.0) -> float:
    """
    Get usage penalty for a track with time decay.
    
    Penalty decays exponentially: usage_count * exp(-days_since / decay_days) * 0.1
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT usage_count, 
                           EXTRACT(EPOCH FROM (now() - last_used_at)) / 86400 as days_since
                    FROM track_usage
                    WHERE track_id = %s
                """, (track_id,))
                
                row = cur.fetchone()
                if not row:
                    return 0.0
                
                usage_count, days_since = row
                if days_since is None:
                    days_since = 0
                
                # Exponential decay
                penalty = usage_count * math.exp(-days_since / decay_days) * 0.1
                return min(penalty, 0.5)  # Cap at 0.5
                
    except Exception as e:
        logger.error(f"Failed to get track usage: {e}")
        return 0.0


def get_embedding_coverage() -> float:
    """Get percentage of tracks with embeddings."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM tracks")
                total = cur.fetchone()[0]
                
                if total == 0:
                    return 0.0
                
                cur.execute("SELECT COUNT(*) FROM track_embeddings WHERE status = 'ready'")
                with_embeddings = cur.fetchone()[0]
                
                return with_embeddings / total
    except Exception as e:
        logger.error(f"Failed to get embedding coverage: {e}")
        return 0.0


def check_cold_start() -> dict[str, Any]:
    """
    Check cold start status and return recommendations.
    """
    coverage = get_embedding_coverage()
    
    status = {
        "embedding_coverage": coverage,
        "ready_for_generation": coverage >= 0.1,
        "quality_level": "low" if coverage < 0.3 else "medium" if coverage < 0.7 else "high",
        "recommendation": None,
    }
    
    if coverage < 0.1:
        status["recommendation"] = "Run embedding enrichment before generating playlists"
    elif coverage < 0.3:
        status["recommendation"] = "Playlist quality may be limited. Consider enriching more tracks."
    
    return status


def get_generation_stats(days: int = 7) -> dict[str, Any]:
    """Get generation statistics for the last N days."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_generations,
                        AVG(generation_time_ms) as avg_time_ms,
                        AVG(playlist_length) as avg_length,
                        AVG(trajectory_deviation) as avg_deviation,
                        AVG(pool_entropy) as avg_entropy
                    FROM playlist_generation_log
                    WHERE created_at > now() - interval '%s days'
                """, (days,))
                
                row = cur.fetchone()
                if not row:
                    return {}
                
                return {
                    "total_generations": row[0] or 0,
                    "avg_time_ms": round(row[1] or 0, 1),
                    "avg_length": round(row[2] or 0, 1),
                    "avg_deviation": round(row[3] or 0, 3),
                    "avg_entropy": round(row[4] or 0, 3),
                    "period_days": days,
                }
    except Exception as e:
        logger.error(f"Failed to get generation stats: {e}")
        return {}


# Cached embedding lookup
@lru_cache(maxsize=1000)
def get_cached_embedding_hash(prompt_hash: str) -> str | None:
    """Cache key for prompt embeddings (uses hash for LRU cache)."""
    return prompt_hash


def get_cached_prompt_embedding(prompt: str) -> list[float] | None:
    """Get cached prompt embedding."""
    import hashlib
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
    cache_key = f"prompt_emb:{prompt_hash}"
    return cache_get(cache_key)


def set_cached_prompt_embedding(prompt: str, embedding: list[float]) -> None:
    """Cache prompt embedding."""
    import hashlib
    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
    cache_key = f"prompt_emb:{prompt_hash}"
    cache_set(cache_key, embedding)


def get_cached_semantic_results(prompt_hash: str, limit: int) -> list[Any] | None:
    """Get cached semantic search results."""
    cache_key = f"semantic:{prompt_hash}:{limit}"
    return cache_get(cache_key)


def set_cached_semantic_results(prompt_hash: str, limit: int, results: list[Any]) -> None:
    """Cache semantic search results."""
    cache_key = f"semantic:{prompt_hash}:{limit}"
    cache_set(cache_key, results)
