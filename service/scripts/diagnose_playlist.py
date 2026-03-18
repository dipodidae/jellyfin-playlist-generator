#!/usr/bin/env python3
"""
Playlist quality diagnostic script.

Runs prompts through the v4 composer and dumps detailed scoring data
for analysis. Outputs to both console and a log file.

Usage:
    cd service
    .venv/bin/python3 -m scripts.diagnose_playlist [--prompts "prompt1" "prompt2"] [--size 25]

Defaults to running "pure evil 80s thrash" and "coldwave" if no prompts given.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Ensure the service app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.trajectory.composer_v4 import compose_playlist_v4, PlaylistResult
from app.trajectory.intent import parse_prompt, PlaylistIntent
from app.embeddings.generator import search_tracks_by_text, generate_embedding, search_similar_tracks
from app.database_pg import get_connection

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
logger = logging.getLogger("diagnose")


def get_track_genres_from_db(track_ids: list[str]) -> dict[str, list[str]]:
    """Fetch genres for a list of track IDs from the database."""
    if not track_ids:
        return {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tg.track_id, g.name
                FROM track_genres tg
                JOIN genres g ON tg.genre_id = g.id
                WHERE tg.track_id = ANY(%s::uuid[])
            """, (track_ids,))
            result: dict[str, list[str]] = {}
            for row in cur.fetchall():
                tid = str(row[0])
                result.setdefault(tid, []).append(row[1])
            return result


def run_raw_semantic_search(prompt: str, limit: int = 50) -> list[dict]:
    """Run a raw semantic search (no trajectory, no scoring) to see what embeddings find."""
    results = search_tracks_by_text(prompt, limit=limit)
    # Enrich with genres
    track_ids = [r["id"] for r in results]
    genres_map = get_track_genres_from_db(track_ids)
    for r in results:
        r["genres"] = genres_map.get(r["id"], [])
    return results


def run_composer(prompt: str, size: int = 25) -> PlaylistResult:
    """Run the full v4 composer pipeline."""
    return compose_playlist_v4(prompt, size)


def format_intent(intent: PlaylistIntent) -> dict:
    """Format PlaylistIntent as a serializable dict."""
    return {
        "arc_type": intent.arc_type.value,
        "prompt_type": intent.prompt_type.value if intent.prompt_type else None,
        "genre_hints": intent.genre_hints,
        "genre_hints_primary": sorted(intent.genre_hints_primary) if intent.genre_hints_primary else [],
        "mood_keywords": intent.mood_keywords,
        "year_range": intent.year_range,
        "dimension_weights": {
            "energy": intent.dimension_weights.energy,
            "tempo": intent.dimension_weights.tempo,
            "darkness": intent.dimension_weights.darkness,
            "texture": intent.dimension_weights.texture,
        } if intent.dimension_weights else None,
    }


def format_track(track, position: int, intent: PlaylistIntent) -> dict:
    """Format a CandidateTrack with full scoring details."""
    # Get trajectory target at this position
    target = None
    if intent.trajectory_curve:
        t = position / max(1, 24)  # approximate, actual depends on playlist length
        try:
            tp = intent.trajectory_curve.evaluate(t)
            target = {
                "energy": round(tp.energy, 3),
                "tempo": round(tp.tempo, 3),
                "darkness": round(tp.darkness, 3),
                "texture": round(tp.texture, 3),
            }
        except Exception:
            pass

    return {
        "position": position,
        "title": track.title,
        "artist": track.artist_name,
        "album": track.album_name,
        "year": track.year,
        "genres": track.genres or [],
        "scores": {
            "semantic": round(track.semantic_score, 4),
            "keyword": round(track.keyword_score, 4),
            "trajectory": round(track.trajectory_score, 4),
            "genre_match": round(track.genre_match_score, 4),
            "gravity_penalty": round(track.gravity_penalty, 4),
            "duration_penalty": round(track.duration_penalty, 4),
            "year_score": round(track.year_score, 4),
            "usage_penalty": round(track.usage_penalty, 4),
            "total": round(track.total_score, 4),
        },
        "weights": {
            "semantic": track._w_semantic,
            "trajectory": track._w_trajectory,
            "genre": track._w_genre,
            "gravity": track._w_gravity,
            "duration": track._w_duration,
        },
        "profile": {
            "energy": round(track.energy, 3),
            "tempo": round(track.tempo, 3),
            "darkness": round(track.darkness, 3),
            "texture": round(track.texture, 3),
        },
        "trajectory_target": target,
    }


