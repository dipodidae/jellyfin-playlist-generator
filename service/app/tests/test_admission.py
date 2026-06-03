from app.trajectory.admission import is_admissible


def _kw(**over):
    base = dict(
        semantic_score=0.5, semantic_floor=0.2,
        genre_match_score=0.0, admissibility_score=0.5,
        admissibility_floor=0.35, negative_constraint_penalty=0.0,
        neg_constraint_ceiling=0.45, has_genre_hints=True,
    )
    base.update(over)
    return base


def test_clears_semantic_floor():
    assert is_admissible(**_kw(semantic_score=0.5)) is True


def test_below_floor_but_strong_genre_is_admitted():
    # This is the coldwave fix: genre-pool tracks carry semantic_score=0.15.
    assert is_admissible(**_kw(semantic_score=0.15, genre_match_score=0.6)) is True


def test_below_floor_weak_genre_rejected():
    assert is_admissible(**_kw(semantic_score=0.15, genre_match_score=0.2)) is False


def test_strong_genre_ignored_when_no_hints():
    assert is_admissible(**_kw(semantic_score=0.15, genre_match_score=0.9,
                               has_genre_hints=False)) is False


def test_admissibility_floor_gates_everything():
    assert is_admissible(**_kw(admissibility_score=0.1)) is False


def test_negative_constraint_ceiling_gates_everything():
    assert is_admissible(**_kw(negative_constraint_penalty=0.5)) is False
