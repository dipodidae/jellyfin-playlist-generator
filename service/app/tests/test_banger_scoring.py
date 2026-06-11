from app.enrichment.banger_scoring import (
    tempo_score, energy_proxy, is_dark_genre, sonic_score,
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


def test_sonic_all_max():
    # energy=dance=loud=tempo(110)=valence=1.0 -> 1.0
    s = sonic_score(energy=1.0, danceability=1.0, loudness_norm=1.0,
                    bpm=110, valence=1.0, dark=False)
    assert round(s, 4) == 1.0


def test_sonic_weights_sum_correctly():
    # only energy=1.0, everything else 0, valence=0 -> 0.30
    s = sonic_score(energy=1.0, danceability=0.0, loudness_norm=0.0,
                    bpm=0, valence=0.0, dark=False)
    assert round(s, 3) == 0.30


def test_sonic_dark_drops_valence_no_penalty():
    # Dark track, low valence: valence term removed, other 4 reweighted to sum 1.
    # energy=1, dance=1, loud=1, tempo(110)=1, valence=0
    light = sonic_score(1.0, 1.0, 1.0, 110, valence=0.0, dark=False)
    dark = sonic_score(1.0, 1.0, 1.0, 110, valence=0.0, dark=True)
    # Light track loses the 0.10 valence contribution (valence=0) -> 0.90
    assert round(light, 3) == 0.90
    # Dark track redistributes -> the four maxed terms give full 1.0
    assert round(dark, 3) == 1.0
