"""File-based music library scanner with parallel processing and incremental updates."""

import hashlib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus

from app.config import settings
from app.database_pg import get_cursor, get_connection

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {'.flac', '.mp3', '.ogg', '.m4a', '.opus', '.wav', '.aiff', '.aif'}
IGNORE_EXTENSIONS = {'.cue', '.log', '.jpg', '.jpeg', '.png', '.txt', '.nfo', '.m3u', '.m3u8', '.pdf'}


def compute_file_hash(size: int, mtime: float) -> str:
    """Fast change detection for files."""
    return hashlib.sha1(f"{size}|{mtime}".encode()).hexdigest()


def compute_track_fingerprint(artist: str, title: str, duration_ms: int) -> str:
    """Fuzzy track identity that survives format/encode changes."""
    norm_artist = (artist or "").lower().strip()
    norm_title = (title or "").lower().strip()
    duration_bucket = duration_ms // 2000  # 2-second buckets
    data = f"{norm_artist}|{norm_title}|{duration_bucket}"
    return hashlib.sha1(data.encode()).hexdigest()


def compute_metadata_hash(title: str, artists: list[str], album: str, genres: list[str], tags: list[str], year: int | None) -> str:
    """Full semantic hash for embedding staleness detection."""
    data = f"{title}|{'|'.join(sorted(artists))}|{album}|{'|'.join(sorted(genres))}|{'|'.join(sorted(tags))}|{year or ''}"
    return hashlib.sha1(data.encode()).hexdigest()


def parse_folder_metadata(file_path: Path) -> dict[str, str | None]:
    """Extract metadata from folder structure.

    Supports common patterns:
    - Artist/Album/Track.ext
    - Artist - Title.ext
    - Year - Album/Track.ext
    """
    parts = file_path.parts
    result = {"artist": None, "album": None, "title": None}

    # Try Artist/Album/Track pattern
    if len(parts) >= 3:
        potential_artist = parts[-3]
        potential_album = parts[-2]

        # Skip if looks like a year folder
        if not re.match(r'^\d{4}$', potential_artist):
            result["artist"] = potential_artist

        # Album might be "Year - Album" format
        album_match = re.match(r'^(\d{4})\s*[-–]\s*(.+)$', potential_album)
        if album_match:
            result["album"] = album_match.group(2)
        else:
            result["album"] = potential_album

    # Try to extract title from filename
    stem = file_path.stem

    # Pattern: "01 - Title" or "01. Title"
    track_match = re.match(r'^(\d+)[\s.\-–]+(.+)$', stem)
    if track_match:
        result["title"] = track_match.group(2).strip()
    else:
        # Pattern: "Artist - Title"
        artist_title_match = re.match(r'^(.+?)\s*[-–]\s*(.+)$', stem)
        if artist_title_match and not result["artist"]:
            result["artist"] = artist_title_match.group(1).strip()
            result["title"] = artist_title_match.group(2).strip()
        else:
            result["title"] = stem

    return result


