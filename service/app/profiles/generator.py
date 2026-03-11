"""Semantic track profile generation from genre/tag heuristics."""

import logging
from typing import Any

from app.database_pg import get_cursor, get_connection

logger = logging.getLogger(__name__)

# Energy keywords (0-1 scale)
ENERGY_KEYWORDS = {
    # High energy (0.8-1.0)
    'death metal': 0.95,
    'thrash metal': 0.95,
    'grindcore': 1.0,
    'powerviolence': 1.0,
    'hardcore': 0.9,
    'metalcore': 0.85,
    'deathcore': 0.9,
    'industrial': 0.8,
    'techno': 0.85,
    'gabber': 1.0,
    'speedcore': 1.0,
    'drum and bass': 0.85,
    'punk': 0.85,
    'power metal': 0.85,
    'speed metal': 0.9,
    'crossover': 0.85,

    # Medium-high energy (0.6-0.8)
    'black metal': 0.75,
    'heavy metal': 0.7,
    'rock': 0.6,
    'hard rock': 0.7,
    'alternative rock': 0.6,
    'progressive metal': 0.65,
    'melodic death metal': 0.8,
    'trance': 0.75,
    'house': 0.7,
    'electronic': 0.6,
    'synthwave': 0.65,
    'ebm': 0.7,

    # Medium energy (0.4-0.6)
    'progressive rock': 0.5,
    'post-rock': 0.45,
    'post-metal': 0.5,
    'shoegaze': 0.45,
    'indie': 0.5,
    'alternative': 0.5,
    'new wave': 0.55,
    'synth-pop': 0.55,
    'pop': 0.55,

    # Low-medium energy (0.2-0.4)
    'doom metal': 0.35,
    'stoner': 0.4,
    'sludge': 0.45,
    'gothic': 0.35,
    'darkwave': 0.35,
    'trip-hop': 0.35,
    'downtempo': 0.3,
    'chillout': 0.25,

    # Low energy (0.0-0.2)
    'ambient': 0.15,
    'dark ambient': 0.1,
    'drone': 0.1,
    'funeral doom': 0.2,
    'folk': 0.3,
    'acoustic': 0.25,
    'classical': 0.3,
    'neoclassical': 0.25,
    'meditation': 0.05,
    'sleep': 0.05,
}

# Darkness keywords (0-1 scale, 1 = darkest)
DARKNESS_KEYWORDS = {
    # Very dark (0.8-1.0)
    'black metal': 0.95,
    'dark ambient': 1.0,
    'funeral doom': 0.95,
    'depressive': 1.0,
    'suicidal': 1.0,
    'doom metal': 0.85,
    'death metal': 0.8,
    'gothic': 0.8,
    'darkwave': 0.85,
    'industrial': 0.75,
    'noise': 0.8,
    'harsh noise': 0.9,

    # Dark (0.6-0.8)
    'sludge': 0.7,
    'stoner': 0.6,
    'post-metal': 0.65,
    'drone': 0.7,
    'atmospheric black metal': 0.8,
    'blackgaze': 0.7,
    'deathcore': 0.7,
    'grindcore': 0.65,

    # Neutral-dark (0.4-0.6)
    'heavy metal': 0.5,
    'thrash metal': 0.55,
    'progressive metal': 0.5,
    'metalcore': 0.55,
    'hardcore': 0.5,
    'post-rock': 0.45,
    'shoegaze': 0.45,
    'trip-hop': 0.5,
    'ebm': 0.6,

    # Neutral (0.3-0.5)
    'rock': 0.4,
    'alternative': 0.4,
    'electronic': 0.4,
    'techno': 0.45,
    'house': 0.35,
    'trance': 0.35,
    'progressive rock': 0.4,

    # Light (0.1-0.3)
    'pop': 0.25,
    'indie pop': 0.25,
    'synth-pop': 0.3,
    'new wave': 0.35,
    'power metal': 0.3,
    'symphonic metal': 0.35,
    'folk': 0.3,

    # Very light (0.0-0.2)
    'happy': 0.1,
    'uplifting': 0.1,
    'cheerful': 0.05,
    'summer': 0.15,
    'party': 0.2,
}

# Tempo keywords (relative, 0-1 scale)
TEMPO_KEYWORDS = {
    # Very fast (0.8-1.0)
    'grindcore': 1.0,
    'speedcore': 1.0,
    'gabber': 0.95,
    'thrash metal': 0.85,
    'death metal': 0.8,
    'speed metal': 0.9,
    'powerviolence': 0.95,
    'drum and bass': 0.85,
    'hardcore techno': 0.9,

    # Fast (0.6-0.8)
    'black metal': 0.75,
    'punk': 0.75,
    'hardcore': 0.7,
    'metalcore': 0.7,
    'power metal': 0.7,
    'techno': 0.7,
    'trance': 0.7,

    # Medium (0.4-0.6)
    'heavy metal': 0.55,
    'rock': 0.5,
    'house': 0.55,
    'electronic': 0.5,
    'progressive metal': 0.5,
    'alternative': 0.5,
    'pop': 0.5,

    # Slow (0.2-0.4)
    'doom metal': 0.25,
    'sludge': 0.3,
    'stoner': 0.35,
    'trip-hop': 0.35,
    'downtempo': 0.3,
    'post-rock': 0.4,
    'shoegaze': 0.4,

    # Very slow (0.0-0.2)
    'funeral doom': 0.1,
    'drone': 0.1,
    'ambient': 0.15,
    'dark ambient': 0.1,
    'meditation': 0.05,
}

