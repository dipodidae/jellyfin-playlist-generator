"""Fix Jellyfin album release dates by writing durable album.nfo sidecars.

Approach
--------
The previous API/LockData approach reverted on every Jellyfin metadata refresh
because the MusicBrainz provider overrides ``LockData`` during a full refresh.

The durable fix is an ``album.nfo`` sidecar in each album folder:
- ``<year>``, ``<premiered>``, ``<releasedate>`` carry the correct original year.
- ``<lockdata>true</lockdata>`` stops the online provider from overriding values.
- Jellyfin's NFO reader runs first and the lock is filesystem-persistent.

The container's ``/music`` mount must be read-write for this to work.

Pure helpers (no I/O) at the top are ported from the host-side
``scripts/jellyfin_nfo_dates.py`` — identical logic.
"""

import logging
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from app.config import settings
from app.database_pg import get_connection

logger = logging.getLogger(__name__)

_DISC_RE = re.compile(r"^(disc|cd)\s*\d+$", re.IGNORECASE)
_DATE_TAGS = frozenset({"year", "premiered", "releasedate", "lockdata"})
_XML_DECL = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'


# ---------------------------------------------------------------------------
# Pure / testable functions (no I/O)
# ---------------------------------------------------------------------------


def iso_date(year: int, month: int | None, day: int | None) -> str:
    """Format a partial date as ISO-8601 ``YYYY-MM-DD``, defaulting month/day to 01.

    >>> iso_date(1990, None, None)
    '1990-01-01'
    >>> iso_date(1983, 5, 25)
    '1983-05-25'
    >>> iso_date(2001, 3, None)
    '2001-03-01'
    """
    m = month if month is not None else 1
    d = day if day is not None else 1
    return f"{year:04d}-{m:02d}-{d:02d}"


def build_album_nfo(
    existing_xml: str | None,
    title: str,
    year: int,
    month: int | None,
    day: int | None,
) -> str:
    """Build (or update) an ``album.nfo`` XML string.

    If *existing_xml* is ``None``, a minimal ``<album>`` element is created.
    Otherwise the existing XML is parsed and:
    - ``<year>``, ``<premiered>``, ``<releasedate>``, ``<lockdata>`` are
      set/overwritten.
    - Any child element whose tag starts with ``musicbrainz`` is removed so
      Jellyfin cannot re-fetch a wrong date via a stale MB release id.
    - All other existing child elements are preserved.
    - A ``<title>`` is added if none exists.

    The returned string includes the XML declaration line.
    """
    date_str = iso_date(year, month, day)

    if existing_xml:
        try:
            root = ET.fromstring(existing_xml)
        except ET.ParseError:
            root = ET.Element("album")
    else:
        root = ET.Element("album")

    # Remove musicbrainz* elements and date-related elements (re-added below).
    to_remove = [
        el for el in list(root)
        if el.tag.lower().startswith("musicbrainz") or el.tag.lower() in _DATE_TAGS
    ]
    for el in to_remove:
        root.remove(el)

    # Ensure <title> exists.
    if root.find("title") is None:
        title_el = ET.SubElement(root, "title")
        title_el.text = title

    # Append date fields in a consistent order.
    year_el = ET.SubElement(root, "year")
    year_el.text = str(year)

    premiered_el = ET.SubElement(root, "premiered")
    premiered_el.text = date_str

    releasedate_el = ET.SubElement(root, "releasedate")
    releasedate_el.text = date_str

    lock_el = ET.SubElement(root, "lockdata")
    lock_el.text = "true"

    body = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return f"{_XML_DECL}\n{body}"


def nfo_is_current(existing_xml: str, year: int) -> bool:
    """Return True if *existing_xml* already has the correct year and lockdata=true.

    Parsing errors are treated as "not current" so the NFO is rewritten.
    """
    try:
        root = ET.fromstring(existing_xml)
    except ET.ParseError:
        return False

    year_el = root.find("year")
    lock_el = root.find("lockdata")

    if year_el is None or year_el.text is None:
        return False
    try:
        nfo_year = int(year_el.text.strip())
    except ValueError:
        return False

    if nfo_year != year:
        return False

    return not (lock_el is None or (lock_el.text or "").strip().lower() != "true")


