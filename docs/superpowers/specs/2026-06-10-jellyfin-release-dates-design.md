# Jellyfin Release-Date Fixer — Design

**Date:** 2026-06-10
**Status:** Approved (design); pending implementation plan
**Branch:** `jellyfin-release-dates`

## Problem

Jellyfin shows wrong album release dates (reissue/remaster years, scraper guesses). The app now resolves true original release dates (Discogs master release = first pressing) into `album_release_dates`. A Tools page button should push those original dates onto the matching Jellyfin albums so Jellyfin displays/sorts by the real first-pressing year.

## Decisions (from brainstorming)

- **One-click apply-all** (no dry-run/preview). Show a result summary after.
- **Albums only** (set MusicAlbum date; not per-track). Even for reissues-with-bonus-tracks, write the original date.
- **Path-based matching** primary (same `/music` files indexed by both app and Jellyfin), normalized `AlbumArtist + Album` name match as fallback.
- **Lock the fields** so Jellyfin's metadata refresh doesn't revert them.

## Non-Goals

- No per-track date writes.
- No dry-run/preview gate.
- No DB writes (read app data, write Jellyfin only).
- No new matching of tracks the app doesn't already have paths for.

## Data sources

- `album_release_dates(album_id, original_year, original_month, original_day, precision, confidence, …)` — only albums with `original_year IS NOT NULL` are eligible.
- App albums → tracks → `track_files.path` (`/music/...`) gives representative paths per album.
- `settings.jellyfin_url`, `settings.jellyfin_api_key`, `settings.local_path_prefix` (`/music`), `settings.jellyfin_path_prefix` (`/data/movies/music`) — already configured; same vars the playlist export uses.

## Architecture

### Backend

**New module `service/app/ingestion/jellyfin_dates.py`** — focused, testable:

Pure helpers (unit-tested, no I/O):
- `translate_path(local_path, local_prefix, jellyfin_prefix) -> str` — rewrite `/music/...` → `/data/movies/music/...`.
- `build_premiere_date(year, month, day, precision) -> str` — ISO `YYYY-MM-DDT00:00:00.0000000Z`; month/day default to `01` when precision is `year` or values absent. Returns the string Jellyfin expects.
- `resolve_album_id_map(app_albums, jellyfin_audio_items, local_prefix, jellyfin_prefix) -> dict[app_album_id, jellyfin_album_id]` — for each app album, translate its representative track path(s) and look up the Jellyfin `AlbumId` from the audio-item path map; record misses for name fallback.
- `match_by_name(app_album_name, app_artist, jellyfin_albums) -> jellyfin_album_id | None` — normalized fallback (reuse `textnorm`).

Jellyfin client functions (httpx, mirror `ingestion/jellyfin.py` auth `X-Emby-Token`):
- `fetch_audio_items(client) -> list[{Id, AlbumId, Path}]` — paged `GET /Users/{uid}/Items?IncludeItemTypes=Audio&Recursive=true&Fields=Path&StartIndex=…&Limit=…`.
- `fetch_album_items(client) -> list[{Id, Name, AlbumArtist}]` — paged `GET …?IncludeItemTypes=MusicAlbum&Recursive=true&Fields=AlbumArtist` (for name fallback).
- `update_album_date(client, jellyfin_album_id, premiere_date, year) -> None` — `GET /Users/{uid}/Items/{id}` (full DTO), set `PremiereDate`, `ProductionYear`, append `"PremiereDate"`,`"ProductionYear"` to `LockedFields`, then `POST /Items/{id}` with the mutated DTO. Raises on non-2xx.

**Orchestrator** `async fix_release_dates(progress_callback) -> dict`:
1. Load eligible app albums (`original_year` present) with name/artist + a representative track path. If none → return early summary.
2. Guard: if `jellyfin_url`/`jellyfin_api_key` unset → return `{error: "Jellyfin not configured"}`.
3. Fetch Jellyfin audio items → build `jellyfin_path → AlbumId` map. Build `resolve_album_id_map`. For unresolved, fetch album items and name-match.
4. For each resolved album: `build_premiere_date`, `update_album_date`; count outcomes; `progress_callback(i, total, msg)`. Per-album failures are caught and counted, never abort the run.
5. Return `{eligible, matched, updated, skipped_no_jellyfin_match, failed, errors: [sample…]}`.

**Endpoint** in `routes_v3.py`: `POST /jellyfin/fix-release-dates` → SSE stream (mirror existing enrichment SSE pattern) emitting `{stage, progress, message}` and a final `{done: true, stats}`. A module-level lock prevents concurrent runs.

### Frontend

- New page `frontend/app/pages/tools.vue` + a "Tools" entry in `layouts/default.vue` nav.
- A card "Fix Jellyfin release dates" with a one-line explanation + a button. Click → open SSE to `/api/jellyfin/fix-release-dates`, show a progress bar + live count, then a result summary (eligible / matched / updated / unmatched / failed) and a few error samples if any. Nuxt UI v4. A composable `useJellyfinTools.ts` wraps the SSE call (mirror `useEnrichmentStream.ts`).

## Error handling

- Jellyfin unconfigured → endpoint returns a clear error event; button shows it.
- Per-album GET/POST failure → caught, counted in `failed`, first N error strings returned; run continues.
- Unmatched albums (no Jellyfin path or name match) → counted in `skipped_no_jellyfin_match`, not an error.
- Paged Jellyfin fetch handles empty/short pages; total from `TotalRecordCount`.

## Testing

- pytest (pure): `translate_path` (prefix swap, trailing slashes, non-prefixed path passthrough); `build_premiere_date` (year-only → `-01-01`, full date, missing month/day); `resolve_album_id_map` against a mocked audio-item list (hit, miss, multiple tracks same album); `match_by_name` (normalized hit, no-match).
- Live Jellyfin write verified manually via the button (httpx mocked in tests).

## Rollout

1. Build + deploy (next deploy after the current rescan finishes, so as not to interrupt it).
2. Open Tools page → click button → albums get original dates; Jellyfin reflects them after the run (locked, so they persist).
3. Best run after `album_release_dates` is well-populated (the Discogs release-date stage of the current rescan is filling it now).
