# Scan Orphan Reconciliation — Design

**Date:** 2026-06-13
**Status:** Approved (pending spec review)
**Project:** P1 of the "enrichment + reconciliation" program (independent of P2/P3)

## Problem

When albums are deleted from the music library on disk (e.g. removed in Lidarr,
or manually), they continue to appear in the playlist-generator and remain
eligible for playlist generation. The filesystem scanner (`scan_library()` in
`service/app/ingestion/scanner.py`) is **additive-only** for `tracks` and
`albums`: when a file disappears it sets `track_files.missing_since = now()`
(scanner.py:605-613) but **never removes** the `tracks` / `albums` rows or their
enrichment data. Those rows live in the DB forever and keep surfacing in
results.

The Jellyfin sync path (`ingestion/jellyfin.py`) already hard-deletes orphaned
tracks on a full sync, but the filesystem scanner — which is what actually runs
in this deployment (cron `cron-sync.sh` → `/sync/full-pipeline` → `scan_library`,
and `app.cli_v3 scan`) — has no equivalent. This design adds that reconciliation.

## Goal

During every scan, hard-delete tracks whose files are all gone, plus the
albums/artists left empty as a result — with a safety guard that prevents a bad
scan (unmounted/empty library directory) from wiping the database.

## Scope decisions (from brainstorming)

- **Behavior:** hard-delete orphans (not soft-delete, not grace-period, not
  query-time exclusion). Mirrors the existing Jellyfin sync semantics.
- **Trigger:** every scan — incremental and full. The scanner already walks the
  full tree and runs the mark-missing pass on every scan, so orphan detection is
  already available on every run.
- **Safety:** abort deletion on a suspicious wipe (see Safety Guard).

Out of scope (YAGNI): grace period, soft-delete/restore UI, a configurable
threshold setting, artist-level external cleanup beyond row removal.

## Where it hooks

`service/app/ingestion/scanner.py`, inside `scan_library()`, immediately after
the existing "Mark missing files" block (~scanner.py:613), within the **same
`with get_connection() as conn` transaction** so detection and deletion are
atomic with the missing-marking that precedes them.

All three scan entrypoints funnel through `scan_library()`, so this one hook
covers every caller:
- `app.cli_v3 scan` (cli_v3.py:38)
- API scan routes (routes_v3.py:515, 571)
- cron `/sync/full-pipeline` (routes_v3.py:1261)

## Logic

### 1. Detect orphaned tracks

A track is orphaned when it has **no present file** — every `track_files` row for
it has `missing_since IS NOT NULL`, or it has no files at all:

```sql
SELECT t.id FROM tracks t
WHERE NOT EXISTS (
    SELECT 1 FROM track_files tf
    WHERE tf.track_id = t.id AND tf.missing_since IS NULL
)
```

This correctly **keeps** multi-file tracks (same fingerprint at multiple paths)
that still have at least one present file. Because the mark-missing pass runs
just before this in the same transaction, `missing_since` is current.

### 2. Safety guard (abort on suspicious wipe)

Compute, in the same transaction:
- `total_tracks` = `SELECT count(*) FROM tracks`
- `files_found` = number of audio files seen on disk this scan (`len(all_files)`)
- `orphan_count` = number of track ids from step 1

Skip deletion entirely and emit a loud `logger.warning(...)` if **either**:
- `files_found == 0` **and** `total_tracks > 0` — classic unmounted/empty
  `/mnt/drive`; nothing was seen on disk, so "everything is missing" is almost
  certainly wrong, **or**
- `orphan_count > PRUNE_MAX_FRACTION * total_tracks` — mass-deletion tripwire.
  `PRUNE_MAX_FRACTION = 0.20` (module constant). A normal album delete is ~10
  tracks, far under 20% of a 35k-track library.

When the guard trips, set `stats["prune_skipped"] = True` and
`stats["prune_skipped_reason"] = "<which condition>"`, log the orphan count and
threshold, and return without deleting.

