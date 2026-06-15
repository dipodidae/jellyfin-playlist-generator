"""PARSE_AUDIT P8 — single canonical sibling graph (GENRE_GRAPH)."""
from app.genre.manifold import get_related_families
from app.trajectory.intent import expand_genre_hints


def test_get_related_families_reads_genre_graph():
    rel = get_related_families("coldwave")
    assert "darkwave" in rel
    assert "post-punk" in rel
    # Broad umbrella genres are never returned as siblings.
    assert "rock" not in rel
    assert "metal" not in rel


def test_get_related_families_merged_families():
    # Families merged from the former _RELATED_FAMILIES still expand.
    assert "aor" in get_related_families("glam metal")
    # "punk" is a broad umbrella genre and is correctly filtered out; the
    # non-broad sibling remains.
    assert "metalcore" in get_related_families("hardcore")


def test_expand_genre_hints_preserves_originals_first():
    out = expand_genre_hints(["coldwave"])
    assert out[0] == "coldwave"
    assert "darkwave" in out
    # No duplicates.
    assert len(out) == len(set(out))


def test_expand_genre_hints_empty():
    assert expand_genre_hints([]) == []
