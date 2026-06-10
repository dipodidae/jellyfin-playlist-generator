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


_PAGE = 500


def _headers() -> dict:
    return {"X-Emby-Token": settings.jellyfin_api_key}


async def fetch_audio_items(client: httpx.AsyncClient) -> list[dict]:
    """Page through all Jellyfin Audio items, returning [{Id, AlbumId, Path}]."""
    items: list[dict] = []
    start = 0
    while True:
        resp = await client.get(
            f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items",
            headers=_headers(),
            params={
                "IncludeItemTypes": "Audio",
                "Recursive": "true",
                "Fields": "Path",
                "StartIndex": start,
                "Limit": _PAGE,
            },
        )
        resp.raise_for_status()
        page = resp.json().get("Items", [])
        if not page:
            break
        for it in page:
            items.append({"Id": it.get("Id"), "AlbumId": it.get("AlbumId"), "Path": it.get("Path")})
        start += len(page)
        if len(page) < _PAGE:
            break
    return items


async def fetch_album_items(client: httpx.AsyncClient) -> list[dict]:
    """Page through all Jellyfin MusicAlbum items, returning [{Id, Name, AlbumArtist}]."""
    items: list[dict] = []
    start = 0
    while True:
        resp = await client.get(
            f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items",
            headers=_headers(),
            params={
                "IncludeItemTypes": "MusicAlbum",
                "Recursive": "true",
                "Fields": "AlbumArtist",
                "StartIndex": start,
                "Limit": _PAGE,
            },
        )
        resp.raise_for_status()
        page = resp.json().get("Items", [])
        if not page:
            break
        for it in page:
            artist = it.get("AlbumArtist")
            if not artist and it.get("AlbumArtists"):
                artist = (it["AlbumArtists"][0] or {}).get("Name")
            items.append({"Id": it.get("Id"), "Name": it.get("Name"), "AlbumArtist": artist})
        start += len(page)
        if len(page) < _PAGE:
            break
    return items


async def update_album_date(
    client: httpx.AsyncClient,
    jellyfin_album_id: str,
    premiere_date: str,
    year: int,
) -> None:
    """Set PremiereDate + ProductionYear on a Jellyfin album and lock those fields."""
    # Fetch the full item DTO
    get_resp = await client.get(
        f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items/{jellyfin_album_id}",
        headers=_headers(),
    )
    get_resp.raise_for_status()
    dto = get_resp.json()
    dto["PremiereDate"] = premiere_date
    dto["ProductionYear"] = int(year)
    locked = set(dto.get("LockedFields") or [])
    locked.update({"PremiereDate", "ProductionYear"})
    dto["LockedFields"] = list(locked)
    # POST the mutated DTO back (UpdateItem)
    post_resp = await client.post(
        f"{settings.jellyfin_url}/Items/{jellyfin_album_id}",
        headers={**_headers(), "Content-Type": "application/json"},
        json=dto,
    )
    post_resp.raise_for_status()


def _load_eligible_albums() -> list[dict]:
    """App albums with a resolved original date + representative track paths."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.title, a.artist_name,
                       ard.original_year, ard.original_month, ard.original_day, ard.precision,
                       ARRAY(
                           SELECT tf.path FROM track_albums ta
                           JOIN track_files tf ON tf.track_id = ta.track_id
                           WHERE ta.album_id = a.id AND tf.path IS NOT NULL
                           LIMIT 5
                       ) AS track_paths
                FROM albums a
                JOIN album_release_dates ard ON ard.album_id = a.id
                WHERE ard.original_year IS NOT NULL
            """)
            rows = cur.fetchall()
    return [
        {
            "album_id": str(r[0]), "title": r[1], "artist_name": r[2],
            "year": r[3], "month": r[4], "day": r[5], "precision": r[6] or "year",
            "track_paths": list(r[7] or []),
        }
        for r in rows
    ]


async def fix_release_dates(progress_callback=None) -> dict:
    """Push resolved original dates onto matching Jellyfin albums. Album-level, locked."""
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        return {"error": "Jellyfin not configured (set jellyfin_url + jellyfin_api_key)"}

    albums = _load_eligible_albums()
    stats = {
        "eligible": len(albums), "matched": 0, "updated": 0,
        "skipped_no_jellyfin_match": 0, "failed": 0, "errors": [],
    }
    if not albums:
        return stats

    lp = settings.local_path_prefix or "/music"
    jp = settings.jellyfin_path_prefix or ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        audio_items = await fetch_audio_items(client)
        mapping, unresolved = resolve_album_id_map(
            [{"album_id": a["album_id"], "track_paths": a["track_paths"]} for a in albums],
            audio_items, lp, jp,
        )
        if unresolved:
            jf_albums = await fetch_album_items(client)
            by_id = {a["album_id"]: a for a in albums}
            for aid in unresolved:
                a = by_id[aid]
                jf_id = match_by_name(a["title"], a["artist_name"], jf_albums)
                if jf_id:
                    mapping[aid] = jf_id

        stats["matched"] = len(mapping)
        stats["skipped_no_jellyfin_match"] = len(albums) - len(mapping)

        total = len(mapping)
        by_id = {a["album_id"]: a for a in albums}
        for i, (app_id, jf_id) in enumerate(mapping.items()):
            a = by_id[app_id]
            try:
                premiere = build_premiere_date(a["year"], a["month"], a["day"], a["precision"])
                await update_album_date(client, jf_id, premiere, a["year"])
                stats["updated"] += 1
            except Exception as e:  # noqa: BLE001 — per-album failure must not abort the run
                stats["failed"] += 1
                if len(stats["errors"]) < 10:
                    stats["errors"].append(f"{a['artist_name']} - {a['title']}: {e}")
            if progress_callback:
                progress_callback(i + 1, total, f"Updated {i + 1}/{total} albums")
    return stats
