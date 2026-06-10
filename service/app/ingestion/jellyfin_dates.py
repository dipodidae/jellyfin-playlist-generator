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
    """Set PremiereDate + ProductionYear on a Jellyfin album so they persist.

    Persistence uses the per-item ``LockData`` flag (whole-item metadata lock).
    NOTE: ``LockedFields`` is NOT used — its MetadataField enum has no
    PremiereDate/ProductionYear members, so locking individual date fields is
    impossible; ``LockData=True`` is what actually stops a metadata refresh from
    reverting these values.
    """
    # Fetch the full item DTO
    get_resp = await client.get(
        f"{settings.jellyfin_url}/Users/{settings.jellyfin_user_id}/Items/{jellyfin_album_id}",
        headers=_headers(),
    )
    get_resp.raise_for_status()
    dto = get_resp.json()
    dto["PremiereDate"] = premiere_date
    dto["ProductionYear"] = int(year)
    dto["LockData"] = True  # pin the whole item so a refresh won't revert the date
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
                SELECT a.id, a.title,
                       (SELECT ar.name FROM album_artists aa
                        JOIN artists ar ON ar.id = aa.artist_id
                        WHERE aa.album_id = a.id
                        ORDER BY aa.position LIMIT 1) AS artist_name,
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


def load_applied_ledger() -> dict[str, int]:
    """Return {app_album_id: applied_year} of dates already written to Jellyfin."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT album_id, applied_year FROM jellyfin_date_applied")
            return {str(r[0]): r[1] for r in cur.fetchall()}


def record_applied(album_id: str, jellyfin_album_id: str, year: int) -> None:
    """Mark an album as fixed at ``year`` so future runs skip it (idempotency ledger)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jellyfin_date_applied
                    (album_id, jellyfin_album_id, applied_year, applied_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (album_id) DO UPDATE
                    SET jellyfin_album_id = EXCLUDED.jellyfin_album_id,
                        applied_year = EXCLUDED.applied_year,
                        applied_at = now()
                """,
                (album_id, jellyfin_album_id, int(year)),
            )


def partition_by_ledger(albums: list[dict], ledger: dict[str, int], force: bool = False):
    """Split eligible albums into (to_process, already_applied_count).

    An album is skipped when ``force`` is False AND it was already written at the
    SAME ``year`` (the ledger value matches its current resolved original_year).
    Albums whose resolved year changed since last write are re-processed.
    """
    if force:
        return list(albums), 0
    to_process: list[dict] = []
    skipped = 0
    for a in albums:
        if ledger.get(a["album_id"]) == a["year"]:
            skipped += 1
        else:
            to_process.append(a)
    return to_process, skipped


async def fix_release_dates(progress_callback=None, force: bool = False) -> dict:
    """Push resolved original dates onto matching Jellyfin albums. Album-level, locked.

    Idempotent: albums already written at their current resolved year are skipped
    via the ``jellyfin_date_applied`` ledger (no Jellyfin call), so re-runs are short
    maintenance bursts touching only new/changed albums. ``force=True`` re-applies all.
    """
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        return {"error": "Jellyfin not configured (set jellyfin_url + jellyfin_api_key)"}

    albums = _load_eligible_albums()
    ledger = load_applied_ledger()
    to_process, already_applied = partition_by_ledger(albums, ledger, force)

    stats = {
        "eligible": len(albums), "already_applied": already_applied,
        "matched": 0, "updated": 0,
        "skipped_no_jellyfin_match": 0, "failed": 0, "errors": [],
    }
    # Nothing new/changed → skip the (expensive) Jellyfin library fetch entirely.
    if not to_process:
        return stats

    lp = settings.local_path_prefix or "/music"
    jp = settings.jellyfin_path_prefix or ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        audio_items = await fetch_audio_items(client)
        mapping, unresolved = resolve_album_id_map(
            [{"album_id": a["album_id"], "track_paths": a["track_paths"]} for a in to_process],
            audio_items, lp, jp,
        )
        if unresolved:
            jf_albums = await fetch_album_items(client)
            by_id = {a["album_id"]: a for a in to_process}
            for aid in unresolved:
                a = by_id[aid]
                jf_id = match_by_name(a["title"], a["artist_name"], jf_albums)
                if jf_id:
                    mapping[aid] = jf_id

        stats["matched"] = len(mapping)
        stats["skipped_no_jellyfin_match"] = len(to_process) - len(mapping)

        total = len(mapping)
        by_id = {a["album_id"]: a for a in to_process}
        for i, (app_id, jf_id) in enumerate(mapping.items()):
            a = by_id[app_id]
            try:
                premiere = build_premiere_date(a["year"], a["month"], a["day"], a["precision"])
                await update_album_date(client, jf_id, premiere, a["year"])
                record_applied(app_id, jf_id, a["year"])  # ledger: don't touch again
                stats["updated"] += 1
            except Exception as e:  # noqa: BLE001 — per-album failure must not abort the run
                stats["failed"] += 1
                if len(stats["errors"]) < 10:
                    stats["errors"].append(f"{a['artist_name']} - {a['title']}: {e}")
            if progress_callback:
                progress_callback(i + 1, total, f"Updated {i + 1}/{total} albums")
    return stats
