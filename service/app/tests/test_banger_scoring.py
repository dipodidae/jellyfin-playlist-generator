from app.enrichment.banger_scoring import (
    tempo_score, energy_proxy, is_dark_genre,
)


def test_tempo_peak_zone():
    assert tempo_score(90) == 1.0
    assert tempo_score(110) == 1.0
    assert tempo_score(130) == 1.0


def test_tempo_falloff_low():
    assert tempo_score(70) == 0.0
    assert tempo_score(80) == 0.5      # halfway between 70 and 90
    assert tempo_score(None) == 0.0
    assert tempo_score(0) == 0.0


def test_tempo_falloff_high():
    assert tempo_score(180) == 0.0
    assert tempo_score(155) == 0.5     # halfway between 130 and 180
    assert tempo_score(200) == 0.0


def test_energy_proxy_blend():
    # 0.5*ln + 0.3*orn + 0.2*pc
    assert energy_proxy(1.0, 1.0, 1.0) == 1.0
    assert energy_proxy(0.0, 0.0, 0.0) == 0.0
    assert round(energy_proxy(1.0, 0.0, 0.0), 3) == 0.5
    # None inputs treated as 0
    assert round(energy_proxy(1.0, None, None), 3) == 0.5


def test_is_dark_genre():
    assert is_dark_genre(["Doom Metal", "Sludge"]) is True
    assert is_dark_genre(["Industrial"]) is True
    assert is_dark_genre(["Darkwave"]) is True
    assert is_dark_genre(["Synthpop", "Dream Pop"]) is False
    assert is_dark_genre([]) is False
