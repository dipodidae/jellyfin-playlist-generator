"""Tests for jellyfin_dates pure helpers and ledger logic."""

from xml.etree import ElementTree as ET

from app.ingestion.jellyfin_dates import (
    build_album_nfo,
    iso_date,
    nfo_is_current,
    partition_by_ledger,
)


# ---------------------------------------------------------------------------
# iso_date
# ---------------------------------------------------------------------------


def test_iso_date_year_only():
    assert iso_date(1990, None, None) == "1990-01-01"


def test_iso_date_full():
    assert iso_date(1983, 5, 25) == "1983-05-25"


def test_iso_date_month_only():
    assert iso_date(2001, 3, None) == "2001-03-01"


def test_iso_date_zero_pads():
    assert iso_date(999, 1, 2) == "0999-01-02"


# ---------------------------------------------------------------------------
# build_album_nfo — create from scratch
# ---------------------------------------------------------------------------


def test_build_album_nfo_creates_from_none():
    nfo = build_album_nfo(None, "Holy Diver", 1983, 5, 25)
    assert nfo.startswith("<?xml version")
    root = ET.fromstring(nfo.split("\n", 1)[1])
    assert root.tag == "album"
    assert root.find("year").text == "1983"
    assert root.find("premiered").text == "1983-05-25"
    assert root.find("releasedate").text == "1983-05-25"
    assert root.find("lockdata").text == "true"
    assert root.find("title").text == "Holy Diver"


def test_build_album_nfo_year_only_date():
    nfo = build_album_nfo(None, "Album", 2000, None, None)
    root = ET.fromstring(nfo.split("\n", 1)[1])
    assert root.find("year").text == "2000"
    assert root.find("premiered").text == "2000-01-01"


# ---------------------------------------------------------------------------
# build_album_nfo — merge / update existing
# ---------------------------------------------------------------------------


def test_build_album_nfo_preserves_non_date_elements():
    existing = (
        '<?xml version="1.0"?>\n'
        "<album>"
        "<title>Old Title</title>"
        "<plot>Some description</plot>"
        "<year>1990</year>"
        "</album>"
    )
    nfo = build_album_nfo(existing, "New Title", 1983, None, None)
    root = ET.fromstring(nfo.split("\n", 1)[1])
    assert root.find("plot").text == "Some description"
    # <title> from existing is preserved (no new title added because title exists)
    assert root.find("title").text == "Old Title"
    assert root.find("year").text == "1983"
    assert root.find("lockdata").text == "true"


def test_build_album_nfo_drops_musicbrainz_elements():
    existing = (
        '<?xml version="1.0"?>\n'
        "<album>"
        "<title>Filosofem</title>"
        "<musicbrainzalbumid>abc-123</musicbrainzalbumid>"
        "<MusicBrainzAlbumArtistId>xyz</MusicBrainzAlbumArtistId>"
        "<year>1996</year>"
        "</album>"
    )
    nfo = build_album_nfo(existing, "Filosofem", 1996, 1, 1)
    root = ET.fromstring(nfo.split("\n", 1)[1])
    tags = [el.tag for el in root]
    assert not any(t.lower().startswith("musicbrainz") for t in tags), (
        f"musicbrainz elements not stripped: {tags}"
    )


def test_build_album_nfo_overwrites_existing_year():
    existing = (
        '<?xml version="1.0"?>\n'
        "<album>"
        "<title>Album</title>"
        "<year>2010</year>"
        "<premiered>2010-01-01</premiered>"
        "<releasedate>2010-01-01</releasedate>"
        "<lockdata>false</lockdata>"
        "</album>"
    )
    nfo = build_album_nfo(existing, "Album", 1983, None, None)
    root = ET.fromstring(nfo.split("\n", 1)[1])
    assert root.find("year").text == "1983"
    assert root.find("lockdata").text == "true"
    # Only one <year> element should be present
    assert len(root.findall("year")) == 1


def test_build_album_nfo_handles_malformed_xml():
    nfo = build_album_nfo("not valid xml <<<", "Album", 2000, None, None)
    root = ET.fromstring(nfo.split("\n", 1)[1])
    assert root.find("year").text == "2000"
    assert root.find("lockdata").text == "true"


def test_build_album_nfo_adds_title_when_missing():
    existing = (
        '<?xml version="1.0"?>\n'
        "<album><plot>desc</plot></album>"
    )
    nfo = build_album_nfo(existing, "My Album", 2005, None, None)
    root = ET.fromstring(nfo.split("\n", 1)[1])
    assert root.find("title").text == "My Album"


# ---------------------------------------------------------------------------
# nfo_is_current
# ---------------------------------------------------------------------------


def test_nfo_is_current_returns_true_when_correct():
    nfo = (
        '<album>'
        '<year>1983</year>'
        '<lockdata>true</lockdata>'
        '</album>'
    )
    assert nfo_is_current(nfo, 1983) is True


def test_nfo_is_current_wrong_year():
    nfo = '<album><year>1990</year><lockdata>true</lockdata></album>'
    assert nfo_is_current(nfo, 1983) is False


def test_nfo_is_current_missing_lockdata():
    nfo = '<album><year>1983</year></album>'
    assert nfo_is_current(nfo, 1983) is False


def test_nfo_is_current_lockdata_false():
    nfo = '<album><year>1983</year><lockdata>false</lockdata></album>'
    assert nfo_is_current(nfo, 1983) is False


def test_nfo_is_current_lockdata_case_insensitive():
    nfo = '<album><year>1983</year><lockdata>True</lockdata></album>'
    assert nfo_is_current(nfo, 1983) is True


def test_nfo_is_current_missing_year():
    nfo = '<album><lockdata>true</lockdata></album>'
    assert nfo_is_current(nfo, 1983) is False


def test_nfo_is_current_malformed_xml():
    assert nfo_is_current("not xml", 1983) is False


# ---------------------------------------------------------------------------
# partition_by_ledger
# ---------------------------------------------------------------------------


def test_partition_by_ledger_skips_already_applied():
    albums = [
        {"album_id": "A1", "year": 1990},   # already applied at 1990 -> skip
        {"album_id": "A2", "year": 1983},   # applied at 1979 (changed) -> process
        {"album_id": "A3", "year": 2001},   # never applied -> process
    ]
    ledger = {"A1": 1990, "A2": 1979}
    to_process, skipped = partition_by_ledger(albums, ledger)
    assert skipped == 1
    assert [a["album_id"] for a in to_process] == ["A2", "A3"]


def test_partition_by_ledger_force_processes_all():
    albums = [{"album_id": "A1", "year": 1990}]
    to_process, skipped = partition_by_ledger(albums, {"A1": 1990}, force=True)
    assert skipped == 0 and len(to_process) == 1


def test_partition_by_ledger_empty_ledger():
    albums = [{"album_id": "A1", "year": 1990}, {"album_id": "A2", "year": 2000}]
    to_process, skipped = partition_by_ledger(albums, {})
    assert skipped == 0
    assert len(to_process) == 2
