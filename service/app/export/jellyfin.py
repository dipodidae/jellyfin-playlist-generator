"""Jellyfin playlist export — resolve local tracks to Jellyfin IDs and create playlists."""

import logging
from urllib.parse import quote

import httpx

from app.config import settings
from app.export.m3u import get_track_files

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """Check whether Jellyfin connection details are present."""
    return bool(settings.jellyfin_url and settings.jellyfin_api_key and settings.jellyfin_user_id)


def _headers() -> dict[str, str]:
    return {
        "X-Emby-Token": settings.jellyfin_api_key,
    }


def _convert_path(local_path: str) -> str:
    """Convert a local file path to the equivalent Jellyfin-side path.

    E.g. /mnt/drive-next/Music/Artist/song.flac
      -> /data/movies/Music/Artist/song.flac
    """
    src = settings.local_path_prefix
    dst = settings.jellyfin_path_prefix
    if src and dst and local_path.startswith(src):
        return dst + local_path[len(src):]
    return local_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def test_connection() -> dict:
    """Test whether Jellyfin is reachable and credentials are valid.

    Returns dict with keys: available, configured, server_name, version, error.
    """
    if not _is_configured():
        return {"available": False, "configured": False, "server_name": None, "version": None, "error": "Jellyfin not configured"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.jellyfin_url}/System/Info/Public",
                headers=_headers(),
            )
            resp.raise_for_status()
            info = resp.json()
            return {
                "available": True,
                "configured": True,
                "server_name": info.get("ServerName"),
                "version": info.get("Version"),
                "error": None,
            }
    except Exception as exc:
        logger.warning("Jellyfin connection test failed: %s", exc)
        return {
            "available": False,
            "configured": True,
            "server_name": None,
            "version": None,
            "error": str(exc),
        }


async def resolve_jellyfin_ids(tracks: list[dict]) -> tuple[list[str], list[dict]]:
    """Resolve local track dicts (from get_track_files) to Jellyfin Item IDs.

    For each track we:
      1. Convert the local file path to a Jellyfin path.
      2. Search Jellyfin by track title to get a small candidate set.
      3. Match the candidate whose Path equals the converted path.

    Returns:
        (matched_jellyfin_ids_in_order, list_of_unmatched_track_dicts)
    """
    matched_ids: list[str] = []
    unmatched: list[dict] = []

    async with httpx.AsyncClient(timeout=15.0) as client:
        for track in tracks:
            local_path = track.get("path")
            if not local_path:
                unmatched.append(track)
                continue

            jellyfin_path = _convert_path(local_path)
            title = track.get("title") or ""

            # Search Jellyfin by title — returns a small set we can path-match against
            try:
                resp = await client.get(
                    f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items",
                    headers=_headers(),
                    params={
                        "IncludeItemTypes": "Audio",
                        "Recursive": "true",
                        "Fields": "Path",
                        "SearchTerm": title,
                        "Limit": 50,
                    },
                )
                resp.raise_for_status()
                items = resp.json().get("Items", [])
            except Exception as exc:
                logger.warning("Jellyfin search failed for '%s': %s", title, exc)
                unmatched.append(track)
                continue

            # Find exact path match
            found = False
            for item in items:
                if item.get("Path") == jellyfin_path:
                    matched_ids.append(item["Id"])
                    found = True
                    break

            if not found:
                # Fallback: try a broader filename-based match
                # The filename portion should be unique enough
                filename = jellyfin_path.rsplit("/", 1)[-1] if "/" in jellyfin_path else jellyfin_path
                for item in items:
                    item_path = item.get("Path") or ""
                    if item_path.endswith("/" + filename):
                        matched_ids.append(item["Id"])
                        found = True
                        logger.info(
                            "Jellyfin: filename fallback matched '%s' via '%s'",
                            track.get("title"), item_path,
                        )
                        break

            if not found:
                logger.warning(
                    "Jellyfin: no match for '%s' — expected path '%s'",
                    track.get("title"), jellyfin_path,
                )
                unmatched.append(track)

    return matched_ids, unmatched


async def create_playlist(name: str, item_ids: list[str]) -> str:
    """Create a playlist in Jellyfin.

    Returns the Jellyfin playlist ID.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.jellyfin_url}/Playlists",
            headers={**_headers(), "Content-Type": "application/json"},
            json={
                "Name": name,
                "Ids": item_ids,
                "UserId": settings.jellyfin_user_id,
                "MediaType": "Audio",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("Id", "")


async def export_to_jellyfin(track_ids: list[str], playlist_name: str) -> dict:
    """Full pipeline: resolve local track IDs -> Jellyfin IDs -> create playlist.

    Args:
        track_ids: Ordered list of local track UUIDs.
        playlist_name: Display name for the Jellyfin playlist.

    Returns dict with:
        success, jellyfin_playlist_id, jellyfin_url (deep-link),
        matched_count, total_count, unmatched_tracks [{title, artist_name}]
    """
    if not _is_configured():
        return {
            "success": False,
            "error": "Jellyfin is not configured",
            "jellyfin_playlist_id": None,
            "jellyfin_url": None,
            "matched_count": 0,
            "total_count": len(track_ids),
            "unmatched_tracks": [],
        }

    # 1. Look up file paths from PostgreSQL
    tracks = get_track_files(track_ids)
    if not tracks:
        return {
            "success": False,
            "error": "No track files found in database",
            "jellyfin_playlist_id": None,
            "jellyfin_url": None,
            "matched_count": 0,
            "total_count": len(track_ids),
            "unmatched_tracks": [],
        }

    total = len(tracks)

    # 2. Resolve to Jellyfin Item IDs
    matched_ids, unmatched = await resolve_jellyfin_ids(tracks)

    if not matched_ids:
        return {
            "success": False,
            "error": "Could not match any tracks in Jellyfin",
            "jellyfin_playlist_id": None,
            "jellyfin_url": None,
            "matched_count": 0,
            "total_count": total,
            "unmatched_tracks": [
                {"title": t.get("title", "?"), "artist_name": t.get("artist_name", "?")}
                for t in unmatched
            ],
        }

    # 3. Create the playlist
    try:
        playlist_id = await create_playlist(playlist_name, matched_ids)
    except Exception as exc:
        logger.error("Failed to create Jellyfin playlist: %s", exc)
        return {
            "success": False,
            "error": f"Failed to create playlist in Jellyfin: {exc}",
            "jellyfin_playlist_id": None,
            "jellyfin_url": None,
            "matched_count": len(matched_ids),
            "total_count": total,
            "unmatched_tracks": [
                {"title": t.get("title", "?"), "artist_name": t.get("artist_name", "?")}
                for t in unmatched
            ],
        }

    jellyfin_url = f"{settings.jellyfin_url}/web/#/details?id={playlist_id}"

    logger.info(
        "Created Jellyfin playlist '%s' (%s) — %d/%d tracks matched",
        playlist_name, playlist_id, len(matched_ids), total,
    )

    return {
        "success": True,
        "error": None,
        "jellyfin_playlist_id": playlist_id,
        "jellyfin_url": jellyfin_url,
        "matched_count": len(matched_ids),
        "total_count": total,
        "unmatched_tracks": [
            {"title": t.get("title", "?"), "artist_name": t.get("artist_name", "?")}
            for t in unmatched
        ],
    }
