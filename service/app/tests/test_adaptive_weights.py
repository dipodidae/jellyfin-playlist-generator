"""PARSE_AUDIT P7 — confidence-driven adaptive weights."""
from app.trajectory.candidates import get_adaptive_weights
from app.trajectory.intent import ArcType, PlaylistIntent


def _intent(**kw):
    base = dict(raw_prompt="x", prompt_embedding=[])
    base.update(kw)
    return PlaylistIntent(**base)


def test_weights_sum_to_one():
    for intent in (
        _intent(genre_hints=["thrash metal"], genre_confidence=1.0, arc_type=ArcType.STEADY),
        _intent(arc_type=ArcType.RISE, arc_confidence=0.9),
        _intent(),
    ):
        w = get_adaptive_weights(intent)
        assert abs(sum(w.values()) - 1.0) < 1e-6


def test_confident_genre_leans_genre():
    genre = get_adaptive_weights(
        _intent(genre_hints=["thrash metal"], genre_confidence=1.0, arc_type=ArcType.STEADY)
    )
    arc = get_adaptive_weights(_intent(arc_type=ArcType.RISE, arc_confidence=0.9))
    # Genre-confident prompt weights genre + semantic above trajectory.
    assert genre["genre"] > arc["genre"]
    assert arc["trajectory"] > genre["trajectory"]


def test_low_confidence_genre_softens_genre_weight():
    high = get_adaptive_weights(
        _intent(genre_hints=["thrash metal"], genre_confidence=1.0, arc_type=ArcType.STEADY)
    )
    low = get_adaptive_weights(
        _intent(genre_hints=["thrash metal"], genre_confidence=0.4, arc_type=ArcType.STEADY)
    )
    # A snapped / low-confidence genre trusts genre matching less.
    assert low["genre"] < high["genre"]


def test_no_signal_is_balanced():
    w = get_adaptive_weights(_intent())
    # Falls back to the MIXED endpoint when nothing is detected.
    assert abs(w["trajectory"] - 0.26) < 1e-6
    assert abs(w["semantic"] - 0.28) < 1e-6
