from app.trajectory.intent import parse_valence_target


def test_uplifting_is_high():
    assert parse_valence_target("uplifting euphoric summer anthems") >= 0.75


def test_melancholic_is_low():
    assert parse_valence_target("bleak melancholic doom") <= 0.25


def test_neutral_default():
    assert parse_valence_target("instrumental focus music") == 0.5
