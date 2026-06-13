"""Unified album-level tag/genre persistence (P2).

A single store (`album_tags`) collects genre/tag signal from every source so the
scoring layer can read it uniformly. This module holds the normalization and the
upsert helper; each ingestion source calls ``save_album_tags`` with its parsed
items. Pure of network I/O — it only takes a cursor.
"""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")

VALID_KINDS = {"genre", "style", "tag"}


def normalize_tag(name: str) -> str:
    """Lowercase, trim, and collapse internal whitespace. '' for junk input."""
    if not name:
        return ""
    return _WS.sub(" ", str(name).strip().lower())


def _coerce_items(items: list[Any]) -> list[dict[str, Any]]:
    """Accept a list of strings or dicts; return normalized dict rows.

    Duplicate normalized names are merged, keeping the max weight and the first
    (smallest) position seen.
    """
    merged: dict[str, dict[str, Any]] = {}
    for raw in items or []:
        if isinstance(raw, str):
            name, weight, position = raw, None, None
        elif isinstance(raw, dict):
            name = raw.get("name") or raw.get("tag") or ""
            weight = raw.get("weight")
            position = raw.get("position")
        else:
            continue
        norm = normalize_tag(name)
        if not norm:
            continue
        existing = merged.get(norm)
        if existing is None:
            merged[norm] = {"tag": norm, "weight": weight, "position": position}
        else:
            if weight is not None and (
                existing["weight"] is None or weight > existing["weight"]
            ):
                existing["weight"] = weight
            if position is not None and (
                existing["position"] is None or position < existing["position"]
            ):
                existing["position"] = position
    return list(merged.values())


def save_album_tags(
    cur,
    album_id: str,
    source: str,
    items: list[Any],
    kind: str = "genre",
) -> int:
    """Upsert album tags for one (album, source, kind). Returns rows written.

    ``items`` may be plain strings or dicts with optional ``weight``/``position``.
    Blank/junk names are skipped. Existing rows are updated (weight/position
    refreshed) so re-running enrichment is idempotent.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid kind: {kind!r}")
    rows = _coerce_items(items)
    if not rows:
        return 0
    written = 0
    for row in rows:
        cur.execute(
            """
            INSERT INTO album_tags (album_id, source, tag, kind, weight, position)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (album_id, source, kind, tag) DO UPDATE SET
                weight = EXCLUDED.weight,
                position = EXCLUDED.position
            """,
            (album_id, source, row["tag"], kind, row["weight"], row["position"]),
        )
        written += 1
    return written
