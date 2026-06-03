from app.trajectory.textnorm import normalize_artist, normalize_title


def test_normalize_artist_strips_accents_and_case():
    assert normalize_artist("Voïvod") == normalize_artist("Voivod")
    assert normalize_artist("Motörhead") == "motorhead"
    assert normalize_artist(None) is None


def test_normalize_title_strips_version_qualifiers():
    base = normalize_title("Suck Your Bone")
    assert normalize_title("Suck Your Bone (live)") == base
    assert normalize_title("Suck Your Bone (Radio 1 session)") == base
    assert normalize_title("Stranger (remix)") == normalize_title("Stranger")
    assert normalize_title("Hollow Eyes (single version)") == normalize_title("Hollow Eyes")
    assert normalize_title("A Day (Tibet mix)") == normalize_title("A Day")
    assert normalize_title("Guardian (demo)") == normalize_title("Guardian")
    assert normalize_title("Bela Lugosi's Dead (2008 remaster)") == normalize_title("Bela Lugosi's Dead")


def test_normalize_title_keeps_distinct_songs_distinct():
    assert normalize_title("Guardian") != normalize_title("The Sorceress")


def test_normalize_title_strips_featuring():
    assert normalize_title("Song (feat. Someone)") == normalize_title("Song")
    assert normalize_title("Song feat. Someone") == normalize_title("Song")


def test_normalize_title_untitled_does_not_collapse_to_empty():
    assert normalize_title("[untitled]") != ""
