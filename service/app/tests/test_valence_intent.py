from app.trajectory.intent import detect_prefer_live, parse_valence_target


def test_uplifting_is_high():
    assert parse_valence_target("uplifting euphoric summer anthems") >= 0.75


def test_melancholic_is_low():
    assert parse_valence_target("bleak melancholic doom") <= 0.25


def test_neutral_default():
    assert parse_valence_target("instrumental focus music") == 0.5


def test_prefer_live_detected():
    assert detect_prefer_live("the best live concert recordings") is True
    assert detect_prefer_live("acoustic unplugged sessions") is True


def test_prefer_live_default_false():
    assert detect_prefer_live("dark ambient studio focus") is False
