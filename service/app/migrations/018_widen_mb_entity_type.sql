-- 018_widen_mb_entity_type.sql
-- MusicBrainz ALBUM resolution has never written a single row.
--
-- mb_lookup_cache.entity_type was VARCHAR(10). The artist branch inserts
-- 'artist' (6 chars) and works -- 3,143 rows. The album branch inserts
-- 'release_group' (13 chars) and throws on every single album:
--
--   MB album resolution error for 'Zenyatta Mondatta':
--     value too long for type character varying(10)
--
-- Both the match branch (ingestion/musicbrainz.py _save_album_mbid) and the
-- no-match branch insert that literal, so every album fails either way. The
-- surrounding `except Exception` swallows it as a WARNING and the
-- `stats["albums_resolved"] += 1` after the raising call is never reached --
-- which is why the log reads "(0 resolved)" for thousands of albums and
-- `SELECT count(*) FROM albums WHERE musicbrainz_id IS NOT NULL` returned 0
-- out of 15,474 on 2026-09-03.
--
-- 32 rather than 13: leaves room for other entity types (recording, release,
-- work) without another migration. Widening a varchar is a catalog-only change
-- in Postgres -- no table rewrite -- and this table holds ~3k rows.
--
-- The CREATE TABLE in database_pg.py is fixed in the same commit, because it is
-- CREATE TABLE IF NOT EXISTS: an existing database never picks up a changed
-- definition, and a fresh one would otherwise be born broken again.

ALTER TABLE mb_lookup_cache
    ALTER COLUMN entity_type TYPE VARCHAR(32);