def extract_tags(file_path: Path) -> dict[str, Any] | None:
    """Extract metadata from audio file tags with folder fallback."""
    try:
        audio = mutagen.File(str(file_path), easy=True)
        if audio is None:
            logger.warning(f"Could not read tags from {file_path}")
            return None

        # Get duration
        if hasattr(audio, 'info') and hasattr(audio.info, 'length'):
            duration_ms = int(audio.info.length * 1000)
        else:
            duration_ms = 0

        # Extract tags with fallback
        def get_tag(keys: list[str], default: str | None = None) -> str | None:
            for key in keys:
                if key in audio and audio[key]:
                    val = audio[key]
                    if isinstance(val, list):
                        return val[0] if val else default
                    return str(val)
            return default

        folder_meta = parse_folder_metadata(file_path)

        # Artist fallback hierarchy
        artist = (
            get_tag(['artist']) or
            get_tag(['albumartist']) or
            get_tag(['performer']) or
            folder_meta.get("artist") or
            "Unknown Artist"
        )

        # Album artist (may differ from track artist)
        album_artist = (
            get_tag(['albumartist']) or
            get_tag(['artist']) or
            folder_meta.get("artist")
        )

        # Title
        title = (
            get_tag(['title']) or
            folder_meta.get("title") or
            file_path.stem
        )

        # Album
        album = (
            get_tag(['album']) or
            folder_meta.get("album") or
            "Unknown Album"
        )

        # Year
        year_str = get_tag(['date', 'year', 'originaldate'])
        year = None
        if year_str:
            # Handle various date formats
            year_match = re.match(r'^(\d{4})', year_str)
            if year_match:
                year = int(year_match.group(1))

        # Track/disc numbers
        track_num = None
        track_str = get_tag(['tracknumber'])
        if track_str:
            track_match = re.match(r'^(\d+)', track_str)
            if track_match:
                track_num = int(track_match.group(1))

        disc_num = 1
        disc_str = get_tag(['discnumber'])
        if disc_str:
            disc_match = re.match(r'^(\d+)', disc_str)
            if disc_match:
                disc_num = int(disc_match.group(1))

        # Genres
        genres = []
        genre_val = get_tag(['genre'])
        if genre_val:
            # Split on common separators
            for g in re.split(r'[;,/]', genre_val):
                g = g.strip()
                if g:
                    genres.append(g)

        # Featured artists (parse from title or artist field)
        featured_artists = []
        feat_patterns = [
            r'\s*[\(\[](feat\.?|ft\.?|featuring)\s+([^\)\]]+)[\)\]]',
            r'\s*(feat\.?|ft\.?|featuring)\s+(.+)$',
        ]
        for pattern in feat_patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                feat_str = match.group(2)
                for fa in re.split(r'[,&]', feat_str):
                    fa = fa.strip()
                    if fa:
                        featured_artists.append(fa)
                # Clean title
                title = re.sub(pattern, '', title, flags=re.IGNORECASE).strip()
                break

        return {
            "title": title,
            "artist": artist,
            "album_artist": album_artist,
            "album": album,
            "year": year,
            "duration_ms": duration_ms,
            "track_number": track_num,
            "disc_number": disc_num,
            "genres": genres,
            "featured_artists": featured_artists,
            "format": file_path.suffix.lower().lstrip('.'),
        }

    except Exception as e:
        logger.error(f"Error extracting tags from {file_path}: {e}")
        return None


def scan_file(file_path: Path) -> dict[str, Any] | None:
    """Scan a single audio file and return metadata."""
    try:
        stat = file_path.stat()
        size = stat.st_size
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        inode = stat.st_ino if hasattr(stat, 'st_ino') else None

        file_hash = compute_file_hash(size, stat.st_mtime)

        tags = extract_tags(file_path)
        if tags is None:
            return None

        fingerprint = compute_track_fingerprint(
            tags["artist"],
            tags["title"],
            tags["duration_ms"]
        )

        return {
            "path": str(file_path),
            "file_hash": file_hash,
            "size": size,
            "mtime": mtime,
            "inode": inode,
            "fingerprint": fingerprint,
            **tags,
        }
    except Exception as e:
        logger.error(f"Error scanning file {file_path}: {e}")
        return None


def get_or_create_artist(cur, name: str) -> str:
    """Get or create an artist, return UUID."""
    cur.execute("SELECT id FROM artists WHERE name = %s", (name,))
    result = cur.fetchone()
    if result:
        return result[0]

    cur.execute(
        "INSERT INTO artists (name, sort_name) VALUES (%s, %s) RETURNING id",
        (name, name)  # TODO: compute proper sort_name
    )
    return cur.fetchone()[0]


def get_or_create_album(cur, title: str, year: int | None) -> str:
    """Get or create an album, return UUID."""
    cur.execute(
        "SELECT id FROM albums WHERE title = %s AND year IS NOT DISTINCT FROM %s",
        (title, year)
    )
    result = cur.fetchone()
    if result:
        return result[0]

    cur.execute(
        "INSERT INTO albums (title, year) VALUES (%s, %s) RETURNING id",
        (title, year)
    )
    return cur.fetchone()[0]


def get_or_create_genre(cur, name: str) -> str:
    """Get or create a genre, return UUID."""
    cur.execute("SELECT id FROM genres WHERE name = %s", (name,))
    result = cur.fetchone()
    if result:
        return result[0]

    cur.execute("INSERT INTO genres (name) VALUES (%s) RETURNING id", (name,))
    return cur.fetchone()[0]


