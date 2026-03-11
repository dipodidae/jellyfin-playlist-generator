"""M3U playlist exporter with multiple path mapping modes."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

from app.config import settings
from app.database_pg import get_cursor, get_connection

logger = logging.getLogger(__name__)

ExportMode = Literal["absolute", "relative", "mapped"]


def get_path_mappings() -> list[dict]:
    """Get all path mappings sorted by prefix length (longest first)."""
    with get_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, name, source_prefix, target_prefix, priority
            FROM path_mappings
            ORDER BY length(source_prefix) DESC, priority DESC
        """)
        return [dict(row) for row in cur.fetchall()]


def apply_path_mapping(path: str, mappings: list[dict]) -> str:
    """Apply path mapping using longest prefix match."""
    for mapping in mappings:
        source = mapping["source_prefix"]
        target = mapping["target_prefix"]
        if path.startswith(source):
            return path.replace(source, target, 1)
    return path


def get_playlist_tracks(playlist_id: str) -> list[dict]:
    """Get tracks for a playlist with file paths."""
    with get_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT 
                t.id as track_id,
                t.title,
                t.duration_ms,
                tf.path,
                a.name as artist_name,
                pt.position
            FROM playlist_tracks pt
            JOIN tracks t ON pt.track_id = t.id
            JOIN track_files tf ON tf.track_id = t.id AND tf.missing_since IS NULL
            LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
            LEFT JOIN artists a ON ta.artist_id = a.id
            WHERE pt.playlist_id = %s
            ORDER BY pt.position
        """, (playlist_id,))
        return [dict(row) for row in cur.fetchall()]


def get_track_files(track_ids: list[str]) -> list[dict]:
    """Get track info with file paths for a list of track IDs."""
    if not track_ids:
        return []
    
    with get_cursor(dict_cursor=True) as cur:
        # Preserve order using array position
        cur.execute("""
            WITH track_order AS (
                SELECT unnest(%s::uuid[]) as id, generate_series(1, %s) as pos
            )
            SELECT 
                t.id as track_id,
                t.title,
                t.duration_ms,
                tf.path,
                a.name as artist_name,
                o.pos as position
            FROM track_order o
            JOIN tracks t ON t.id = o.id
            JOIN track_files tf ON tf.track_id = t.id AND tf.missing_since IS NULL
            LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
            LEFT JOIN artists a ON ta.artist_id = a.id
            ORDER BY o.pos
        """, (track_ids, len(track_ids)))
        return [dict(row) for row in cur.fetchall()]


def format_duration(duration_ms: int) -> int:
    """Convert milliseconds to seconds for M3U."""
    return duration_ms // 1000 if duration_ms else -1


def generate_m3u(
    tracks: list[dict],
    mode: ExportMode = "absolute",
    mapping_name: str | None = None,
    output_path: Path | None = None,
) -> str:
    """Generate M3U playlist content.
    
    Args:
        tracks: List of track dicts with path, title, artist_name, duration_ms
        mode: Export mode - "absolute", "relative", or "mapped"
        mapping_name: Name of path mapping to use (for "mapped" mode)
        output_path: Output file path (required for "relative" mode)
    
    Returns:
        M3U playlist content as string
    """
    lines = ["#EXTM3U"]
    
    # Get mappings if needed
    mappings = []
    if mode == "mapped":
        all_mappings = get_path_mappings()
        if mapping_name:
            mappings = [m for m in all_mappings if m["name"] == mapping_name]
            if not mappings:
                logger.warning(f"Path mapping '{mapping_name}' not found, using all mappings")
                mappings = all_mappings
        else:
            mappings = all_mappings
    
    for track in tracks:
        path = track.get("path")
        if not path:
            logger.warning(f"Track {track.get('track_id')} has no file path, skipping")
            continue
        
        # Apply path transformation based on mode
        if mode == "relative" and output_path:
            try:
                output_dir = output_path.parent
                path = os.path.relpath(path, output_dir)
            except ValueError:
                # Can't make relative (different drives on Windows)
                pass
        elif mode == "mapped":
            path = apply_path_mapping(path, mappings)
        # "absolute" mode: use path as-is
        
        # Format track info
        duration = format_duration(track.get("duration_ms", 0))
        artist = track.get("artist_name") or "Unknown Artist"
        title = track.get("title") or "Unknown Title"
        
        # Extended M3U format
        lines.append(f"#EXTINF:{duration},{artist} - {title}")
        lines.append(path)
    
    return "\n".join(lines) + "\n"


def export_playlist_to_file(
    playlist_id: str,
    output_path: Path | str,
    mode: ExportMode = "absolute",
    mapping_name: str | None = None,
) -> Path:
    """Export a saved playlist to an M3U file.
    
    Args:
        playlist_id: UUID of the playlist
        output_path: Where to write the M3U file
        mode: Export mode
        mapping_name: Path mapping name for "mapped" mode
    
    Returns:
        Path to the created file
    """
    output_path = Path(output_path)
    
    # Get playlist tracks
    tracks = get_playlist_tracks(playlist_id)
    if not tracks:
        raise ValueError(f"Playlist {playlist_id} has no tracks")
    
    # Generate M3U content
    content = generate_m3u(
        tracks=tracks,
        mode=mode,
        mapping_name=mapping_name,
        output_path=output_path,
    )
    
    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    
    logger.info(f"Exported playlist to {output_path} ({len(tracks)} tracks, mode={mode})")
    return output_path


def export_tracks_to_file(
    track_ids: list[str],
    output_path: Path | str,
    mode: ExportMode = "absolute",
    mapping_name: str | None = None,
    playlist_name: str | None = None,
) -> Path:
    """Export a list of track IDs to an M3U file.
    
    Args:
        track_ids: List of track UUIDs in order
        output_path: Where to write the M3U file
        mode: Export mode
        mapping_name: Path mapping name for "mapped" mode
        playlist_name: Optional name for the playlist (used in filename if output_path is a directory)
    
    Returns:
        Path to the created file
    """
    output_path = Path(output_path)
    
    # If output_path is a directory, generate filename
    if output_path.is_dir():
        name = playlist_name or f"playlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        # Sanitize filename
        name = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        output_path = output_path / f"{name}.m3u"
    
    # Get track info
    tracks = get_track_files(track_ids)
    if not tracks:
        raise ValueError("No valid tracks found")
    
    # Generate M3U content
    content = generate_m3u(
        tracks=tracks,
        mode=mode,
        mapping_name=mapping_name,
        output_path=output_path,
    )
    
    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    
    logger.info(f"Exported {len(tracks)} tracks to {output_path} (mode={mode})")
    return output_path


def create_path_mapping(name: str, source_prefix: str, target_prefix: str, priority: int = 0) -> str:
    """Create or update a path mapping.
    
    Returns:
        UUID of the mapping
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO path_mappings (name, source_prefix, target_prefix, priority)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    source_prefix = EXCLUDED.source_prefix,
                    target_prefix = EXCLUDED.target_prefix,
                    priority = EXCLUDED.priority
                RETURNING id
            """, (name, source_prefix, target_prefix, priority))
            return str(cur.fetchone()[0])


def delete_path_mapping(name: str) -> bool:
    """Delete a path mapping by name.
    
    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM path_mappings WHERE name = %s", (name,))
            return cur.rowcount > 0
