# Album-Level Tag/Genre Collection — Design (P2)

**Date:** 2026-06-13
**Status:** Approved (user waived per-spec review for this program)
**Project:** P2 of the enrichment program. Pure **collection** — no scoring/
trajectory/genre algorithm changes, so **no eval gate**. P3 will consume this.

## Problem

Album-level genre/tag signal is collected from essentially one source today
(RateYourMusic). Several sources already hand album genres to us and we drop
them:

- **Discogs** `get_master_release_details()` parses `genres` + `styles`
  (`discogs.py:219-220`) then discards them — never persisted.
- **MusicBrainz** release-group lookups request only `includes=["releases"]`
  (`musicbrainz.py:208`); MB exposes per-RG `genres` with vote counts via
  `includes=["genres"]`, unused.
- **Last.fm** fetches track and artist tags but never calls
  `album.getTopTags` — no album-level Last.fm tags at all.
- **Metal Archives** scrapes only rating/review counts; the "Genre" field on the
  album/band page is never parsed.

Plus two discarded weighting signals on data we *do* collect:
- RYM `rym_album_genres.vote_count` column exists but is always 0.
- RYM `rym_albums.rating_std` is hard-coded to `None` (`rym.py`), though the
  column exists.

## Goal

Capture album-level genres/tags from all available sources into a single
unified store that P3 can read uniformly, **reusing existing API calls where
possible** (Discogs/MB genres piggyback on the release-date resolution that
already hits those APIs). No change to playlist output in this project.

## Architecture

### Unified store: `album_tags`

One table absorbs album-level genre/tag signal from every source. P3 reads this
one place instead of five source-specific schemas.

```sql
CREATE TABLE IF NOT EXISTS album_tags (
    album_id UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    source   VARCHAR(20) NOT NULL,   -- lastfm|discogs|musicbrainz|metal_archives|rym
    tag      VARCHAR NOT NULL,        -- normalized: lowercased, trimmed
    kind     VARCHAR(10) NOT NULL DEFAULT 'genre',  -- genre|style|tag
    weight   REAL,                    -- source-native weight/count, nullable
    position INTEGER,                 -- source ordering where available, nullable
    PRIMARY KEY (album_id, source, kind, tag)
);
CREATE INDEX IF NOT EXISTS idx_album_tags_album ON album_tags(album_id);
CREATE INDEX IF NOT EXISTS idx_album_tags_tag   ON album_tags(tag);
```