def diagnose_prompt(prompt: str, size: int = 25) -> dict:
    """Run full diagnosis for a single prompt."""
    logger.info(f"\n{'='*80}")
    logger.info(f"DIAGNOSING: \"{prompt}\"")
    logger.info(f"{'='*80}")

    # Phase 1: Raw semantic search
    logger.info("\n--- Phase 1: Raw Semantic Search (top 30) ---")
    raw_results = run_raw_semantic_search(prompt, limit=30)
    for i, r in enumerate(raw_results[:15]):
        genres_str = ", ".join(r["genres"][:5]) if r["genres"] else "NO GENRES"
        logger.info(
            f"  {i+1:2d}. [{r['similarity']:.3f}] {r['artist_name']} - {r['title']} "
            f"({r['year'] or '?'}) [{genres_str}]"
        )
    if len(raw_results) > 15:
        logger.info(f"  ... and {len(raw_results) - 15} more")

    # Phase 2: Intent parsing
    logger.info("\n--- Phase 2: Intent Parsing ---")
    intent = parse_prompt(prompt, target_size=size)
    intent_data = format_intent(intent)
    for k, v in intent_data.items():
        logger.info(f"  {k}: {v}")

    # Phase 3: Full composer
    logger.info("\n--- Phase 3: Full V4 Composer ---")
    t0 = time.time()
    result = run_composer(prompt, size)
    elapsed = time.time() - t0
    logger.info(f"  Generated {len(result.tracks)} tracks in {elapsed:.1f}s")
    logger.info(f"  Metrics: {json.dumps(result.metrics, indent=2, default=str)}")

    # Phase 4: Detailed track analysis
    logger.info("\n--- Phase 4: Track Analysis ---")
    tracks_data = []
    for i, track in enumerate(result.tracks):
        td = format_track(track, i, result.intent)
        tracks_data.append(td)

        genres_str = ", ".join(td["genres"][:5]) if td["genres"] else "NO GENRES"
        logger.info(
            f"  {i+1:2d}. {td['artist']:30s} - {td['title'][:40]:40s} "
            f"sem={td['scores']['semantic']:.3f} "
            f"traj={td['scores']['trajectory']:.3f} "
            f"genre={td['scores']['genre_match']:.3f} "
            f"grav={td['scores']['gravity_penalty']:.3f} "
            f"TOTAL={td['scores']['total']:.3f} "
            f"[{genres_str}]"
        )

    # Genre coverage analysis
    all_genres: dict[str, int] = {}
    for td in tracks_data:
        for g in td["genres"]:
            all_genres[g] = all_genres.get(g, 0) + 1

    logger.info("\n--- Genre Coverage ---")
    for genre, count in sorted(all_genres.items(), key=lambda x: -x[1])[:20]:
        logger.info(f"  {genre}: {count} tracks")

    # Score distribution
    logger.info("\n--- Score Distribution ---")
    for score_name in ["semantic", "trajectory", "genre_match", "total"]:
        values = [td["scores"][score_name] for td in tracks_data]
        if values:
            logger.info(
                f"  {score_name:15s}: min={min(values):.3f} avg={sum(values)/len(values):.3f} "
                f"max={max(values):.3f}"
            )

    return {
        "prompt": prompt,
        "intent": intent_data,
        "raw_semantic_top30": raw_results[:30],
        "composer_tracks": tracks_data,
        "metrics": result.metrics,
        "genre_coverage": all_genres,
        "generation_time_s": elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description="Playlist quality diagnostic")
    parser.add_argument("--prompts", nargs="+", default=["pure evil 80s thrash", "coldwave"],
                        help="Prompts to diagnose")
    parser.add_argument("--size", type=int, default=25, help="Playlist size")
    parser.add_argument("--output", type=str, default=None,
                        help="Output JSON file (default: auto-generated)")
    args = parser.parse_args()

    all_results = []
    for prompt in args.prompts:
        result = diagnose_prompt(prompt, args.size)
        all_results.append(result)

    # Write full results to JSON log
    output_path = args.output or f"diagnose_{int(time.time())}.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    logger.info(f"\n{'='*80}")
    logger.info(f"Full results written to: {output_path}")
    logger.info(f"{'='*80}")

    return all_results


if __name__ == "__main__":
    main()