def upsert_track(cur, metadata: dict[str, Any]) -> str:
    """Upsert a track by fingerprint, return track UUID."""
    fingerprint = metadata["fingerprint"]

    # Check if track exists
    cur.execute("SELECT id FROM tracks WHERE fingerprint = %s", (fingerprint,))
    result = cur.fetchone()

    if result:
        track_id = result[0]
        # Update track metadata
        cur.execute("""
            UPDATE tracks SET
                title = %s,
                duration_ms = %s,
                year = %s,
                updated_at = now()
            WHERE id = %s
        """, (metadata["title"], metadata["duration_ms"], metadata.get("year"), track_id))
    else:
        # Insert new track
        cur.execute("""
            INSERT INTO tracks (fingerprint, title, duration_ms, year)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (fingerprint, metadata["title"], metadata["duration_ms"], metadata.get("year")))
        track_id = cur.fetchone()[0]

    return str(track_id)


def upsert_track_file(cur, track_id: str, metadata: dict[str, Any]) -> str:
    """Upsert a track file, return file UUID."""
    path = metadata["path"]

    cur.execute("SELECT id FROM track_files WHERE path = %s", (path,))
    result = cur.fetchone()

    if result:
        file_id = result[0]
        cur.execute("""
            UPDATE track_files SET
                track_id = %s,
                file_hash = %s,
                size = %s,
                mtime = %s,
                inode = %s,
                format = %s,
                last_scanned = now(),
                missing_since = NULL
            WHERE id = %s
        """, (track_id, metadata["file_hash"], metadata["size"], metadata["mtime"],
              metadata.get("inode"), metadata["format"], file_id))
    else:
        cur.execute("""
            INSERT INTO track_files (track_id, path, file_hash, size, mtime, inode, format)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (track_id, path, metadata["file_hash"], metadata["size"], metadata["mtime"],
              metadata.get("inode"), metadata["format"]))
        file_id = cur.fetchone()[0]

    return str(file_id)


def link_track_artists(cur, track_id: str, metadata: dict[str, Any]) -> None:
    """Link track to artists."""
    # Clear existing links
    cur.execute("DELETE FROM track_artists WHERE track_id = %s", (track_id,))

    # Primary artist
    artist_id = get_or_create_artist(cur, metadata["artist"])
    cur.execute("""
        INSERT INTO track_artists (track_id, artist_id, role, position)
        VALUES (%s, %s, 'primary', 0)
        ON CONFLICT DO NOTHING
    """, (track_id, artist_id))

    # Featured artists
    for i, feat_artist in enumerate(metadata.get("featured_artists", [])):
        feat_id = get_or_create_artist(cur, feat_artist)
        cur.execute("""
            INSERT INTO track_artists (track_id, artist_id, role, position)
            VALUES (%s, %s, 'featured', %s)
            ON CONFLICT DO NOTHING
        """, (track_id, feat_id, i + 1))


def link_track_album(cur, track_id: str, metadata: dict[str, Any]) -> None:
    """Link track to album."""
    album_id = get_or_create_album(cur, metadata["album"], metadata.get("year"))

    # Link album to album artist
    if metadata.get("album_artist"):
        album_artist_id = get_or_create_artist(cur, metadata["album_artist"])
        cur.execute("""
            INSERT INTO album_artists (album_id, artist_id, position)
            VALUES (%s, %s, 0)
            ON CONFLICT DO NOTHING
        """, (album_id, album_artist_id))

    # Link track to album
    cur.execute("""
        INSERT INTO track_albums (track_id, album_id, disc_number, track_number)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (track_id, album_id) DO UPDATE SET
            disc_number = EXCLUDED.disc_number,
            track_number = EXCLUDED.track_number
    """, (track_id, album_id, metadata.get("disc_number", 1), metadata.get("track_number")))


