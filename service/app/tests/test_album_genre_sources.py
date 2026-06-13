"""Pure-parser tests for P2 album-genre source extraction."""
import asyncio

from bs4 import BeautifulSoup

from app.ingestion.metal_archives import parse_ma_genre, split_ma_genres
from app.ingestion.musicbrainz import parse_mb_genres

# --- MusicBrainz release-group genre parse -----------------------------------

def test_parse_mb_genres_with_counts():
    resp = {
        "release-group": {
            "genre-list": [
                {"name": "Black Metal", "count": "5"},
                {"name": "Ambient"},  # no count
            ]
        }
    }
    out = parse_mb_genres(resp)
    by = {g["name"]: g["weight"] for g in out}
    assert by["Black Metal"] == 5.0
    assert by["Ambient"] is None


def test_parse_mb_genres_empty_and_malformed():
    assert parse_mb_genres({}) == []
    assert parse_mb_genres(None) == []
    assert parse_mb_genres({"release-group": {}}) == []
    # entry with no name is skipped
    assert parse_mb_genres({"release-group": {"genre-list": [{"count": "3"}]}}) == []


# --- Metal Archives genre string split ---------------------------------------

def test_split_ma_genres_strips_era_annotations():
    assert split_ma_genres("Death/Doom Metal (early), Gothic Metal (later)") == [
        "death/doom metal",
        "gothic metal",
    ]


def test_split_ma_genres_single_and_empty():
    assert split_ma_genres("Thrash Metal") == ["thrash metal"]
    assert split_ma_genres("") == []
    assert split_ma_genres("   ") == []


# --- Metal Archives page genre extraction ------------------------------------

def test_parse_ma_genre_present():
    html = "<dl><dt>Genre:</dt><dd>Thrash Metal</dd><dt>Year:</dt><dd>1986</dd></dl>"
    soup = BeautifulSoup(html, "html.parser")
    assert parse_ma_genre(soup) == "Thrash Metal"


def test_parse_ma_genre_absent_no_raise():
    soup = BeautifulSoup("<dl><dt>Year:</dt><dd>1986</dd></dl>", "html.parser")
    assert parse_ma_genre(soup) is None


# --- Last.fm album tag fetch (monkeypatched network) -------------------------

def test_fetch_album_tags_monkeypatched(monkeypatch):
    from app.ingestion import lastfm

    class _FakeItem:
        def __init__(self, name):
            self.name = name

    class _FakeTag:
        def __init__(self, name, weight):
            self.item = _FakeItem(name)
            self.weight = weight

    class _FakeAlbum:
        def get_top_tags(self, limit=10):
            return [_FakeTag("Shoegaze", 100), _FakeTag("Dream Pop", 80)]

    class _FakeNetwork:
        def get_album(self, artist, album):
            return _FakeAlbum()

    tags = asyncio.run(lastfm.fetch_album_tags(_FakeNetwork(), "Slowdive", "Souvlaki"))
    by = {t["name"]: t["weight"] for t in tags}
    assert by == {"shoegaze": 100, "dream pop": 80}
