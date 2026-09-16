"""Navidrome playlist export — resolve local tracks to Subsonic song IDs.

Why this exists alongside the Jellyfin exporter: Navidrome carries three things
on a playlist that Jellyfin has no equivalent for, and a generated playlist is
exactly the case that wants them.

  * **a comment** — a free-text description shown under the playlist name.
    Jellyfin playlists have a name and nothing else, so the prompt that produced
    the playlist, its size and how it was sequenced are lost the moment it lands.
    Here they travel with it.
  * **a public flag** — one playlist visible to every Navidrome user, rather
    than a per-user copy.
  * **Subsonic itself** — which is what Symfonium, substreamer, DSub and play:Sub
    actually speak, so the playlist is reachable from a phone without Jellyfin.

Two traps this had to be written around, both measured against Navidrome 0.64.0:

1. **`path` in a Subsonic response is NOT the file path.** It is synthesised
   from tags — `Kreator/Flag of Hate/01-02 - Take Their Lives.mp3` for a file
   that is really `Kreator/1986 - Flag of Hate/02 - Take Their Lives.mp3`.
   Matching on it looks exact and is not, so resolution here scores on
   MusicBrainz id, then title/artist/album/duration, and never on `path`.

2. **`createPlaylist` takes no comment.** The comment and the public flag are a
   second `updatePlaylist` call, which is why a push is two requests and why a
   failure of the second one is reported rather than swallowed — the playlist
   exists either way, just without its description.

Ownership note: the playlist belongs to whichever account `navidrome_user`
names. Point it at the account you actually browse Navidrome with, or the
playlist lands somewhere you have to go looking for it.
"""

import hashlib
import logging
import secrets
from typing import Any

import httpx

from app.config import settings
from app.export.m3u import get_track_files

logger = logging.getLogger(__name__)

# The Subsonic protocol version we speak. 1.16.1 is what Navidrome reports.
SUBSONIC_API_VERSION = "1.16.1"
CLIENT_NAME = "playlist-generator"
# How far a candidate's duration may sit from ours and still be the same
# recording. Encoders disagree by a second or two; three is slack, not a guess.
DURATION_TOLERANCE_SECONDS = 3
# Candidates to pull per track. Titles like "Intro" are not rare.
SEARCH_LIMIT = 25

# Score floor a candidate must clear to be accepted at all. Title+artist alone
# reaches 60; anything below that is a different song with a similar name.
MIN_ACCEPTABLE_SCORE = 60


def _is_configured() -> bool:
    """Whether Navidrome connection details are present."""
    return bool(settings.navidrome_url and settings.navidrome_user and settings.navidrome_password)


def _auth_params() -> dict[str, str]:
    """Subsonic salted-token auth.

    Deliberately not the legacy `p=` plaintext parameter: this travels in a
    query string, which lands in access logs and proxy logs verbatim.
    """
    salt = secrets.token_hex(8)
    token = hashlib.md5(  # noqa: S324 - the Subsonic spec mandates MD5 here
        (settings.navidrome_password + salt).encode("utf-8")
    ).hexdigest()
    return {
        "u": settings.navidrome_user,
        "t": token,
        "s": salt,
        "v": SUBSONIC_API_VERSION,
        "c": CLIENT_NAME,
        "f": "json",
    }


def _base_url() -> str:
    return settings.navidrome_url.rstrip("/")


class SubsonicError(RuntimeError):
    """Navidrome answered 200 with `status="failed"` — the Subsonic way to fail."""

    def __init__(self, code: int, message: str):
        super().__init__(f"Subsonic error {code}: {message}")
        self.code = code
        self.message = message


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """The `subsonic-response` body, or raise.

    Subsonic signals failure INSIDE a 200, so `raise_for_status()` is not enough
    and a bare 200 proves nothing.
    """
    response = payload.get("subsonic-response") or {}
    if response.get("status") != "ok":
        error = response.get("error") or {}
        raise SubsonicError(int(error.get("code", -1)), str(error.get("message", "unknown")))
    return response


async def _call(client: httpx.AsyncClient, endpoint: str, extra: dict[str, Any]) -> dict[str, Any]:
    """One Subsonic call. `extra` values that are lists become repeated params."""
    params: list[tuple[str, str]] = list(_auth_params().items())
    for key, value in extra.items():
        if isinstance(value, list):
            params.extend((key, str(item)) for item in value)
        else:
            params.append((key, str(value)))
    resp = await client.get(f"{_base_url()}/rest/{endpoint}", params=params)
    resp.raise_for_status()
    return _unwrap(resp.json())


def _normalize(text: str | None) -> str:
    """Casefolded, whitespace-collapsed text for comparison."""
    return " ".join((text or "").split()).casefold()