def link_track_genres(cur, track_id: str, genres: list[str]) -> None:
    """Link track to genres."""
    cur.execute("DELETE FROM track_genres WHERE track_id = %s", (track_id,))

    for genre in genres:
        genre_id = get_or_create_genre(cur, genre)
        cur.execute("""
            INSERT INTO track_genres (track_id, genre_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (track_id, genre_id))


def list_audio_files(directory: Path) -> list[Path]:
    """Recursively list all audio files in a directory."""
    files = []
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext in AUDIO_EXTENSIONS:
                files.append(Path(root) / filename)
    return files


def get_existing_file_hashes(cur) -> dict[str, tuple[str, str]]:
    """Get existing file paths and their hashes."""
    cur.execute("SELECT path, file_hash, track_id FROM track_files WHERE missing_since IS NULL")
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


async def scan_library(
    progress_callback: callable = None,
    full_scan: bool = False
) -> dict[str, int]:
    """Scan music library for new/changed files.

    Args:
        progress_callback: Optional callback(current, total, message)
        full_scan: If True, rescan all files regardless of hash

    Returns:
        Stats dict with counts of processed/added/updated files
    """
    stats = {
        "files_found": 0,
        "files_scanned": 0,
        "files_skipped": 0,
        "tracks_added": 0,
        "tracks_updated": 0,
        "files_missing": 0,
        "errors": 0,
    }

    def report_progress(stage: str, current: int, total: int, message: str) -> None:
        if not progress_callback:
            return

        payload = {
            "stage": stage,
            "current": current,
            "total": total,
            "message": message,
            "stats": dict(stats),
        }

        try:
            progress_callback(payload)
        except TypeError:
            progress_callback(current, total, message)

    music_dirs = settings.music_dirs
    if not music_dirs:
        logger.warning("No music directories configured")
        report_progress("error", 0, 0, "No music directories configured")
        return stats

    report_progress("discovering", 0, 0, "Discovering audio files...")

    # Collect all audio files
    all_files: list[Path] = []
    for dir_path in music_dirs:
        dir_path = Path(dir_path)
        if dir_path.exists():
            files = list_audio_files(dir_path)
            all_files.extend(files)
            logger.info(f"Found {len(files)} audio files in {dir_path}")
        else:
            logger.warning(f"Music directory does not exist: {dir_path}")

    stats["files_found"] = len(all_files)

    if not all_files:
        logger.info("No audio files found")
        report_progress("complete", 0, 0, "No audio files found")
        return stats

    # Get existing file hashes for incremental scanning
    with get_connection() as conn:
        with conn.cursor() as cur:
            existing_hashes = get_existing_file_hashes(cur)

    # Determine which files need scanning
    files_to_scan: list[Path] = []
    for file_path in all_files:
        path_str = str(file_path)
        if full_scan:
            files_to_scan.append(file_path)
        elif path_str not in existing_hashes:
            files_to_scan.append(file_path)
        else:
            # Check if file changed
            try:
                stat = file_path.stat()
                current_hash = compute_file_hash(stat.st_size, stat.st_mtime)
                if current_hash != existing_hashes[path_str][0]:
                    files_to_scan.append(file_path)
                else:
                    stats["files_skipped"] += 1
            except OSError:
                files_to_scan.append(file_path)

    logger.info(f"Scanning {len(files_to_scan)} files ({stats['files_skipped']} unchanged)")

    report_progress("scanning_files", 0, len(files_to_scan), f"Scanning {len(files_to_scan)} files...")

    # Parallel file scanning
    scanned_metadata: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=settings.scan_threads) as executor:
        futures = {executor.submit(scan_file, f): f for f in files_to_scan}

        for i, future in enumerate(as_completed(futures)):
            file_path = futures[future]
            try:
                metadata = future.result()
                if metadata:
                    scanned_metadata.append(metadata)
                    stats["files_scanned"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                logger.error(f"Error scanning {file_path}: {e}")
                stats["errors"] += 1

            if (i + 1) % 25 == 0 or i + 1 == len(files_to_scan):
                report_progress(
                    "scanning_files",
                    i + 1,
                    len(files_to_scan),
                    f"Scanned {i + 1}/{len(files_to_scan)} files",
                )

    report_progress(len(scanned_metadata) and "saving_tracks" or "complete", 0, len(scanned_metadata), "Saving to database...")

    # Batch insert into database
    scanned_paths = set()
    with get_connection() as conn:
        with conn.cursor() as cur:
            for i, metadata in enumerate(scanned_metadata):
                try:
                    # Check if track exists (by fingerprint)
                    cur.execute("SELECT id FROM tracks WHERE fingerprint = %s", (metadata["fingerprint"],))
                    existing = cur.fetchone()

                    track_id = upsert_track(cur, metadata)
                    upsert_track_file(cur, track_id, metadata)
                    link_track_artists(cur, track_id, metadata)
                    link_track_album(cur, track_id, metadata)
                    link_track_genres(cur, track_id, metadata.get("genres", []))

                    scanned_paths.add(metadata["path"])

                    if existing:
                        stats["tracks_updated"] += 1
                    else:
                        stats["tracks_added"] += 1

                    # Commit every 100 tracks
                    if (i + 1) % 25 == 0 or i + 1 == len(scanned_metadata):
                        conn.commit()
                        report_progress(
                            "saving_tracks",
                            i + 1,
                            len(scanned_metadata),
                            f"Saved {i + 1}/{len(scanned_metadata)} tracks",
                        )

                except Exception as e:
                    logger.error(f"Error saving track {metadata.get('path')}: {e}")
                    stats["errors"] += 1

            # Mark missing files
            all_scanned_paths = set(str(f) for f in all_files)
            for path in existing_hashes:
                if path not in all_scanned_paths:
                    cur.execute("""
                        UPDATE track_files SET missing_since = now()
                        WHERE path = %s AND missing_since IS NULL
                    """, (path,))
                    stats["files_missing"] += 1

    logger.info(f"Scan complete: {stats}")
    report_progress(len(scanned_metadata) and "complete" or "complete", len(scanned_metadata), len(scanned_metadata), "Scan complete")
    return stats
