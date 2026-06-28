import app.snapshot.composer as comp
from app.trajectory.candidates import CandidateTrack
from app.trajectory.intent import PlaylistIntent


def _mk(tid, artist, album, gm, dark, banger, leg):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name=album, album_id=album, year=1985, duration_ms=200000,
        darkness=dark,
    )
    t.genres = ["thrash metal"]
    t.banger_score = banger
    t.album_legitimacy_score = leg
    return t


def test_compose_snapshot_breadth_and_no_arc(monkeypatch):
    # 6 artists, 3 tracks each, all niche-fit
    pool = []
    for ai in range(6):
        for ti in range(3):
            pool.append(_mk(f"{ai}-{ti}", f"artist{ai}", f"alb{ai}-{ti}",
                            gm=0.9, dark=0.8, banger=0.9 if ti == 0 else 0.1, leg=0.7))

    intent = PlaylistIntent(raw_prompt="evil 80s thrash", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    intent.genre_hints_raw = ["thrash metal"]
    intent.base_darkness = 0.8
    intent.year_range = (1980, 1989)

    monkeypatch.setattr(comp, "parse_prompt", lambda *a, **k: intent)
    monkeypatch.setattr(comp, "semantic_search", lambda *a, **k: list(pool))
    monkeypatch.setattr(comp, "keyword_search", lambda *a, **k: [])
    monkeypatch.setattr(comp, "_attach_artist_tags", lambda c: None)
    monkeypatch.setattr(comp, "_normalize_album_legitimacy", lambda c: None)
    # genre match: niche fit comes straight from the synthetic genres
    monkeypatch.setattr(comp, "compute_genre_match_score", lambda t, *a, **k: 0.9)
    monkeypatch.setattr(comp, "compute_genre_exclusion", lambda t, h: False)
    monkeypatch.setattr(comp, "log_generation", lambda **k: None)
    monkeypatch.setattr(comp, "update_track_usage", lambda ids: None)

    result = comp.compose_snapshot("evil 80s thrash", soft_cap=120)

    assert result.tracks, "expected a non-empty snapshot"
    # breadth: many distinct artists (not one band dominating)
    artists = {t.artist_id for t in result.tracks}
    assert len(artists) >= 5
    # no same-artist adjacency
    for a, b in zip(result.tracks, result.tracks[1:]):
        assert a.artist_id != b.artist_id
    # snapshot-specific metrics, and NO trajectory/arc metrics
    assert result.metrics["mode"] == "snapshot"
    assert result.metrics["distinct_artists"] == len(artists)
    assert "trajectory" not in result.metrics


def test_compose_snapshot_strict_floor_drops_offniche(monkeypatch):
    good = _mk("1", "a", "x", gm=0.9, dark=0.8, banger=0.9, leg=0.8)
    bad = _mk("2", "b", "y", gm=0.0, dark=0.0, banger=0.0, leg=0.0)
    intent = PlaylistIntent(raw_prompt="evil 80s thrash", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    intent.base_darkness = 0.8

    monkeypatch.setattr(comp, "parse_prompt", lambda *a, **k: intent)
    monkeypatch.setattr(comp, "semantic_search", lambda *a, **k: [good, bad])
    monkeypatch.setattr(comp, "keyword_search", lambda *a, **k: [])
    monkeypatch.setattr(comp, "_attach_artist_tags", lambda c: None)
    monkeypatch.setattr(comp, "_normalize_album_legitimacy", lambda c: None)
    monkeypatch.setattr(comp, "compute_genre_exclusion", lambda t, h: False)
    monkeypatch.setattr(comp, "log_generation", lambda **k: None)
    monkeypatch.setattr(comp, "update_track_usage", lambda ids: None)
    # real relevance via genre_match: good=0.9, bad=0.0
    monkeypatch.setattr(comp, "compute_genre_match_score",
                        lambda t, *a, **k: 0.9 if t.id == "1" else 0.0)

    result = comp.compose_snapshot("evil 80s thrash", soft_cap=120)
    assert {t.id for t in result.tracks} == {"1"}
    assert result.metrics["qualifying_tracks"] == 1


def test_compose_snapshot_year_range_is_a_hard_cut(monkeypatch):
    # in-range 1985, out-of-range 2023, and unknown-year (None) — only 1985 kept.
    in80s = _mk("1", "a", "x", gm=0.9, dark=0.8, banger=0.9, leg=0.8)
    in80s.year = 1985
    modern = _mk("2", "b", "y", gm=0.9, dark=0.8, banger=0.9, leg=0.8)
    modern.year = 2023
    unknown = _mk("3", "c", "z", gm=0.9, dark=0.8, banger=0.9, leg=0.8)
    unknown.year = None
    unknown.original_year = None

    intent = PlaylistIntent(raw_prompt="evil 80s thrash", prompt_embedding=[0.0] * 8)
    intent.genre_hints = ["thrash metal"]
    intent.base_darkness = 0.8
    intent.year_range = (1980, 1989)

    monkeypatch.setattr(comp, "parse_prompt", lambda *a, **k: intent)
    # search returns ALL three (simulating the keyword path that skipped the SQL year filter)
    monkeypatch.setattr(comp, "semantic_search", lambda *a, **k: [in80s, modern, unknown])
    monkeypatch.setattr(comp, "keyword_search", lambda *a, **k: [])
    monkeypatch.setattr(comp, "_attach_artist_tags", lambda c: None)
    monkeypatch.setattr(comp, "_normalize_album_legitimacy", lambda c: None)
    monkeypatch.setattr(comp, "compute_genre_match_score", lambda t, *a, **k: 0.9)
    monkeypatch.setattr(comp, "compute_genre_exclusion", lambda t, h: False)
    monkeypatch.setattr(comp, "log_generation", lambda **k: None)
    monkeypatch.setattr(comp, "update_track_usage", lambda ids: None)

    result = comp.compose_snapshot("evil 80s thrash", soft_cap=120)
    assert {t.id for t in result.tracks} == {"1"}