`ON DELETE CASCADE` keeps it consistent with the P1 reconciliation (deleting an
album drops its tags). Added both to `database_pg.init_database()` (idempotent
`CREATE TABLE IF NOT EXISTS`) **and** as numbered migration `016_album_tags.sql`
for existing DBs (per the project's migration workflow).

The RYM `vote_count` / `rating_std` fixes use the **existing** `rym_album_genres`
/ `rym_albums` columns — no schema change for those.

### Shared persist helper: `ingestion/album_tags.py`

```python
def normalize_tag(name: str) -> str        # lowercase, strip, collapse ws
def save_album_tags(cur, album_id, source, items, kind="genre") -> int
```
`items` is a list of either plain strings or `{"name", "weight"?, "position"?}`.
Upserts via `INSERT ... ON CONFLICT (album_id, source, kind, tag) DO UPDATE`.
Skips blank/empty names. This pure-ish function (only takes a cursor) is the unit
tested in isolation.

### Source wiring

| Source | Where hooked | Extra API call? | source / kind |
|---|---|---|---|
| Discogs | `release_dates.resolve_album_release_date` — `discogs_result` already carries genres/styles | **No** (reuses release-date call) | `discogs` / `genre`,`style` |
| MusicBrainz | new `musicbrainz.fetch_release_group_genres(mbid)` (`includes=["genres"]`), called from `resolve_album_release_date` when an MBID is present | one light call per album with an MBID | `musicbrainz` / `genre` (weight = vote count) |
| Last.fm | new pass `enrich_albums_from_lastfm_tags(force)` + `fetch_album_tags(network, artist, album)` via `pylast.Album(...).get_top_tags(limit=10)`; new `/enrich/lastfm-album-tags[/stream]` endpoint, wired into `/sync/full-pipeline` | yes, dedicated pass | `lastfm` / `tag` (weight = tag weight) |
| Metal Archives | extend the existing `scrape_album_rating` page parse to read the "Genre" dt/dd; persist in `enrich_albums_from_metal_archives` | **No** (reuses MA scrape) | `metal_archives` / `genre` |
| RYM | in `_save_rym_album`, also mirror parsed genres into `album_tags` (uniform read for P3); separately populate `rym_album_genres.vote_count` and `rym_albums.rating_std` when present on the page | **No** (reuses RYM scrape) | `rym` / `genre` (weight = vote count) |

**Discogs genres pass-through:** `resolve_discogs_release_date` must surface
`genres`/`styles` (already obtained by `get_master_release_details`) in its
returned dict so `resolve_album_release_date` can persist them. This is the only
change to the Discogs return contract.

**MB genres:** `get_release_group_by_id(mbid, includes=["genres"])` returns a
`genre-list` of `{name, count}`. Parse to `{"name", "weight": count}`. A new
small function keeps `extract_release_date_from_mb` (which uses
`includes=["releases"]`) untouched, at the cost of one extra MB call per album
with a resolved MBID. MB's rate limiter (already in `musicbrainz.py`) applies.

### Scrape-based items are best-effort, no-regression

Metal Archives "Genre" and RYM `vote_count`/`rating_std` depend on HTML that may
not always be present or may be rate-limited/blocked at scrape time. They are
implemented defensively: **parse if present, else leave null / write nothing.**
They never raise into the enrichment loop and never reduce existing data. If a
selector finds nothing, the album simply gets no row from that source — exactly
today's behavior.

## Backfill

- **Discogs + MB genres** are populated by re-running release-date resolution:
  `resolve_release_dates(force=True)` (existing endpoint `/enrich/release-dates`).
- **Last.fm album tags**: run the new `/enrich/lastfm-album-tags` pass (also part
  of `/sync/full-pipeline` going forward).
- **MA genre / RYM**: populated on the next `enrich_albums_from_metal_archives` /
  `enrich_albums_from_rym` run.
A one-shot backfill is just running these enrichment passes with `force=True`;
no separate migration script needed beyond `016_album_tags.sql` (table create).

## Out of scope (YAGNI / deferred)

- **Last.fm fractional tag weights / top-N>10**: existing `track_lastfm_tags` /
  `artist_lastfm_tags` keep `INTEGER` weight and `limit=10`. The fractional loss
  (pylast weights are integer 0-100) is negligible and a column migration buys
  nothing. New `album_tags.weight` is `REAL` to avoid baking in the limitation.
- **Artist-level genres from RYM/Discogs/MA**, **track-level MBIDs/tags from MB**:
  separate future collection work; not needed for album-genre consumption in P3.
- **Discogs release-variation detail, MA themes/keywords**: not genre signal.

## Testing

- `normalize_tag` — casing, whitespace, empties (pure).
- `save_album_tags` — string list and dict list, upsert/conflict update, blank
  skip, multi-source coexistence for one album (DB integration, rolled back like
  the P1 tests; raw pooled connection, never commits).
- MB genre parse — `genre-list` of `{name, count}` → `{name, weight}` (pure, fed
  a sample response dict).
- MA genre parse — feed sample album-page HTML to the parser, assert the genre
  string is extracted; assert missing-genre HTML yields nothing (no raise).
- RYM `rating_std` / `vote_count` parse — sample HTML with and without the
  fields; assert no-regression when absent.
- Last.fm `fetch_album_tags` — monkeypatch `pylast.Album.get_top_tags`.

## Documentation (same commit)

- `AGENTS.md`: new `album_tags` table in the schema list; new
  `/enrich/lastfm-album-tags` endpoint(s); note Discogs/MB now persist genres.
- `README.md`: API reference for the new endpoint.
- `CLAUDE.md`: migration note (`016_album_tags.sql`); pipeline now includes a
  Last.fm album-tag stage.