# Texture keywords (busy vs sparse, complexity, 0-1 scale)
TEXTURE_KEYWORDS = {
    # Very dense (0.8-1.0)
    'grindcore': 1.0,
    'death metal': 0.9,
    'technical death metal': 0.95,
    'mathcore': 0.95,
    'progressive metal': 0.8,
    'symphonic metal': 0.85,
    'orchestral': 0.85,
    'noise': 0.9,

    # Dense (0.6-0.8)
    'black metal': 0.75,
    'thrash metal': 0.75,
    'metalcore': 0.7,
    'power metal': 0.7,
    'drum and bass': 0.7,
    'industrial': 0.65,

    # Medium (0.4-0.6)
    'heavy metal': 0.55,
    'rock': 0.5,
    'alternative': 0.5,
    'electronic': 0.5,
    'techno': 0.55,
    'house': 0.5,
    'post-metal': 0.5,

    # Sparse (0.2-0.4)
    'doom metal': 0.35,
    'stoner': 0.4,
    'post-rock': 0.4,
    'shoegaze': 0.45,
    'trip-hop': 0.35,
    'folk': 0.35,
    'acoustic': 0.3,

    # Very sparse (0.0-0.2)
    'ambient': 0.15,
    'dark ambient': 0.1,
    'drone': 0.05,
    'minimal': 0.2,
    'minimalist': 0.15,
}


def score_dimension(tags: list[str], keyword_map: dict[str, float], default: float = 0.5) -> float:
    """Score a dimension based on tag matches."""
    if not tags:
        return default

    scores = []
    weights = []

    for tag in tags:
        tag_lower = tag.lower()

        # Exact match
        if tag_lower in keyword_map:
            scores.append(keyword_map[tag_lower])
            weights.append(1.0)
            continue

        # Partial match (tag contains keyword or keyword contains tag)
        for keyword, score in keyword_map.items():
            if keyword in tag_lower or tag_lower in keyword:
                scores.append(score)
                weights.append(0.5)  # Lower weight for partial matches
                break

    if not scores:
        return default

    # Weighted average
    total_weight = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_weight


# Alias for backward compatibility
DENSITY_KEYWORDS = TEXTURE_KEYWORDS


def compute_track_profile(genres: list[str], tags: list[str]) -> dict[str, float]:
    """Compute semantic profile for a track from its genres and tags."""
    all_tags = genres + tags

    return {
        'energy': score_dimension(all_tags, ENERGY_KEYWORDS),
        'darkness': score_dimension(all_tags, DARKNESS_KEYWORDS),
        'tempo': score_dimension(all_tags, TEMPO_KEYWORDS),
        'texture': score_dimension(all_tags, TEXTURE_KEYWORDS),
    }


def get_track_tags(cur, track_id: str) -> tuple[list[str], list[str]]:
    """Get genres and Last.fm tags for a track."""
    # Get genres
    cur.execute("""
        SELECT g.name FROM genres g
        JOIN track_genres tg ON g.id = tg.genre_id
        WHERE tg.track_id = %s
    """, (track_id,))
    genres = [row[0] for row in cur.fetchall()]

    # Get Last.fm tags
    cur.execute("""
        SELECT lt.name FROM lastfm_tags lt
        JOIN track_lastfm_tags tlt ON lt.id = tlt.tag_id
        WHERE tlt.track_id = %s
        ORDER BY tlt.weight DESC
        LIMIT 20
    """, (track_id,))
    tags = [row[0] for row in cur.fetchall()]

    # If no track tags, try artist tags
    if not tags:
        cur.execute("""
            SELECT DISTINCT lt.name FROM lastfm_tags lt
            JOIN artist_lastfm_tags alt ON lt.id = alt.tag_id
            JOIN track_artists ta ON ta.artist_id = alt.artist_id
            WHERE ta.track_id = %s
            ORDER BY alt.weight DESC
            LIMIT 20
        """, (track_id,))
        tags = [row[0] for row in cur.fetchall()]

    return genres, tags


async def generate_profiles(
    progress_callback: callable = None,
    batch_size: int = 500
) -> dict[str, int]:
    """Generate semantic profiles for tracks that don't have them.

    Returns:
        Stats dict with counts
    """
    stats = {
        "processed": 0,
        "created": 0,
        "skipped": 0,
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get tracks without profiles
            cur.execute("""
                SELECT t.id FROM tracks t
                LEFT JOIN track_profiles tp ON t.id = tp.track_id
                WHERE tp.track_id IS NULL
            """)
            track_ids = [row[0] for row in cur.fetchall()]

            if not track_ids:
                logger.info("All tracks have profiles")
                return stats

            logger.info(f"Generating profiles for {len(track_ids)} tracks")

            if progress_callback:
                progress_callback(0, len(track_ids), f"Generating profiles for {len(track_ids)} tracks...")

            for i, track_id in enumerate(track_ids):
                genres, tags = get_track_tags(cur, str(track_id))

                if not genres and not tags:
                    stats["skipped"] += 1
                    continue

                profile = compute_track_profile(genres, tags)

                cur.execute("""
                    INSERT INTO track_profiles (track_id, energy, darkness, tempo, texture)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (track_id) DO UPDATE SET
                        energy = EXCLUDED.energy,
                        darkness = EXCLUDED.darkness,
                        tempo = EXCLUDED.tempo,
                        texture = EXCLUDED.texture,
                        computed_at = now()
                """, (track_id, profile['energy'], profile['darkness'],
                      profile['tempo'], profile['texture']))

                stats["created"] += 1
                stats["processed"] += 1

                # Commit and report progress
                if (i + 1) % batch_size == 0:
                    conn.commit()
                    if progress_callback:
                        progress_callback(i + 1, len(track_ids), f"Generated {i + 1}/{len(track_ids)} profiles")
                    logger.info(f"Generated {i + 1}/{len(track_ids)} profiles")

            conn.commit()

    logger.info(f"Profile generation complete: {stats}")
    return stats
