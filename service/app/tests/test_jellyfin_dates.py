"""Tests for jellyfin_dates pure helpers and ledger logic."""

from xml.etree import ElementTree as ET

from app.ingestion.jellyfin_dates import (
    build_album_nfo,
    choose_album_for_folder,
    effective_year,
    folder_album_name,
    folder_year,
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


# ---------------------------------------------------------------------------
# folder_album_name
# ---------------------------------------------------------------------------


def test_folder_album_name_year_dash_prefix():
    assert folder_album_name("1990 - Painkiller") == "painkiller"


def test_folder_album_name_year_space_prefix():
    assert folder_album_name("1990 Painkiller") == "painkiller"


def test_folder_album_name_no_prefix():
    assert folder_album_name("Painkiller") == "painkiller"


def test_folder_album_name_nn_dash_prefix():
    assert folder_album_name("01 - Holy Diver") == "holy diver"


def test_folder_album_name_remaster_suffix_stripped_by_normalize():
    # normalize_title drops trailing "(Remastered)" — so the result is "painkiller"
    assert folder_album_name("2010 - Painkiller (Remastered)") == "painkiller"


def test_folder_album_name_four_digit_year_only():
    # "2001 - " prefix stripped leaving just the album name
    assert folder_album_name("2001 - Songs of Experience") == "songs of experience"


# ---------------------------------------------------------------------------
# choose_album_for_folder
# ---------------------------------------------------------------------------

# Shared helpers for these tests
_PAINKILLER = {"album_id": "p", "title": "Painkiller", "year": 1990}
_ORIG_CLASSICS = {"album_id": "c", "title": "Original Album Classics", "year": 1983}
_METAL_WORKS = {"album_id": "mw", "title": "Metal Works '73-'93", "year": 1993}


def test_choose_album_painkiller_wins_over_compilation():
    """THE core regression: Painkiller folder should pick Painkiller 1990."""
    candidates = [_PAINKILLER, _ORIG_CLASSICS]
    result = choose_album_for_folder(candidates, "1990 - Painkiller")
    assert result is not None
    assert result["album_id"] == "p"
    assert result["year"] == 1990


def test_choose_album_no_title_match_returns_none():
    """No candidate title matches the folder → ambiguous → None."""
    candidates = [_ORIG_CLASSICS, _METAL_WORKS]
    result = choose_album_for_folder(candidates, "1990 - Painkiller")
    assert result is None


def test_choose_album_conflicting_years_returns_none():
    """Two distinct albums with different years match the folder → ambiguous."""
    painkiller_alt = {"album_id": "p2", "title": "Painkiller", "year": 2001}
    candidates = [_PAINKILLER, painkiller_alt]
    result = choose_album_for_folder(candidates, "1990 - Painkiller")
    assert result is None


def test_choose_album_same_year_duplicates_returns_one():
    """Two entries for the same album (same year) → any is acceptable."""
    dup = {"album_id": "p_dup", "title": "Painkiller", "year": 1990}
    candidates = [_PAINKILLER, dup]
    result = choose_album_for_folder(candidates, "1990 - Painkiller")
    assert result is not None
    assert result["year"] == 1990


def test_choose_album_single_candidate_match():
    """Only one candidate and its title matches → return it."""
    result = choose_album_for_folder([_PAINKILLER], "1990 - Painkiller")
    assert result is not None
    assert result["album_id"] == "p"


def test_choose_album_no_candidates():
    result = choose_album_for_folder([], "1990 - Painkiller")
    assert result is None


def test_choose_album_remaster_folder_matches_original():
    """Folder 'Painkiller (Remastered)' → normalize_title → 'painkiller' → matches."""
    result = choose_album_for_folder([_PAINKILLER], "2010 - Painkiller (Remastered)")
    assert result is not None
    assert result["album_id"] == "p"


def test_choose_album_no_prefix_folder():
    """Folder without year prefix still matches by title."""
    result = choose_album_for_folder([_PAINKILLER, _ORIG_CLASSICS], "Painkiller")
    assert result is not None
    assert result["album_id"] == "p"


def test_choose_album_none_year_not_conflicting():
    """An album with year=None does not conflict with a resolved-year album."""
    none_year = {"album_id": "p_none", "title": "Painkiller", "year": None}
    result = choose_album_for_folder([_PAINKILLER, none_year], "1990 - Painkiller")
    # Both match; none_year doesn't conflict → first (by dedup order) is returned.
    assert result is not None
    assert result["year"] in (1990, None)


# ---------------------------------------------------------------------------
# folder_year
# ---------------------------------------------------------------------------


def test_folder_year_typical():
    assert folder_year("1988 - South of Heaven") == 1988


def test_folder_year_no_separator():
    assert folder_year("2026 Album Name") == 2026


def test_folder_year_no_year():
    assert folder_year("Greatest Hits") is None


def test_folder_year_too_short():
    assert folder_year("1") is None


def test_folder_year_out_of_range_low():
    assert folder_year("0001 - Garbage Tag") is None


def test_folder_year_out_of_range_high():
    assert folder_year("2200 - Future") is None


def test_folder_year_boundary_1900():
    assert folder_year("1900 - First") == 1900


def test_folder_year_boundary_2100():
    assert folder_year("2100 - Last") == 2100


def test_folder_year_leading_whitespace():
    # The regex allows optional leading whitespace in the basename.
    assert folder_year("  1988 - South of Heaven") == 1988


# ---------------------------------------------------------------------------
# effective_year  (folder-first priority since curated folder names are authoritative)
# ---------------------------------------------------------------------------


def test_effective_year_folder_wins_over_file_metadata():
    """file_metadata reissue tag must never win; folder year is authoritative."""
    # Vol 4 folder says 1972; embedded tag says 2021 (reissue rip)
    assert effective_year(2021, "file_metadata", "1972 - Vol 4") == (1972, "folder")


def test_effective_year_folder_wins_over_discogs_reissue():
    """Discogs sometimes matches a reissue master; folder year still wins."""
    # Never Say Die! folder says 1978; Discogs resolved 1996 (reissue)
    assert effective_year(1996, "discogs", "1978 - Never Say Die!") == (1978, "folder")


def test_effective_year_folder_wins_when_no_resolved():
    """No resolved year → folder fallback."""
    assert effective_year(None, None, "1988 - South of Heaven") == (1988, "folder")


def test_effective_year_folder_wins_even_if_bogus_resolved():
    """resolved_year < 1900 → folder fallback (folder year present)."""
    assert effective_year(1, "file_metadata", "1988 - South of Heaven") == (1988, "folder")


def test_effective_year_discogs_fallback_no_folder_year():
    """No folder year, discogs source → resolved year trusted."""
    # Heaven and Hell has no year prefix in folder; Discogs gives 1980
    assert effective_year(1980, "discogs", "Heaven and Hell") == (1980, "resolved")


def test_effective_year_musicbrainz_fallback_no_folder_year():
    """No folder year, musicbrainz source → resolved year trusted."""
    assert effective_year(1975, "musicbrainz", "Sabotage") == (1975, "resolved")


def test_effective_year_file_metadata_no_folder_year():
    """No folder year + file_metadata source → never trust the tag → (None, 'none')."""
    # Sabbath Bloody Sabbath folder has no year prefix; embedded tag says 2004 (reissue)
    assert effective_year(2004, "file_metadata", "Some Comp") == (None, "none")


def test_effective_year_none_resolved_no_folder_year():
    """No resolved year and no parseable folder year → (None, 'none')."""
    assert effective_year(None, None, "Greatest Hits") == (None, "none")


def test_effective_year_none_source_no_folder_year():
    """source=None (no album_release_dates row) + no folder year → (None, 'none')."""
    assert effective_year(None, None, "Greatest Hits") == (None, "none")


def test_effective_year_resolved_exactly_1900_no_folder():
    """Boundary: 1900 is a valid resolved year for discogs source."""
    assert effective_year(1900, "discogs", "Greatest Hits") == (1900, "resolved")


def test_effective_year_folder_present_no_resolved():
    """Folder year present, resolved=None → folder wins."""
    assert effective_year(None, None, "1988 - South of Heaven") == (1988, "folder")


def test_effective_year_bogus_resolved_no_folder_year():
    """Bogus resolved year (< 1900) + no folder year → (None, 'none')."""
    assert effective_year(1, "discogs", "Greatest Hits") == (None, "none")
