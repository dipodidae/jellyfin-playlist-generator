"""Tests for scan orphan reconciliation (P1).

Pure guard-logic tests run anywhere (no DB). The DB integration test pulls a raw
pooled connection and ALWAYS rolls back, so it never mutates real data; it is
skipped automatically when no database is reachable.
"""
import pytest

from app.ingestion.scanner import (
    PRUNE_MAX_FRACTION,
    evaluate_prune_guard,
)

# --- Pure guard logic -------------------------------------------------------

def test_guard_zero_files_is_hard_error_even_with_force():
    # Empty/unmounted library: nothing on disk but tracks exist in DB.
    skip, reason = evaluate_prune_guard(
        orphan_count=500, total_tracks=500, files_found=0, force_prune=True
    )
    assert skip is True
    assert reason == "zero_files"


def test_guard_zero_files_with_empty_db_is_noop_not_error():
    # Fresh DB, nothing on disk yet — not a wipe, nothing to delete.
    skip, reason = evaluate_prune_guard(
        orphan_count=0, total_tracks=0, files_found=0, force_prune=False
    )
    assert skip is False
    assert reason is None


def test_guard_over_threshold_aborts():
    # 30% of the library would be deleted -> tripwire.
    skip, reason = evaluate_prune_guard(
        orphan_count=3000, total_tracks=10000, files_found=7000, force_prune=False
    )
    assert skip is True
    assert reason == "over_threshold"


def test_guard_over_threshold_overridden_by_force():
    skip, reason = evaluate_prune_guard(
        orphan_count=3000, total_tracks=10000, files_found=7000, force_prune=True
    )
    assert skip is False
    assert reason is None


def test_guard_normal_small_delete_proceeds():
    # A normal album delete (~10 tracks) of a 10k library is well under 20%.
    skip, reason = evaluate_prune_guard(
        orphan_count=10, total_tracks=10000, files_found=9990, force_prune=False
    )
    assert skip is False
    assert reason is None


def test_guard_exactly_at_threshold_proceeds():
    # Strictly-greater-than threshold: exactly 20% is allowed.
    at = int(PRUNE_MAX_FRACTION * 10000)
    skip, reason = evaluate_prune_guard(
        orphan_count=at, total_tracks=10000, files_found=8000, force_prune=False
    )
    assert skip is False
    assert reason is None


def test_guard_no_orphans_proceeds():
    skip, reason = evaluate_prune_guard(
        orphan_count=0, total_tracks=10000, files_found=10000, force_prune=False
    )
    assert skip is False
    assert reason is None


# --- DB integration (rolled back, never commits) ----------------------------

def _db_or_skip():
    try:
        from app.database_pg import get_pool
        pool = get_pool()
        return pool
    except Exception as e:  # pragma: no cover - depends on environment
        pytest.skip(f"No database available: {e}")


def test_orphan_detection_and_cascade_delete_rollback():
    """Insert a synthetic all-missing track, confirm it is detected and that
    reconcile cascade-deletes it plus the emptied album/artist. Rolls back."""
    from app.ingestion.scanner import find_orphan_track_ids, reconcile_orphans

    pool = _db_or_skip()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            # Synthetic artist / album / track / all-missing file.
            cur.execute(
                "INSERT INTO artists (name) VALUES (%s) RETURNING id",
                ("__test_orphan_artist__",),
            )
            artist_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO albums (title, year) VALUES (%s, %s) RETURNING id",
                ("__test_orphan_album__", 1999),
            )
            album_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO tracks (fingerprint, title, duration_ms) "
                "VALUES (%s, %s, %s) RETURNING id",
                ("__test_orphan_fp__", "__test_orphan_track__", 1000),
            )
            track_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO track_albums (track_id, album_id) VALUES (%s, %s)",
                (track_id, album_id),
            )
            cur.execute(
                "INSERT INTO track_artists (track_id, artist_id) VALUES (%s, %s)",
                (track_id, artist_id),
            )
            # File row marked missing -> track has no present file.
            cur.execute(
                "INSERT INTO track_files (track_id, path, size, mtime, format, missing_since) "
                "VALUES (%s, %s, %s, now(), %s, now())",
                (track_id, "/nonexistent/__test_orphan__.flac", 1, "flac"),
            )

            # Detected as orphan.
            orphans = find_orphan_track_ids(cur)
            assert str(track_id) in orphans

            # force_prune so the threshold (real DB may have many orphans) can't
            # abort the synthetic delete; files_found huge so zero-files never trips.
            res = reconcile_orphans(cur, files_found=10**9, force_prune=True)
            assert res["prune_skipped"] is False
            assert res["tracks_removed"] >= 1

            # Track is gone; cascade removed its file/links.
            cur.execute("SELECT 1 FROM tracks WHERE id = %s", (track_id,))
            assert cur.fetchone() is None
            cur.execute(
                "SELECT 1 FROM track_files WHERE track_id = %s", (track_id,)
            )
            assert cur.fetchone() is None
            # Emptied album/artist pruned.
            cur.execute("SELECT 1 FROM albums WHERE id = %s", (album_id,))
            assert cur.fetchone() is None
            cur.execute("SELECT 1 FROM artists WHERE id = %s", (artist_id,))
            assert cur.fetchone() is None
        conn.rollback()  # never persist anything
    finally:
        conn.rollback()
        pool.putconn(conn)


def test_track_with_one_present_file_is_not_orphaned_rollback():
    """A multi-file track keeps its row if at least one file is present."""
    from app.ingestion.scanner import find_orphan_track_ids

    pool = _db_or_skip()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tracks (fingerprint, title, duration_ms) "
                "VALUES (%s, %s, %s) RETURNING id",
                ("__test_present_fp__", "__test_present_track__", 1000),
            )
            track_id = cur.fetchone()[0]
            # One missing file, one present file.
            cur.execute(
                "INSERT INTO track_files (track_id, path, size, mtime, format, missing_since) "
                "VALUES (%s, %s, %s, now(), %s, now())",
                (track_id, "/nonexistent/__test_present_a__.flac", 1, "flac"),
            )
            cur.execute(
                "INSERT INTO track_files (track_id, path, size, mtime, format, missing_since) "
                "VALUES (%s, %s, %s, now(), %s, NULL)",
                (track_id, "/somewhere/__test_present_b__.flac", 1, "flac"),
            )
            orphans = find_orphan_track_ids(cur)
            assert str(track_id) not in orphans
        conn.rollback()
    finally:
        conn.rollback()
        pool.putconn(conn)