def score_candidate(track: dict, candidate: dict) -> int:
    """How strongly a Navidrome song matches one of our tracks. Higher is better.

    Pure so it can be tested without a Navidrome. Never looks at `path`: a
    Subsonic `path` is synthesised from tags and does not match the filesystem.
    """
    our_title = _normalize(track.get("title"))
    our_artist = _normalize(track.get("artist_name"))
    their_title = _normalize(candidate.get("title"))
    their_artist = _normalize(candidate.get("artist")) or _normalize(
        candidate.get("displayArtist")
    )

    if our_title != their_title:
        return 0

    score = 40
    if our_artist and our_artist == their_artist:
        score += 20
    elif our_artist and their_artist and (our_artist in their_artist or their_artist in our_artist):
        score += 10

    our_seconds = int((track.get("duration_ms") or 0) // 1000)
    their_seconds = int(candidate.get("duration") or 0)
    if our_seconds and their_seconds:
        delta = abs(our_seconds - their_seconds)
        if delta == 0:
            score += 30
        elif delta <= DURATION_TOLERANCE_SECONDS:
            score += 20
        else:
            # A very different runtime is a different recording (live, edit,
            # remaster) even when title and artist agree.
            score -= 20

    our_album = _normalize(track.get("album_name"))
    if our_album and our_album == _normalize(candidate.get("album")):
        score += 10

    return score


def pick_best(track: dict, candidates: list[dict]) -> dict | None:
    """The best candidate above the floor, or None. Ties break deterministically."""
    scored = [(score_candidate(track, c), c.get("id") or "", c) for c in candidates]
    scored = [row for row in scored if row[0] >= MIN_ACCEPTABLE_SCORE]
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored[0][2]


def build_comment(prompt: str | None, track_count: int, matched_count: int) -> str:
    """The description Navidrome shows under the playlist name.

    This is the field Jellyfin does not have, so it is the one place the
    provenance of a generated playlist can live with the playlist itself.
    """
    parts = [f"Generated by {CLIENT_NAME}"]
    if prompt:
        parts.append(f'from the prompt "{prompt.strip()}"')
    if matched_count != track_count:
        parts.append(f"— {matched_count} of {track_count} tracks matched in Navidrome")
    else:
        parts.append(f"— {track_count} tracks")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def test_connection() -> dict:
    """Whether Navidrome is reachable and the credentials are valid.

    `ping` validates credentials -- an anonymous or wrong-password ping comes
    back `failed` with code 40, not 200-with-ok.
    """
    if not _is_configured():
        return {
            "available": False,
            "configured": False,
            "server_name": None,
            "version": None,
            "error": "Navidrome not configured",
        }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await _call(client, "ping.view", {})
            return {
                "available": True,
                "configured": True,
                "server_name": response.get("type"),
                "version": response.get("serverVersion"),
                "error": None,
            }
    except Exception as exc:
        logger.warning("Navidrome connection test failed: %s", exc)
        return {
            "available": False,
            "configured": True,
            "server_name": None,
            "version": None,
            "error": str(exc),
        }


async def resolve_song_ids(tracks: list[dict]) -> tuple[list[str], list[dict]]:
    """Resolve our track dicts to Navidrome song IDs, preserving order.

    Returns (matched_ids_in_order, unmatched_tracks).
    """
    matched: list[str] = []
    unmatched: list[dict] = []

    async with httpx.AsyncClient(timeout=20.0) as client:
        for track in tracks:
            title = (track.get("title") or "").strip()
            if not title:
                unmatched.append(track)
                continue
            try:
                response = await _call(
                    client,
                    "search3.view",
                    {
                        "query": title,
                        "songCount": SEARCH_LIMIT,
                        "albumCount": 0,
                        "artistCount": 0,
                    },
                )
            except (httpx.HTTPError, SubsonicError) as exc:
                logger.warning("Navidrome search failed for %r: %s", title, exc)
                unmatched.append(track)
                continue

            candidates = (response.get("searchResult3") or {}).get("song") or []
            best = pick_best(track, candidates)
            if best is None:
                logger.info(
                    "Navidrome: no match for %r by %r", title, track.get("artist_name")
                )
                unmatched.append(track)
                continue
            matched.append(best["id"])

    return matched, unmatched


async def create_playlist(client: httpx.AsyncClient, name: str, song_ids: list[str]) -> str:
    """Create the playlist and return its Navidrome ID."""
    response = await _call(client, "createPlaylist.view", {"name": name, "songId": song_ids})
    return str((response.get("playlist") or {}).get("id") or "")


async def annotate_playlist(
    client: httpx.AsyncClient, playlist_id: str, comment: str, public: bool
) -> None:
    """Attach the comment and public flag. createPlaylist accepts neither."""
    await _call(
        client,
        "updatePlaylist.view",
        {
            "playlistId": playlist_id,
            "comment": comment,
            "public": "true" if public else "false",
        },
    )


async def find_existing(client: httpx.AsyncClient, name: str) -> list[str]:
    """IDs of OUR playlists already carrying this name.

    Navidrome happily holds two playlists with the same name, so without this a
    re-push accumulates. Jellyfin's copy of this library has exactly that
    problem -- two `✦ 80s Italo Disco Party`, two `✦ Danceable 80s Electronic`
    -- from the generator being run twice. Not repeating it here.

    Scoped to `owner == navidrome_user` so a public playlist someone else made
    under the same name is never touched.
    """
    response = await _call(client, "getPlaylists.view", {})
    playlists = (response.get("playlists") or {}).get("playlist") or []
    wanted = _normalize(name)
    return [
        str(p["id"])
        for p in playlists
        if _normalize(p.get("name")) == wanted and p.get("owner") == settings.navidrome_user
    ]


async def delete_playlist(client: httpx.AsyncClient, playlist_id: str) -> None:
    """Remove one playlist by id."""
    await _call(client, "deletePlaylist.view", {"id": playlist_id})


async def read_back(client: httpx.AsyncClient, playlist_id: str) -> dict:
    """What Navidrome actually STORED, so the result is observed not assumed.

    createPlaylist and updatePlaylist both answer `ok`; neither proves the song
    count is what we sent or that the comment landed. This is the second,
    independent observation.
    """
    response = await _call(client, "getPlaylist.view", {"id": playlist_id})
    return response.get("playlist") or {}


def _unmatched_payload(unmatched: list[dict]) -> list[dict]:
    return [
        {"title": t.get("title", "?"), "artist_name": t.get("artist_name", "?")}
        for t in unmatched
    ]


def _failure(error: str, total: int, matched: int = 0, unmatched: list[dict] | None = None) -> dict:
    return {
        "success": False,
        "error": error,
        "navidrome_playlist_id": None,
        "navidrome_url": None,
        "comment": None,
        "public": False,
        "replaced_count": 0,
        "stored_song_count": 0,
        "matched_count": matched,
        "total_count": total,
        "unmatched_tracks": _unmatched_payload(unmatched or []),
    }


async def export_to_navidrome(
    track_ids: list[str],
    playlist_name: str,
    prompt: str | None = None,
    public: bool = False,
    replace_existing: bool = True,
) -> dict:
    """Resolve local track IDs to Navidrome songs and create the playlist.

    Deliberately never touches Navidrome's scanner: createPlaylist is immediate,
    while anything file-based waits on a scan that can be blocked for hours by a
    full library re-read (observed 2026-09-16, ~2 h).
    """
    if not _is_configured():
        return _failure("Navidrome is not configured", len(track_ids))

    tracks = get_track_files(track_ids)
    if not tracks:
        return _failure("No track files found in database", len(track_ids))

    total = len(tracks)
    try:
        matched_ids, unmatched = await resolve_song_ids(tracks)
    except Exception as exc:
        logger.error("Navidrome resolution failed: %s", exc)
        return _failure(f"Could not reach Navidrome: {exc}", total)

    if not matched_ids:
        return _failure(
            "Could not match any tracks in Navidrome. If the library was indexed "
            "recently, Navidrome may not have scanned it yet.",
            total,
            unmatched=unmatched,
        )

    comment = build_comment(prompt, total, len(matched_ids))

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Look BEFORE creating, so the new playlist is never a deletion candidate.
        stale: list[str] = []
        if replace_existing:
            try:
                stale = await find_existing(client, playlist_name)
            except Exception as exc:
                logger.warning("Could not list playlists to de-duplicate: %s", exc)

        try:
            playlist_id = await create_playlist(client, playlist_name, matched_ids)
        except Exception as exc:
            logger.error("Failed to create Navidrome playlist: %s", exc)
            return _failure(
                f"Failed to create playlist in Navidrome: {exc}",
                total, matched=len(matched_ids), unmatched=unmatched,
            )

        annotated = True
        try:
            await annotate_playlist(client, playlist_id, comment, public)
        except Exception as exc:
            # The playlist exists and plays; only its description is missing.
            logger.warning("Navidrome playlist %s created unannotated: %s", playlist_id, exc)
            annotated = False

        # Only now that the replacement demonstrably exists.
        replaced = 0
        for old_id in stale:
            if old_id == playlist_id:
                continue
            try:
                await delete_playlist(client, old_id)
                replaced += 1
            except Exception as exc:
                logger.warning("Could not remove superseded playlist %s: %s", old_id, exc)

        stored = await read_back(client, playlist_id)

    stored_count = int(stored.get("songCount") or 0)
    stored_comment = stored.get("comment") or ""
    warning = None
    if stored_count != len(matched_ids):
        warning = f"Navidrome stored {stored_count} of the {len(matched_ids)} tracks sent"
    elif annotated and not stored_comment:
        warning = "Playlist created, but the comment did not stick"
    elif not annotated:
        warning = "Playlist created, but the comment could not be set"

    logger.info(
        "Navidrome playlist %r (%s): %d/%d matched, %d stored, %d superseded",
        playlist_name, playlist_id, len(matched_ids), total, stored_count, replaced,
    )

    return {
        "success": True,
        "error": warning,
        "navidrome_playlist_id": playlist_id,
        "navidrome_url": f"{_base_url()}/app/#/playlist/{playlist_id}/show",
        "comment": stored_comment or None,
        "public": bool(stored.get("public", False)),
        "replaced_count": replaced,
        "stored_song_count": stored_count,
        "matched_count": len(matched_ids),
        "total_count": total,
        "unmatched_tracks": _unmatched_payload(unmatched),
    }
