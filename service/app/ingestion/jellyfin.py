import httpx
from datetime import datetime
from typing import Callable

from app.config import settings
from app.database import get_connection


def get_last_sync_time() -> datetime | None:
    """Get the last successful sync time from the database."""
    conn = get_connection()
    try:
        # Ensure table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                key VARCHAR PRIMARY KEY,
                value VARCHAR,
                updated_at TIMESTAMP DEFAULT now()
            )
        """)
        result = conn.execute(
            "SELECT value FROM sync_metadata WHERE key = 'last_jellyfin_sync'"
        ).fetchone()
        if result and result[0]:
            return datetime.fromisoformat(result[0])
        return None
    finally:
        conn.close()


def set_last_sync_time(sync_time: datetime) -> None:
    """Set the last successful sync time in the database."""
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO sync_metadata (key, value, updated_at)
            VALUES ('last_jellyfin_sync', ?, now())
            ON CONFLICT (key) DO UPDATE SET value = ?, updated_at = now()
        """, [sync_time.isoformat(), sync_time.isoformat()])
    finally:
        conn.close()


async def sync_jellyfin_library(
    progress_callback: Callable[[int, int, str], None] | None = None,
    full_sync: bool = False
) -> dict:
    """Sync the Jellyfin music library to the local database.
    
    Args:
        progress_callback: Optional callback for progress updates
        full_sync: If True, sync all tracks. If False, only sync new tracks since last sync.
    
    This will:
    - Add new tracks/artists/albums
    - Update existing tracks (on full sync)
    - Remove tracks that no longer exist in Jellyfin (on full sync)
    """
    
    stats = {
        "tracks_added": 0,
        "tracks_updated": 0,
        "tracks_removed": 0,
        "artists_added": 0,
        "albums_added": 0,
        "incremental": not full_sync,
    }
    
    # Track all IDs we see from Jellyfin to detect deletions (only for full sync)
    seen_track_ids: set[str] = set()
    
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        raise ValueError("Jellyfin URL and API key must be configured")
    
    headers = {
        "X-Emby-Token": settings.jellyfin_api_key,
    }
    
    # Get last sync time for incremental sync
    last_sync = None if full_sync else get_last_sync_time()
    sync_start_time = datetime.now()
    
    if last_sync and not full_sync:
        if progress_callback:
            progress_callback(0, 0, f"Incremental sync since {last_sync.strftime('%Y-%m-%d %H:%M')}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Build query params
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "Fields": "Path,Genres,Studios,Tags,MediaSources,ParentId,DateCreated",
            "Limit": 500,
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
        }
        
        # For incremental sync, we'll fetch newest first and stop when we hit already-synced tracks
        # For full sync, we fetch everything
        start_index = 0
        page_size = 500
        
        while True:
            params["StartIndex"] = start_index
            params["Limit"] = page_size
            
            response = await client.get(
                f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            
            items = data.get("Items", [])
            if not items:
                break
            
            conn = get_connection()
            
            stop_incremental = False
            
            for item in items:
                track_id = item.get("Id")
                artist_id = item.get("AlbumArtists", [{}])[0].get("Id") if item.get("AlbumArtists") else None
                album_id = item.get("AlbumId")
                
                # For incremental sync, check if we've reached already-synced tracks
                if last_sync and not full_sync:
                    date_created_str = item.get("DateCreated")
                    if date_created_str:
                        # Parse Jellyfin date format (e.g., "2024-01-15T10:30:00.0000000Z")
                        date_created = datetime.fromisoformat(date_created_str.replace("Z", "+00:00").split(".")[0])
                        if date_created.replace(tzinfo=None) <= last_sync:
                            # This track was created before last sync, we can stop
                            stop_incremental = True
                            break
                
                # Track seen IDs for full sync deletion detection
                if full_sync:
                    seen_track_ids.add(track_id)
                
                # Upsert track
                existing = conn.execute(
                    "SELECT id FROM tracks WHERE id = ?", [track_id]
                ).fetchone()
                
                if existing:
                    conn.execute("""
                        UPDATE tracks SET
                            title = ?,
                            artist_id = ?,
                            artist_name = ?,
                            album_id = ?,
                            album_name = ?,
                            year = ?,
                            duration_ms = ?,
                            track_number = ?,
                            disc_number = ?,
                            path = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, [
                        item.get("Name"),
                        artist_id,
                        item.get("AlbumArtist") or item.get("Artists", [""])[0] if item.get("Artists") else None,
                        album_id,
                        item.get("Album"),
                        item.get("ProductionYear"),
                        int(item.get("RunTimeTicks", 0) / 10000) if item.get("RunTimeTicks") else None,
                        item.get("IndexNumber"),
                        item.get("ParentIndexNumber"),
                        item.get("Path"),
                        datetime.now(),
                        track_id,
                    ])
                    stats["tracks_updated"] += 1
                else:
                    conn.execute("""
                        INSERT INTO tracks (
                            id, title, artist_id, artist_name, album_id, album_name,
                            year, duration_ms, track_number, disc_number, path
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        track_id,
                        item.get("Name"),
                        artist_id,
                        item.get("AlbumArtist") or item.get("Artists", [""])[0] if item.get("Artists") else None,
                        album_id,
                        item.get("Album"),
                        item.get("ProductionYear"),
                        int(item.get("RunTimeTicks", 0) / 10000) if item.get("RunTimeTicks") else None,
                        item.get("IndexNumber"),
                        item.get("ParentIndexNumber"),
                        item.get("Path"),
                    ])
                    stats["tracks_added"] += 1
                
                # Upsert artist if we have an ID
                if artist_id:
                    artist_name = item.get("AlbumArtist") or (item.get("Artists", [""])[0] if item.get("Artists") else None)
                    existing_artist = conn.execute(
                        "SELECT id FROM artists WHERE id = ?", [artist_id]
                    ).fetchone()
                    
                    if not existing_artist and artist_name:
                        conn.execute("""
                            INSERT INTO artists (id, name) VALUES (?, ?)
                        """, [artist_id, artist_name])
                        stats["artists_added"] += 1
                
                # Upsert album if we have an ID
                if album_id:
                    existing_album = conn.execute(
                        "SELECT id FROM albums WHERE id = ?", [album_id]
                    ).fetchone()
                    
                    if not existing_album:
                        conn.execute("""
                            INSERT INTO albums (id, name, artist_id, artist_name, year)
                            VALUES (?, ?, ?, ?, ?)
                        """, [
                            album_id,
                            item.get("Album"),
                            artist_id,
                            item.get("AlbumArtist"),
                            item.get("ProductionYear"),
                        ])
                        stats["albums_added"] += 1
                
                # Handle genres
                genres = item.get("Genres", [])
                for genre_name in genres:
                    if not genre_name:
                        continue
                    
                    # Get or create genre
                    genre_row = conn.execute(
                        "SELECT id FROM genres WHERE name = ?", [genre_name]
                    ).fetchone()
                    
                    if genre_row:
                        genre_id = genre_row[0]
                    else:
                        result = conn.execute(
                            "SELECT COALESCE(MAX(id), 0) + 1 FROM genres"
                        ).fetchone()
                        genre_id = result[0]
                        conn.execute("""
                            INSERT INTO genres (id, name, normalized_name)
                            VALUES (?, ?, ?)
                        """, [genre_id, genre_name, genre_name.lower()])
                    
                    # Link track to genre
                    conn.execute("""
                        INSERT OR IGNORE INTO track_genres (track_id, genre_id)
                        VALUES (?, ?)
                    """, [track_id, genre_id])
            
            conn.close()
            
            # For incremental sync, stop if we hit already-synced tracks
            if stop_incremental:
                if progress_callback:
                    progress_callback(stats["tracks_added"], stats["tracks_added"], 
                                    f"Incremental sync complete: {stats['tracks_added']} new tracks")
                break
            
            # Check if we've fetched all items
            total_count = data.get("TotalRecordCount", 0)
            start_index += len(items)
            
            if progress_callback:
                if full_sync or not last_sync:
                    progress_callback(start_index, total_count, f"Processed {start_index}/{total_count} tracks")
                else:
                    progress_callback(stats["tracks_added"], 0, f"Found {stats['tracks_added']} new tracks...")
            
            if start_index >= total_count:
                break
    
    # Save sync time on success
    set_last_sync_time(sync_start_time)
    
    # Remove tracks that no longer exist in Jellyfin (only for full sync)
    if full_sync and seen_track_ids:
        conn = get_connection()
        
        # Get all track IDs currently in database
        existing_ids = conn.execute("SELECT id FROM tracks").fetchall()
        existing_ids = {row[0] for row in existing_ids}
        
        # Find orphaned tracks (in DB but not in Jellyfin)
        orphaned_ids = existing_ids - seen_track_ids
        
        if orphaned_ids:
            # Delete related data first (embeddings, tags, etc.)
            placeholders = ",".join(["?" for _ in orphaned_ids])
            orphaned_list = list(orphaned_ids)
            
            conn.execute(f"DELETE FROM track_embeddings WHERE track_id IN ({placeholders})", orphaned_list)
            conn.execute(f"DELETE FROM track_lastfm_tags WHERE track_id IN ({placeholders})", orphaned_list)
            conn.execute(f"DELETE FROM track_genres WHERE track_id IN ({placeholders})", orphaned_list)
            conn.execute(f"DELETE FROM tracks WHERE id IN ({placeholders})", orphaned_list)
            
            stats["tracks_removed"] = len(orphaned_ids)
        
        conn.close()
    
    return stats


async def create_jellyfin_playlist(name: str, track_ids: list[str]) -> str | None:
    """Create a playlist in Jellyfin with the given tracks."""
    
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        return None
    
    headers = {
        "X-Emby-Token": settings.jellyfin_api_key,
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create playlist
        response = await client.post(
            f"{settings.jellyfin_url}/Playlists",
            headers=headers,
            json={
                "Name": name,
                "Ids": track_ids,
                "UserId": settings.jellyfin_user_id,
                "MediaType": "Audio",
            }
        )
        response.raise_for_status()
        data = response.json()
        
        return data.get("Id")
