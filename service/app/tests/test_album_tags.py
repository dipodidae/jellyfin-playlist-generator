"""Tests for unified album-tag collection (P2).

Pure normalization/coercion tests run anywhere. DB upsert tests pull a raw
pooled connection and ALWAYS roll back; skipped when no DB is reachable.
"""
import pytest

from app.ingestion.album_tags import (
    _coerce_items,
    normalize_tag,
    save_album_tags,
)

# --- Pure logic -------------------------------------------------------------

def test_normalize_lowercases_and_trims():
    assert normalize_tag("  Black   Metal ") == "black metal"
    assert normalize_tag("POST-PUNK") == "post-punk"


def test_normalize_blank_inputs():
    assert normalize_tag("") == ""
    assert normalize_tag("   ") == ""
    assert normalize_tag(None) == ""


def test_coerce_accepts_strings_and_dicts():
    rows = _coerce_items(["Rock", {"name": "Jazz", "weight": 80, "position": 1}])
    by_tag = {r["tag"]: r for r in rows}
    assert by_tag["rock"]["weight"] is None
    assert by_tag["jazz"]["weight"] == 80
    assert by_tag["jazz"]["position"] == 1


def test_coerce_merges_duplicates_keeping_max_weight_min_position():
    rows = _coerce_items([
        {"name": "Doom", "weight": 10, "position": 3},
        {"name": "doom ", "weight": 50, "position": 1},
        "DOOM",
    ])
    assert len(rows) == 1
    assert rows[0]["tag"] == "doom"
    assert rows[0]["weight"] == 50
    assert rows[0]["position"] == 1


def test_coerce_skips_junk_and_blanks():
    rows = _coerce_items(["", "   ", {"name": ""}, 12345, None, "Valid"])
    assert [r["tag"] for r in rows] == ["valid"]


# --- DB upsert (rolled back) ------------------------------------------------

def _db_or_skip():
    try:
        from app.database_pg import get_pool
        return get_pool()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"No database available: {e}")


def test_save_album_tags_upsert_multisource_rollback():
    pool = _db_or_skip()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO albums (title, year) VALUES (%s, %s) RETURNING id",
                ("__test_at_album__", 1991),
            )
            album_id = cur.fetchone()[0]

            n1 = save_album_tags(
                cur, album_id, "discogs",
                ["Rock", "Electronic"], kind="genre",
            )
            n2 = save_album_tags(
                cur, album_id, "lastfm",
                [{"name": "shoegaze", "weight": 100}, {"name": "Rock", "weight": 40}],
                kind="tag",
            )
            assert n1 == 2 and n2 == 2

            # Different sources/kinds coexist for the same album.
            cur.execute("SELECT count(*) FROM album_tags WHERE album_id = %s", (album_id,))
            assert cur.fetchone()[0] == 4

            # Re-running is idempotent and refreshes weight.
            save_album_tags(
                cur, album_id, "lastfm",
                [{"name": "shoegaze", "weight": 55}], kind="tag",
            )
            cur.execute(
                "SELECT weight FROM album_tags "
                "WHERE album_id=%s AND source='lastfm' AND tag='shoegaze'",
                (album_id,),
            )
            assert cur.fetchone()[0] == pytest.approx(55.0)
            cur.execute("SELECT count(*) FROM album_tags WHERE album_id = %s", (album_id,))
            assert cur.fetchone()[0] == 4  # no new row from the re-run

        conn.rollback()
    finally:
        conn.rollback()
        pool.putconn(conn)


def test_save_album_tags_empty_is_noop():
    pool = _db_or_skip()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO albums (title, year) VALUES (%s, %s) RETURNING id",
                ("__test_at_empty__", 1991),
            )
            album_id = cur.fetchone()[0]
            assert save_album_tags(cur, album_id, "discogs", []) == 0
            assert save_album_tags(cur, album_id, "discogs", ["", "  "]) == 0
        conn.rollback()
    finally:
        conn.rollback()
        pool.putconn(conn)


def test_save_album_tags_rejects_bad_kind():
    with pytest.raises(ValueError):
        save_album_tags(None, "x", "discogs", ["rock"], kind="bogus")
