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


def test_normalize_title_strips_dash_delimited_versions():
    base = normalize_title("Tormentor")
    assert normalize_title("Tormentor - Live") == base
    assert normalize_title("Tormentor - 2017 Remaster") == base
    assert normalize_title("Tormentor - Remastered 2017") == base
    assert normalize_title("Tormentor: Live at Wacken") == base
    assert normalize_title("Tormentor - 2017") == base


def test_normalize_title_strips_apostrophe_year():
    assert normalize_title("Tormentor '88") == normalize_title("Tormentor")


def test_normalize_title_strips_extra_parenthetical_versions():
    base = normalize_title("Tormentor")
    assert normalize_title("Tormentor (Orchestral)") == base
    assert normalize_title("Tormentor (Anniversary Edition)") == base
    assert normalize_title("Tormentor (Deluxe)") == base


def test_normalize_title_does_not_overcollapse_distinct_songs():
    # Sequels / parts / non-version dash suffixes must stay distinct.
    assert normalize_title("Tormentor (Part II)") != normalize_title("Tormentor")
    assert normalize_title("Heartwork - Part 1") != normalize_title("Heartwork")
    assert normalize_title("Damage: Inc.") != normalize_title("Damage")
