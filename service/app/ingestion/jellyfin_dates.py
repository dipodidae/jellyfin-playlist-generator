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

NFO writing is FOLDER-CENTRIC: multiple app-albums that resolve to the same
folder directory are disambiguated by title matching against the folder basename.
Ambiguous folders (no title match, or title-match with conflicting years) are
skipped rather than written with a guessed year.

Year resolution is SINGLE-SOURCE: the ``original_year`` from ``album_release_dates``
(resolved by ``resolve_original_years_via_mb``) is the sole authority.  Albums
without a resolved year, or with a year < 1900, are skipped.  Folder-name
parsing and file-metadata fallbacks are intentionally absent — MusicBrainz
release-group ``first-release-date`` is more reliable than either.
"""

import logging
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from app.config import settings
from app.database_pg import get_connection
from app.trajectory.textnorm import normalize_title

logger = logging.getLogger(__name__)

_DISC_RE = re.compile(r"^(disc|cd)\s*\d+$", re.IGNORECASE)
_DATE_TAGS = frozenset({"year", "premiered", "releasedate", "lockdata"})
_XML_DECL = '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'


# ---------------------------------------------------------------------------
# Pure / testable functions (no I/O)
# ---------------------------------------------------------------------------

# Matches a leading "YYYY - ", "YYYY ", or "NN - " prefix in a folder basename.
_FOLDER_PREFIX_RE = re.compile(r"^\d{2,4}(?:\s+-\s+|\s+)")


def folder_album_name(folder_basename: str) -> str:
    """Strip a leading year/track-number prefix from a folder basename and normalize.

    Examples::

        >>> folder_album_name("1990 - Painkiller")
        'painkiller'
        >>> folder_album_name("Painkiller")
        'painkiller'
        >>> folder_album_name("2010 - Painkiller (Remastered)")
        'painkiller'
        >>> folder_album_name("01 - Holy Diver")
        'holy diver'
    """
    name = _FOLDER_PREFIX_RE.sub("", folder_basename, count=1)
    return normalize_title(name)


def choose_album_for_folder(candidates: list[dict], folder_basename: str) -> dict | None:
    """Return the one unambiguous album for a folder, or None if ambiguous.

    *candidates* is a list of album dicts with at least ``album_id``, ``title``,
    and ``year`` keys (same shape as ``_load_eligible_albums`` output).

    Decision logic
    --------------
    1. Compute ``want = folder_album_name(folder_basename)``.
    2. Filter to candidates whose ``normalize_title(title)`` equals ``want``,
       or (fallback) where one is a substring of the other (handles suffixes
       like "(Remastered)" that survive ``normalize_title`` because they don't
       contain a recognized version keyword).
    3. Deduplicate matched candidates by ``album_id``.
    4. Exactly one distinct album → return it.
       Multiple albums with the same ``year`` → return the first (year is all
       that matters for the NFO).
       No matches, or title-matches with conflicting years → return None.
    """
    want = folder_album_name(folder_basename)

    # Step 1: exact normalized-title match.
    matches = [c for c in candidates if normalize_title(c["title"]) == want]

    # Step 2: substring fallback (e.g. "painkiller (deluxe edition)" ↔ "painkiller").
    if not matches:
        matches = [
            c for c in candidates
            if (
                normalize_title(c["title"]) in want
                or want in normalize_title(c["title"])
            )
            and normalize_title(c["title"])  # guard against empty string
        ]

    if not matches:
        return None

    # Deduplicate by album_id.
    seen: dict[str, dict] = {}
    for c in matches:
        seen.setdefault(c["album_id"], c)
    unique = list(seen.values())

    if len(unique) == 1:
        return unique[0]

    # Multiple distinct albums matched — accept only if they all share the same
    # resolved year (None values are excluded from the conflict check; a None year
    # album doesn't conflict with a resolved-year album because the folder-year
    # fallback will be applied later).
    non_none_years = {c["year"] for c in unique if c["year"] is not None}
    if len(non_none_years) <= 1:
        return unique[0]

    # Conflicting resolved years → ambiguous → skip.
    return None


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


def _load_albums() -> list[dict]:
    """All app albums + representative track paths.

    LEFT JOINs ``album_release_dates`` so albums without a resolved date are
    included (year/month/day/precision will be ``None`` for those rows).
    Albums whose ``year`` is None (no resolved date) are skipped later in
    ``fix_release_dates`` — the LEFT JOIN is kept so that choose_album_for_folder
    can still disambiguate folders that contain both resolved and unresolved albums.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.title,
                       (SELECT ar.name FROM album_artists aa
                        JOIN artists ar ON ar.id = aa.artist_id
                        WHERE aa.album_id = a.id
                        ORDER BY aa.position LIMIT 1) AS artist_name,
                       ard.original_year, ard.original_month, ard.original_day, ard.precision,
                       ard.primary_source,
                       ARRAY(
                           SELECT tf.path FROM track_albums ta
                           JOIN track_files tf ON tf.track_id = ta.track_id
                           WHERE ta.album_id = a.id AND tf.path IS NOT NULL
                           LIMIT 5
                       ) AS track_paths
                FROM albums a
                LEFT JOIN album_release_dates ard ON ard.album_id = a.id
            """)
            rows = cur.fetchall()
    return [
        {
            "album_id": str(r[0]), "title": r[1], "artist_name": r[2],
            "year": r[3], "month": r[4], "day": r[5], "precision": r[6] or "year",
            "source": r[7],
            "track_paths": list(r[8] or []),
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

    The process is FOLDER-CENTRIC to handle messy libraries where one physical
    folder contains tracks from many app-albums (e.g. a compilation and its
    original studio release share the same directory):

    1. Load ALL albums + ledger (LEFT JOIN so unresolved albums are included).
    2. Group all albums by their resolved folder (first track path, disc-subfolder
       collapse via ``_DISC_RE``).  Albums with no track paths are counted as
       ``skipped_no_jellyfin_match``.
    3. For each folder run ``choose_album_for_folder`` against the candidates.
       - If None (no title match, or conflicting resolved years) → count all
         candidates as ``skipped_no_jellyfin_match`` and skip.
       - If a winner is chosen → use ``chosen["year"]`` (MB-resolved
         ``original_year`` from ``album_release_dates``).  If that year is None
         or < 1900 the folder is counted as ``skipped_no_jellyfin_match``.
    4. Ledger check (unless ``force=True``): skip if already applied at the same year.
    5. Write/merge ``album.nfo``, ``record_applied``, count ``updated``.
    6. After all writes, trigger one Jellyfin library refresh (best-effort).

    NFO writes are filesystem operations and do NOT require Jellyfin credentials.
    The refresh POST is skipped if jellyfin_url/jellyfin_api_key are not configured.

    Idempotent via the ``jellyfin_date_applied`` ledger. ``force=True`` re-applies all.
    """
    albums = _load_albums()
    ledger = load_applied_ledger()

    stats: dict = {
        "eligible": len(albums),
        "already_applied": 0,
        "matched": 0,
        "updated": 0,
        "skipped_no_jellyfin_match": 0,
        "failed": 0,
        "errors": [],
    }

    # --- Group ALL albums by resolved folder path ------------------------------
    # albums with no track paths are skipped immediately
    folder_to_candidates: dict[Path, list[dict]] = defaultdict(list)
    for album in albums:
        track_paths = album.get("track_paths") or []
        if not track_paths:
            stats["skipped_no_jellyfin_match"] += 1
            continue
        folder = Path(track_paths[0]).parent
        if _DISC_RE.match(folder.name):
            folder = folder.parent
        folder_to_candidates[folder].append(album)

    total = len(folder_to_candidates)
    if not total:
        return stats

    for i, (folder, candidates) in enumerate(folder_to_candidates.items()):
        chosen = choose_album_for_folder(candidates, folder.name)

        if chosen is None:
            # Ambiguous — skip all albums mapped to this folder.
            stats["skipped_no_jellyfin_match"] += len(candidates)
            if progress_callback:
                progress_callback(i + 1, total, f"Processing {i + 1}/{total}")
            continue

        stats["matched"] += 1

        # Year comes solely from the MB-resolved original_year in album_release_dates.
        year = chosen.get("year")
        if year is None or year < 1900:
            stats["skipped_no_jellyfin_match"] += 1
            if progress_callback:
                progress_callback(i + 1, total, f"Processing {i + 1}/{total}")
            continue

        # Ledger / idempotency check.
        if not force and ledger.get(chosen["album_id"]) == year:
            stats["already_applied"] += 1
            if progress_callback:
                progress_callback(i + 1, total, f"Processing {i + 1}/{total}")
            continue

        # month/day from the resolved row.
        month = chosen.get("month")
        day = chosen.get("day")

        try:
            nfo_path = folder / "album.nfo"
            existing_xml: str | None = None
            if nfo_path.exists():
                try:
                    existing_xml = nfo_path.read_text(encoding="utf-8")
                except OSError:
                    existing_xml = None

            if existing_xml and nfo_is_current(existing_xml, year):
                # NFO already has the right year + lockdata; record in ledger but
                # don't rewrite the file.
                record_applied(chosen["album_id"], "", year)
                stats["updated"] += 1
            else:
                content = build_album_nfo(
                    existing_xml,
                    chosen["title"],
                    year,
                    month,
                    day,
                )
                nfo_path.write_text(content, encoding="utf-8")
                record_applied(chosen["album_id"], "", year)
                stats["updated"] += 1

        except Exception as e:  # noqa: BLE001 — per-folder failure must not abort the run
            stats["failed"] += 1
            if len(stats["errors"]) < 10:
                stats["errors"].append(
                    f"{chosen.get('artist_name')} - {chosen.get('title')}: {e}"
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
