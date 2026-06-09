# Cron-based incremental library sync — design

**Date:** 2026-06-09
**Status:** Approved

## Problem

The playlist generator depends on scanning the music collection and enriching
every track parameter. Today this is manual (`sync-new-tracks.sh`), and that
script points at a dead `:8000` backend — the live deployment is the
`playlist-generator` Docker container (compose `unified` profile) which
publishes **no host port** (reached only via SWAG on `nas-network`). The owner
wants this to run automatically on a schedule, only when new files exist, and to
populate every scannable parameter.

## Key facts

- `POST /sync/full-pipeline?skip_audio=false` already runs an incremental scan
  then every enrichment step (MusicBrainz → Last.fm → Metal Archives → release
  dates → embeddings → profiles → clusters → banger flags → search vectors).
  Each step is incremental (only new/unprocessed tracks). Defaults
  `skip_lastfm=false`, `skip_audio=true`.
- Container: `playlist-generator`, internal uvicorn on `127.0.0.1:8000`
  (nginx basic-auth fronts it on `:80`; `docker exec … curl 127.0.0.1:8000`
  bypasses auth). `/health` returns `{"status":"ok"}`.
- Music: `/mnt/drive/music` on host, mounted `:ro` as `/music`.
- Scanner incremental detection = size+mtime hash; `AUDIO_EXTENSIONS =
  {.flac .mp3 .ogg .m4a .opus .wav .aiff .aif}`.
- Host has `flock`, `docker`, `python3`, `curl`. Crontab convention: entries
  `cd /home/tom/nas` and append to `logs/`.

## Decisions

- **Cadence:** every 6 hours (gate makes empty checks ~free).
- **Audio:** included (`skip_audio=false`) — every scannable parameter.
- **Weekly catch-up:** unconditional full-pipeline run Sundays, to clear any
  backlog left by a failed/interrupted run and refresh global steps.

## Component: `cron-sync.sh` (repo root)

Self-contained bash script, two modes (default gated, `--catch-up` unconditional):

1. **Preflight** — `docker exec playlist-generator curl -sf http://127.0.0.1:8000/health`.
   Container down/unhealthy → log + exit 0, stamp untouched.
2. **New-file gate** (default only) — `find /mnt/drive/music -type f \( -iname
   '*.flac' -o … \) -newer <stamp> -print -quit`. Empty → exit 0 without
   touching the backend. Missing stamp (first run) ⇒ treat as new files.
3. **Run** — `docker exec playlist-generator curl -sf -N -X POST
   'http://127.0.0.1:8000/sync/full-pipeline?skip_audio=false'` piped to an SSE
   parser (same pattern as `sync-new-tracks.sh`): prints progress, exits
   non-zero on an `error` event or premature stream close, handles `409`
   (scan already running) gracefully.
4. **Advance stamp only on success** — capture stamp timestamp *before* the run,
   promote it to the real stamp file only on a clean `done`. Files landing
   mid-run stay newer than the stamp (caught next cycle); failed runs leave the
   stamp untouched (retried in 6h or by weekly catch-up).

State: `~/.local/state/playlist-generator/cron-sync.stamp` (matches
`rebuild-library.sh`). Logs: `~/nas/logs/playlist_sync.log`.

## Crontab (added to `~/nas` crontab)

```cron
15 */6 * * *  /usr/bin/flock -n /tmp/nas-playlist-sync.lock <repo>/cron-sync.sh            >> /home/tom/nas/logs/playlist_sync.log 2>&1
45 3 * * 0    /usr/bin/flock -n /tmp/nas-playlist-sync.lock <repo>/cron-sync.sh --catch-up >> /home/tom/nas/logs/playlist_sync.log 2>&1
```

Shared `flock` prevents overlap between/within runs (audio backfill may run long).

## Out of scope

- Refactoring stale `:8000` URLs in `sync-new-tracks.sh`/`rebuild-library.sh`.
- No backend changes — the endpoint already does everything.
