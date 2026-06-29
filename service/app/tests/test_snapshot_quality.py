"""Snapshot quality biasing (studio>live, MA legitimacy, classics) + strict niche."""
from app.trajectory.candidates import CandidateTrack
from app.snapshot.selection import (
    classic_bonus, compute_snapshot_scores, carries_target_genre, select_artist_tracks,
)


def _t(tid, artist="a", album="x", gm=0.9, dark=0.8, banger=0.3, leg=0.3,
       year=1985, version="studio", genres=None, album_genres=None, artist_tags=None):
    t = CandidateTrack(
        id=tid, title=f"t{tid}", artist_name=artist, artist_id=artist,
        album_name=album, album_id=album, year=year, duration_ms=200000, darkness=dark,
    )
    t.genre_match_score = gm
    t.banger_score = banger
    t.album_legitimacy_score = leg
    t.version_type = version
    t.genres = genres if genres is not None else ["thrash metal"]
    t.album_genres = album_genres or []
    t.artist_tags = artist_tags or {}
    return t


# --- classic bonus -----------------------------------------------------------

def test_classic_bonus_favors_older():
    assert classic_bonus(1985, 1970, 2025) > classic_bonus(2021, 1970, 2025)


def test_classic_bonus_unknown_year_is_neutral():
    assert classic_bonus(None, 1970, 2025) == 0.5


def test_classic_bonus_clamped_0_1():
    assert classic_bonus(1960, 1970, 2025) == 1.0   # older than anchor → clamps to 1
    assert classic_bonus(2030, 1970, 2025) == 0.0   # future → clamps to 0


# --- studio always wins ------------------------------------------------------

def test_studio_beats_live_all_else_equal():
    studio = _t("1", version="studio")
    live = _t("2", version="live")
    compute_snapshot_scores([studio, live], base_darkness=0.8, mood_weight=0.3, floor=0.0)
    assert studio.snapshot_score > live.snapshot_score
    # ~4x demotion (nonstudio_factor default 0.25)
    assert live.snapshot_score < 0.4 * studio.snapshot_score + 1e-9


def test_prefer_live_lifts_the_studio_gate():
    studio = _t("1", version="studio")
    live = _t("2", version="live")
    compute_snapshot_scores([studio, live], base_darkness=0.8, mood_weight=0.3,
                            floor=0.0, prefer_live=True)
    assert abs(studio.snapshot_score - live.snapshot_score) < 1e-9


def test_select_artist_prefers_studio_over_live():
    # same artist: a studio classic vs a live version; only 1 slot effectively wins top
    studio = _t("1", album="album", version="studio", banger=0.9, leg=0.8)
    live = _t("2", album="live-at-x", version="live", banger=0.9, leg=0.8)
    compute_snapshot_scores([studio, live], base_darkness=0.8, mood_weight=0.3, floor=0.0)
    picked = select_artist_tracks([studio, live], min_n=1, max_n=1, album_cap=2,
                                  banger_percentile=0.6)
    assert [t.id for t in picked] == ["1"]


# --- Metal Archives legitimacy wins -----------------------------------------

def test_higher_legitimacy_scores_higher():
    legit = _t("1", leg=0.95, banger=0.2)
    mid = _t("2", leg=0.10, banger=0.2)
    compute_snapshot_scores([legit, mid], base_darkness=0.8, mood_weight=0.3, floor=0.0)
    assert legit.snapshot_score > mid.snapshot_score


# --- strict niche (purist) ---------------------------------------------------

def test_carries_target_genre_matches_file_album_or_artist_tags():
    via_file = _t("1", genres=["speed metal"])
    via_album = _t("2", genres=["heavy metal"], album_genres=["speed metal"])
    via_tag = _t("3", genres=["heavy metal"], artist_tags={"speed metal": 80})
    none = _t("4", genres=["heavy metal"], album_genres=["nwobhm"], artist_tags={"rock": 50})
    terms = {"speed metal"}
    assert carries_target_genre(via_file, terms)
    assert carries_target_genre(via_album, terms)
    assert carries_target_genre(via_tag, terms)
    assert not carries_target_genre(none, terms)
