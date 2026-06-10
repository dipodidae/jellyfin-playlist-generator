from app.ingestion.jellyfin_dates import (
    translate_path,
    build_premiere_date,
    resolve_album_id_map,
    match_by_name,
)


def test_translate_path_swaps_prefix():
    assert translate_path("/music/Dio/Holy Diver/01.mp3", "/music", "/data/movies/music") \
        == "/data/movies/music/Dio/Holy Diver/01.mp3"


def test_translate_path_trailing_slashes():
    assert translate_path("/music/A/b.mp3", "/music/", "/data/movies/music/") \
        == "/data/movies/music/A/b.mp3"


def test_translate_path_non_prefixed_passthrough():
    assert translate_path("/other/x.mp3", "/music", "/data/movies/music") == "/other/x.mp3"


def test_build_premiere_date_year_only():
    assert build_premiere_date(1983, None, None, "year") == "1983-01-01T00:00:00.0000000Z"


def test_build_premiere_date_full():
    assert build_premiere_date(1983, 5, 25, "day") == "1983-05-25T00:00:00.0000000Z"


def test_build_premiere_date_month_precision():
    assert build_premiere_date(1990, 7, None, "month") == "1990-07-01T00:00:00.0000000Z"


def test_resolve_album_id_map_path_hit():
    app_albums = [
        {"album_id": "A1", "track_paths": ["/music/Dio/Holy Diver/01.mp3"]},
        {"album_id": "A2", "track_paths": ["/music/Nope/x.mp3"]},
    ]
    audio_items = [
        {"Id": "t1", "AlbumId": "JF-ALB-1", "Path": "/data/movies/music/Dio/Holy Diver/01.mp3"},
    ]
    mapping, unresolved = resolve_album_id_map(app_albums, audio_items, "/music", "/data/movies/music")
    assert mapping == {"A1": "JF-ALB-1"}
    assert unresolved == ["A2"]


def test_resolve_album_id_map_multiple_tracks_one_hits():
    app_albums = [{"album_id": "A1", "track_paths": ["/music/x/missing.mp3", "/music/x/found.mp3"]}]
    audio_items = [{"Id": "t", "AlbumId": "JF9", "Path": "/data/movies/music/x/found.mp3"}]
    mapping, unresolved = resolve_album_id_map(app_albums, audio_items, "/music", "/data/movies/music")
    assert mapping == {"A1": "JF9"}
    assert unresolved == []


def test_match_by_name_normalized():
    jf_albums = [{"Id": "JF1", "Name": "Holy Diver", "AlbumArtist": "Dio"}]
    assert match_by_name("holy  diver", "DIO", jf_albums) == "JF1"
    assert match_by_name("Unknown", "Dio", jf_albums) is None
