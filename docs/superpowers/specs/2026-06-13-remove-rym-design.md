# Remove RateYourMusic (RYM) entirely — Design

**Date:** 2026-06-13
**Status:** Approved (user directive: "completely remove rym from algorithms,
front-end, back-end, and db; if anything severely depends on it, find ways to do
it with other data")

## Why this is safe (behavioural no-op)

RYM scraping was off by default (`rym_scrape_enabled=False`) and never run. All
RYM tables are **empty** (`rym_albums`, `rym_genres`, `rym_album_genres`,
`rym_album_adjacency`, `rym_scrape_cache` = 0 rows). Therefore every RYM code
path is already inert and removal changes no playlist output:

- **curation_score** already degrades to `banger·0.65 + album_legitimacy·0.35`
  whenever RYM is absent (`candidates.py`), which is *always* — so removing the
  RYM branch leaves the live formula unchanged. "Other data" = banger detection
  + Metal Archives legitimacy (already the sole inputs in practice).
- **genre matching / negative constraints** read empty `rym_genres`/`rym_descriptors`
  → no contribution. Genre signal now comes from `track_genres` + `album_tags`.
- **sequencer album-adjacency bonus** reads empty `rym_album_adjacency` → bonus is
  always 0. Sequencing already runs on energy/tempo/genre/era continuity +
  embedding similarity; the bonus is dropped, not replaced.
- **embeddings** only appended RYM text when present → never; existing and future
  embeddings are unaffected.

No eval run is required (provably identical output); the change is mechanical
removal.

## Scope — remove from every layer

**Backend**
- Delete `service/app/ingestion/rym.py`.
- `routes_v3.py`: drop the import, `_rym_lock`, and `/enrich/rym`,
  `/enrich/rym/stream`, `/enrich/rym/status`. Remove any RYM stage from
  `/sync/full-pipeline`.
- `candidates.py`: remove `rym_rating/rym_votes/rym_genres/rym_descriptors`
  fields, the `ra.`→`rym_albums` SQL joins + column selects + row unpacking in
  both candidate queries, the RYM branch of `curation_score` (keep the
  banger+MA formula), and RYM use in `compute_genre_match_score` /
  `compute_negative_constraint_penalty`.
- `sequencer.py`: remove `load_album_adjacency_cache`, the adjacency-bonus
  computation, and its threading through the beam search.
- `embeddings/generator.py`: remove the RYM text lines and the RYM SQL fetch.
- `database_pg.py`: remove the five `rym_*` CREATE TABLEs + indexes and the RYM
  stats collection.

**DB migration**
- New `017_drop_rym.sql`: `DROP TABLE IF EXISTS` for all five rym_* tables
  (CASCADE). `album_tags` is unaffected (generic `source` column); only the
  comment listing example sources is updated to drop "rym".

**Config/settings**
- Remove `rym_scrape_enabled`, `rym_scrape_delay_min`, `rym_scrape_delay_max`
  from `config.py`, `settings_registry.py`, `.env.example`, and the
  docker-compose env (`RYM_SCRAPE_ENABLED`). Update settings tests.

**Frontend**
- `LibrarySettingsPanel.vue`: remove the RYM button, the RYM coverage metric
  card, the `rym` enrichment-stream wiring, and RYM help text.
- `types/library.ts`: remove `albums_with_rym`, `rym_adjacency_pairs`.
- Any `frontend/server/api/enrich/rym*` proxy route.

**Docs**
- `CLAUDE.md`, `README.md`, `AGENTS.md`: drop RYM from the enrichment/source
  lists, the curation-score formula, the schema list, the endpoint tables, and
  the pipeline-stage notes. Historical spec files (P2/P3) are left as dated
  records.

## Verification
- Full pytest suite green; backend imports clean; zero new lint.
- Rebuild + redeploy; `/health` ok; playlist generation works end-to-end
  (confirms the candidate SQL still loads after the `rym_albums` joins are gone).