# ---------------------------------------------------------------------------
# DB helpers (side-effecting; tested via integration)
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"X-Emby-Token": settings.jellyfin_api_key}


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
    """Return {app_album_id: applied_year} of dates already written."""
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


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


async def fix_release_dates(progress_callback=None, force: bool = False) -> dict:
    """Write durable album.nfo sidecars so Jellyfin shows correct original release years.

    For each eligible album (resolved original_year in the DB):
    1. Derive the album folder from the first track path (container path under /music).
       Collapses disc sub-folders (``disc N`` / ``cd N``) to the album root.
    2. Read any existing album.nfo; skip if already current (correct year + lockdata).
    3. Write a new/merged album.nfo with <year>, <premiered>, <releasedate>,
       <lockdata>true</lockdata>; strips musicbrainz* elements that would cause
       Jellyfin to re-fetch and override the date.
    4. After all writes, trigger one Jellyfin library refresh (best-effort).

    NFO writes are filesystem operations and do NOT require Jellyfin credentials.
    The refresh POST is skipped if jellyfin_url/jellyfin_api_key are not configured.

    Idempotent via the ``jellyfin_date_applied`` ledger. ``force=True`` re-applies all.
    """
    albums = _load_eligible_albums()
    ledger = load_applied_ledger()
    to_process, already_applied = partition_by_ledger(albums, ledger, force)

    stats: dict = {
        "eligible": len(albums),
        "already_applied": already_applied,
        "matched": 0,
        "updated": 0,
        "skipped_no_jellyfin_match": 0,
        "failed": 0,
        "errors": [],
    }

    if not to_process:
        return stats

    total = len(to_process)
    for i, album in enumerate(to_process):
        track_paths = album.get("track_paths") or []
        if not track_paths:
            stats["skipped_no_jellyfin_match"] += 1
            if progress_callback:
                progress_callback(i + 1, total, f"Processing {i + 1}/{total}")
            continue

        try:
            folder = Path(track_paths[0]).parent
            if _DISC_RE.match(folder.name):
                folder = folder.parent

            stats["matched"] += 1

            nfo_path = folder / "album.nfo"
            existing_xml: str | None = None
            if nfo_path.exists():
                try:
                    existing_xml = nfo_path.read_text(encoding="utf-8")
                except OSError:
                    existing_xml = None

            year = album["year"]
            if existing_xml and nfo_is_current(existing_xml, year):
                # NFO already has the right year + lockdata; record in ledger but
                # don't rewrite the file.
                record_applied(album["album_id"], "", year)
                stats["updated"] += 1
            else:
                content = build_album_nfo(
                    existing_xml,
                    album["title"],
                    year,
                    album.get("month"),
                    album.get("day"),
                )
                nfo_path.write_text(content, encoding="utf-8")
                record_applied(album["album_id"], "", year)
                stats["updated"] += 1

        except Exception as e:  # noqa: BLE001 — per-album failure must not abort the run
            stats["failed"] += 1
            if len(stats["errors"]) < 10:
                stats["errors"].append(
                    f"{album.get('artist_name')} - {album.get('title')}: {e}"
                )

        if progress_callback:
            progress_callback(i + 1, total, f"Processing {i + 1}/{total}")

    # Best-effort Jellyfin library refresh so it re-reads the new NFOs.
    if settings.jellyfin_url and settings.jellyfin_api_key:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    f"{settings.jellyfin_url}/Library/Refresh",
                    headers=_headers(),
                )
        except Exception as e:  # noqa: BLE001 — refresh failure must not fail the run
            logger.warning("Jellyfin /Library/Refresh failed (ignored): %s", e)
    else:
        logger.info(
            "Jellyfin credentials not configured — NFOs written but library refresh skipped"
        )

    return stats
