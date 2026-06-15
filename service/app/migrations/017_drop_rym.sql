-- 017_drop_rym.sql
-- Remove RateYourMusic entirely. RYM scraping was off by default and never run
-- (all tables empty), so this drops dead schema with no data loss. Curation now
-- runs on banger + Metal Archives; album genres come from track_genres +
-- album_tags. CASCADE clears the FKs to albums.

DROP TABLE IF EXISTS rym_album_adjacency CASCADE;
DROP TABLE IF EXISTS rym_album_genres CASCADE;
DROP TABLE IF EXISTS rym_genres CASCADE;
DROP TABLE IF EXISTS rym_albums CASCADE;
DROP TABLE IF EXISTS rym_scrape_cache CASCADE;