**Override:** a `force_prune: bool = False` parameter on `scan_library()` bypasses
the guard (still logs what it deleted). Threaded through:
- `cli_v3` — new `--force-prune` flag on the `scan` command
- scan API routes and `/sync/full-pipeline` — new `force_prune: bool = False`
  query param passed into `scan_library(..., force_prune=force_prune)`

The `files_found == 0` condition is **never** overridden by `force_prune` — an
empty scan is treated as a hard error regardless, because there is no legitimate
case where deleting the entire library from a zero-file scan is intended.

### 3. Delete

Confirmed: all FKs referencing `tracks`, `albums`, `artists` use
`ON DELETE CASCADE` (database_pg.py:82-552). So deletion is a single statement
per level and the database cascades to all child tables:

```sql
DELETE FROM tracks WHERE id IN (<orphan ids>);
```

This cascades to `track_files`, `track_embeddings`, `track_genres`,
`track_artists`, `track_albums`, `track_lastfm_tags`, `lastfm_stats`,
`track_audio_features`, `track_banger_flags`, `track_studio_scores`,
`track_genre_probabilities`, `playlist_tracks`, etc. — including removing the
track from any historical `generated_playlists`, which is acceptable since the
underlying file no longer exists.

Then prune now-empty parents:

```sql
DELETE FROM albums a
WHERE NOT EXISTS (SELECT 1 FROM track_albums ta WHERE ta.album_id = a.id);

DELETE FROM artists ar
WHERE NOT EXISTS (SELECT 1 FROM track_artists ta WHERE ta.artist_id = ar.id)
  AND NOT EXISTS (SELECT 1 FROM album_artists aa WHERE aa.artist_id = ar.id);
```

Album/artist deletes cascade to their own enrichment children (`rym_albums`,
`album_legitimacy`, `album_release_dates`, `rym_album_genres`,
`rym_album_adjacency`, `artist_lastfm_tags`, `artist_similarity`, etc.).

Batch the `IN (...)` delete if the orphan list is large (chunks of ~1000 ids) to
keep statement size bounded.

### 4. Stats & visibility

Extend the returned `stats` dict with:
- `tracks_removed` (int)
- `albums_removed` (int)
- `artists_removed` (int)
- `prune_skipped` (bool) and `prune_skipped_reason` (str | None)

These flow into the existing scan log line (`logger.info(f"Scan complete: {stats}")`,
scanner.py:615) and the SSE progress / `cron-sync.sh` log, so a skipped prune or
a large deletion is visible after the fact.

## Error handling

- The detect → guard → delete sequence runs inside the existing connection's
  transaction. On any exception, log the error, do **not** partially delete
  (let the transaction roll back / avoid committing the delete), and surface via
  `stats["errors"]` consistent with the existing per-track error handling.
- The guard is evaluated **before** any delete executes, so a tripped guard
  performs zero deletes.

## Testing

Unit tests (pytest) for the reconciliation logic, ideally factored into a small
pure-ish helper so the guard math is testable without a full scan:

1. **Orphan detection:** a track with all files `missing_since` set is selected;
   a multi-file track with one present file is NOT selected; a track with no
   files is selected.
2. **Guard — zero files:** `files_found == 0`, `total_tracks > 0` → no deletion,
   `prune_skipped` true, even with `force_prune=True`.
3. **Guard — over threshold:** `orphan_count` > 20% of `total_tracks` → no
   deletion, `prune_skipped` true; with `force_prune=True` → deletion proceeds.
4. **Normal delete:** small orphan set under threshold → tracks deleted, empty
   albums/artists pruned, counts reported in stats.

Verify cascade behavior against the real schema (delete a track, assert child
rows in e.g. `track_genres` / `track_files` are gone).

## Documentation updates (same commit)

Per the project's doc-freshness policy:
- `AGENTS.md` — scan behavior now reconciles deletions (and the new
  `force_prune` / `--force-prune` knobs).
- `CLAUDE.md` — note in the "Scheduled library sync" section that scans now
  hard-delete orphaned tracks/albums with a safety guard.

No schema migration is required: `track_files.missing_since` already exists and
no new columns are added.
