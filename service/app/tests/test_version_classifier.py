from app.ingestion.version_classifier import classify_version


def test_plain_studio():
    vt, score = classify_version("Paranoid", "Paranoid", [])
    assert vt == "studio"
    assert score == 1.0


def test_live_in_title():
    vt, score = classify_version("War Pigs (Live)", "Paranoid", [])
    assert vt == "live"
    assert score < 0.5


def test_live_at():
    vt, _ = classify_version("Children of the Grave - Live at Last", "Live at Last", [])
    assert vt == "live"


def test_demo():
    vt, score = classify_version("Snowblind (Demo)", "The Vol 4 Sessions", [])
    assert vt == "demo"
    assert score < 0.6


def test_bonus_and_alternate():
    assert classify_version("Track X (Bonus Track)", "Album", [])[0] == "bonus"
    assert classify_version("Track X (Alternate Take)", "Album", [])[0] == "alternate"


def test_acoustic_and_remix():
    assert classify_version("Track (Acoustic Version)", "Album", [])[0] == "acoustic"
    assert classify_version("Track (Club Remix)", "Album", [])[0] == "remix"


def test_mb_secondary_type_live():
    vt, score = classify_version("Some Song", "Some Album", ["Live"])
    assert vt == "live"


def test_clean_title_with_parenthetical_non_version():
    # parentheticals that are not version markers stay studio
    vt, score = classify_version("Hello (feat. Friend)", "Album", [])
    assert vt == "studio"
    assert score == 1.0
