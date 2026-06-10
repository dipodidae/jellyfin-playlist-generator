"""Fix Jellyfin album release dates from the app's resolved original dates.

Pure helpers (no I/O) + an httpx Jellyfin client + an orchestrator. Matching is
path-based (both systems index the same files via the configured prefix mapping)
with a normalized name fallback.
"""

import logging

import httpx

from app.config import settings
from app.database_pg import get_connection
from app.trajectory.textnorm import normalize_artist, normalize_title

logger = logging.getLogger(__name__)


def translate_path(local_path: str, local_prefix: str, jellyfin_prefix: str) -> str:
    """Rewrite an app /music path to the path Jellyfin reports. Passthrough if no prefix match."""
    lp = local_prefix.rstrip("/")
    jp = jellyfin_prefix.rstrip("/")
    if lp and local_path.startswith(lp):
        return jp + local_path[len(lp):]
    return local_path


def build_premiere_date(year, month, day, precision: str) -> str:
    """ISO-8601 PremiereDate string Jellyfin accepts. Missing month/day default to 01."""
    m = month if (precision in ("month", "day") and month) else 1
    d = day if (precision == "day" and day) else 1
    return f"{int(year):04d}-{int(m):02d}-{int(d):02d}T00:00:00.0000000Z"


def resolve_album_id_map(app_albums, jellyfin_audio_items, local_prefix, jellyfin_prefix):
    """Map app album_id -> Jellyfin AlbumId via translated track paths.

    app_albums: [{"album_id": str, "track_paths": [str, ...]}]
    jellyfin_audio_items: [{"Id", "AlbumId", "Path"}]
    Returns (mapping, unresolved_album_ids).
    """
    by_path = {it.get("Path"): it.get("AlbumId") for it in jellyfin_audio_items if it.get("Path")}
    mapping: dict[str, str] = {}
    unresolved: list[str] = []
    for alb in app_albums:
        found = None
        for p in alb.get("track_paths", []):
            jf_path = translate_path(p, local_prefix, jellyfin_prefix)
            album_id = by_path.get(jf_path)
            if album_id:
                found = album_id
                break
        if found:
            mapping[alb["album_id"]] = found
        else:
            unresolved.append(alb["album_id"])
    return mapping, unresolved


def match_by_name(app_album_name, app_artist, jellyfin_albums) -> str | None:
    """Normalized AlbumArtist+Name fallback match. Returns Jellyfin album Id or None.

    Returns None when the name+artist is AMBIGUOUS (matches more than one Jellyfin
    album) — libraries with duplicate songs spread across multiple albums often have
    several albums sharing a name/artist (studio vs compilation), and guessing one
    would stamp the wrong album. Path matching is the reliable route; name fallback
    only fires for a single unambiguous hit.
    """
    want_title = normalize_title(app_album_name or "")
    want_artist = normalize_artist(app_artist or "")
    matches = [
        alb.get("Id") for alb in jellyfin_albums
        if normalize_title(alb.get("Name") or "") == want_title
        and normalize_artist(alb.get("AlbumArtist") or "") == want_artist
    ]
    return matches[0] if len(matches) == 1 else None
