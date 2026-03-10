from pydantic import BaseModel


class GeneratePlaylistRequest(BaseModel):
    prompt: str
    size: int = 30


class Track(BaseModel):
    id: str
    title: str
    artist_name: str
    album_name: str
    year: int | None
    duration_ms: int


class GeneratedPlaylist(BaseModel):
    prompt: str
    title: str
    playlist_size: int
    tracks: list[Track]
    jellyfin_playlist_id: str | None
    partial: bool = False
    warning: str | None = None


class ProgressEvent(BaseModel):
    stage: str
    progress: int
    message: str
    phase: str | None = None
    playlist: GeneratedPlaylist | None = None
    jellyfin_id: str | None = None
    error: str | None = None
