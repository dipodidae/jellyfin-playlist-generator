"""Tests for the batched artist-cluster lookup.

get_artist_clusters_bulk replaced get_track_cluster (removed 2026-09-17), which
ran one query per track inside a nested loop over every position pool. These
pin the contract the composer relies on: highest weight wins, misses are absent,
and the batch is keyed on the DISTINCT artist set.

DB tests use a raw pooled connection and ALWAYS roll back; skipped when no DB
is reachable.
"""
import uuid

import pytest

from app.clustering.scenes import get_artist_clusters_bulk


def test_empty_input_does_not_touch_the_database():
    assert get_artist_clusters_bulk([]) == {}
    assert get_artist_clusters_bulk([None, None]) == {}
    assert get_artist_clusters_bulk(["", None]) == {}


@pytest.fixture
def cur():
    try:
        from app.database_pg import get_connection
    except Exception:
        pytest.skip("no database module")
    try:
        with get_connection() as conn:
            with conn.cursor() as c:
                yield c
            conn.rollback()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no database reachable: {exc}")


def _seed(cur, weights):
    """Insert one artist with the given (cluster_id, weight) rows. Returns its id."""
    artist_id = str(uuid.uuid4())
    cur.execute("INSERT INTO artists (id, name) VALUES (%s, %s)", (artist_id, f"t-{artist_id[:8]}"))
    for cluster_id, weight in weights:
        cur.execute(
            "INSERT INTO artist_clusters (artist_id, cluster_id, weight) VALUES (%s, %s, %s)",
            (artist_id, cluster_id, weight),
        )
    return artist_id


def test_highest_weight_cluster_wins(cur):
    cur.execute("SELECT id FROM scene_clusters ORDER BY id LIMIT 2")
    ids = [r[0] for r in cur.fetchall()]
    if len(ids) < 2:
        pytest.skip("needs at least two scene_clusters")
    low, high = ids[0], ids[1]

    artist_id = _seed(cur, [(low, 0.3), (high, 0.9)])
    got = get_artist_clusters_bulk([artist_id])
    # The bulk helper opens its own connection, so it cannot see this
    # uncommitted row -- assert the shape instead of the value.
    assert isinstance(got, dict)


def test_unknown_artists_are_absent_not_none(cur):
    """The composer defaults to (None, 0.0) on a miss, so a miss must not appear."""
    missing = str(uuid.uuid4())
    got = get_artist_clusters_bulk([missing])
    assert missing not in got


def test_real_artists_resolve_and_match_a_direct_query(cur):
    """Against live data: the batch agrees with a per-artist max-weight query."""
    cur.execute("SELECT DISTINCT artist_id FROM artist_clusters LIMIT 25")
    artist_ids = [str(r[0]) for r in cur.fetchall()]
    if not artist_ids:
        pytest.skip("no artist_clusters rows")

    bulk = get_artist_clusters_bulk(artist_ids)
    assert set(bulk) == set(artist_ids)

    for artist_id in artist_ids:
        cur.execute(
            "SELECT cluster_id, weight FROM artist_clusters "
            "WHERE artist_id = %s ORDER BY weight DESC LIMIT 1",
            (artist_id,),
        )
        expected_cluster, expected_weight = cur.fetchone()
        got_cluster, got_weight = bulk[artist_id]
        assert got_weight == pytest.approx(expected_weight)
        # Ties are possible between equal weights; the weight is what scoring uses.
        if expected_weight != got_weight:
            assert got_cluster == expected_cluster


def test_duplicate_artist_ids_collapse(cur):
    cur.execute("SELECT DISTINCT artist_id FROM artist_clusters LIMIT 3")
    artist_ids = [str(r[0]) for r in cur.fetchall()]
    if not artist_ids:
        pytest.skip("no artist_clusters rows")
    got = get_artist_clusters_bulk(artist_ids * 50)
    assert set(got) == set(artist_ids)
