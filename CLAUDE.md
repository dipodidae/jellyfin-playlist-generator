# Claude Development Guidelines

## Project Context

This is a playlist generator that creates intelligent playlists from a Jellyfin music library using:
- Semantic embeddings for understanding prompts
- 6D trajectory-based composition (energy, tempo, darkness, texture, era, valence)
- Multi-source enrichment: Last.fm (tags, similarity, play stats), MusicBrainz (IDs), Metal Archives (legitimacy), Discogs (release dates + album genres)
- Curation scoring: banger detection + album legitimacy + studio/live preference
- Genre Manifold System (GMS): probabilistic genre identity vectors
- Extended audio features: BPM, loudness, brightness, valence, danceability, pulse clarity, onset rate, instrumentalness, acousticness, MFCC timbre (heuristic proxies via librosa)
- OpenAI for creative playlist titles

## Code Style

### Python (Backend)
- Python 3.12+ with type hints
- FastAPI for API routes
- Pydantic for data validation
- PostgreSQL 16 + pgvector (no ORM)
- Use `async`/`await` for I/O operations
- Keep functions focused and small

### TypeScript/Vue (Frontend)
- Nuxt 4 with Vue 3 Composition API
- `<script setup lang="ts">` for components
- Nuxt UI v4 (not Pro) for components
- TailwindCSS for styling
- Use `ref()` and `computed()` for reactivity

## Important Files

### Backend
- `service/app/api/routes_v3.py` - All API endpoints (PostgreSQL)
- `service/app/api/routes_settings.py` - Settings CRUD + test + Discogs OAuth endpoints
- `service/app/settings_registry.py` - Declarative registry of all DB-backed settings (pure, no I/O)
- `service/app/settings_store.py` - DB load/reload/save/seed; overlays values onto the `settings` singleton
- `service/app/ingestion/discogs_oauth.py` - Discogs PLAINTEXT OAuth 1.0a header builder + token exchange
- `service/app/trajectory/intent.py` - Prompt parsing, PromptType, GenreMode, 5D waypoints, era mode. LLM parse uses OpenAI Structured Outputs (json_schema, strict, seeded), grounds genres in the library vocab + snaps unknowns via embeddings, and caches on the normalized prompt. `expand_genre_hints` reads the single canonical `GENRE_GRAPH`; `hard_avoid_keywords` drives the genre pre-filter. `genre_hints_raw` preserves the exact niche terms (drives P-NICHE); `detect_focused` sets `intent.focused` for exclusivity prompts (P-FOCUS). The genre_hints prompt instruction preserves precise microgenres ("war metal") instead of collapsing to the broad family
- `service/app/trajectory/library_vocab.py` - Library vocabulary grounding (P2: real genres/tags injected into the parse prompt) + embedding genre snapping (P4); process-cached, `reset_cache()` to refresh
- `service/app/trajectory/composer_v4.py` - v4 playlist composition (arc/trajectory mode)
- `service/app/snapshot/composer.py` - **snapshot mode** composer: `compose_snapshot()` builds a breadth-across-artists archival cross-section (2–4 banger+deep-cut tracks per artist, ~120 soft cap, constraint shuffle). Reuses intent parse + candidate scoring; bypasses beam-search sequencing entirely
- `service/app/snapshot/selection.py` - pure snapshot primitives: `relevance`, `compute_snapshot_scores`, `is_banger`, `select_artist_tracks`, `apply_soft_cap`, `shuffle_no_adjacent_artist` (no I/O, unit-tested in isolation)
- `service/app/trajectory/candidates.py` - Candidate pools, curation scoring, adaptive weights. Strong artist seeds + Last.fm-tag expansion (`expand_artist_seeds`, `compute_seed_affinity_score`, exact-name only — P-SEED); niche tag-aware genre scoring (`derive_niche_hints`, `_attach_artist_tags`, `compute_genre_match_score` niche regime — P-NICHE); focused-mode trajectory flattening in `get_adaptive_weights` (P-FOCUS)
- `service/app/trajectory/sequencer.py` - Beam search, acoustic continuity, era coherence
- `service/app/genre/manifold.py` - Genre Manifold System (GMS)
- `service/app/ingestion/release_dates.py` - Multi-source original release date resolver
- `service/app/ingestion/musicbrainz.py` - MusicBrainz ID resolution
- `service/app/ingestion/jellyfin_dates.py` - Push resolved original release dates to Jellyfin: path-based album matching (LOCAL_PATH_PREFIX → JELLYFIN_PATH_PREFIX) with normalized name fallback, sets PremiereDate + ProductionYear and locks those fields
- `service/app/ingestion/metal_archives.py` - Metal Archives album legitimacy
- `service/app/ingestion/version_classifier.py` - Pure studio/live/demo/remix/bonus classifier → (version_type, studio_score); no I/O
- `service/app/ingestion/studio_scores.py` - Backfill `track_studio_scores` from track + album title metadata
- `service/app/enrichment/banger_detector.py` - Banger detection from Last.fm
- `service/app/database_pg.py` - PostgreSQL + pgvector schema, queries, BM25 search vectors
- `service/app/config.py` - Environment settings (base defaults; DB overlays these at runtime)

### Frontend
- `frontend/app/pages/index.vue` - Main UI
- `frontend/app/pages/settings.vue` - In-app settings page (registry-driven)
- `frontend/app/pages/tools.vue` - Tools page: Fix Jellyfin release dates button (SSE progress); writes LOCKED original release dates to Jellyfin albums via path-based matching
- `frontend/app/composables/useSettings.ts` - fetch/save/test/OAuth composable
- `frontend/app/types/settings.ts` - TypeScript types for the settings API
- `frontend/server/api/` - Nuxt server routes (proxy to backend)
- `frontend/nuxt.config.ts` - Nuxt configuration

## Common Tasks

### Adding a new API endpoint
1. Add route in `service/app/api/routes.py`
2. Add schema in `service/app/api/schemas.py` if needed
3. Add proxy route in `frontend/server/api/`

### Album-level genres/tags (`album_tags`)
Unified store (migration `016_album_tags.sql`) collecting album genres/tags from
every source into one table — `(album_id, source, kind, tag, weight, position)`.
Populated by: Discogs + MusicBrainz genres during release-date resolution (no
extra calls beyond one MB genre lookup); a dedicated Last.fm `album.getTopTags`
pass (`/enrich/lastfm-album-tags`, also stage 2b of `/sync/full-pipeline`); and
the Metal Archives scrape (best-effort genre field). Read by genre matching, the
Genre Manifold ensemble, and the BM25 search vector (dormant until backfilled).

### Modifying the database schema
1. Add a migration file in `service/app/migrations/` (numbered, e.g. `012_my_change.sql`)
2. Apply it: `psql $DATABASE_URL -f service/app/migrations/012_my_change.sql`
3. Update `service/app/database_pg.py` if adding new query helpers

### Testing locally
```bash
# Backend (stop the production service first)
systemctl --user stop playlist-generator-backend
cd service && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && pnpm dev --port 3000
```

### Deploying
```bash
# Backend
systemctl --user restart playlist-generator-backend

# Frontend
cd frontend && pnpm build && pm2 restart playlist-generator-frontend
```
Note: Backend takes ~60 seconds to start on Pi 5 (sentence-transformers model load).

### Scheduled library sync
Driven from the **NAS repo**, not from here: `~/nas/scripts/playlist_sync_stage.py`
runs ONE stage per invocation in a bounded batch, wrapped in `cron_job.py`, logging
to `~/nas/logs/playlist_sync.log`. `cron-sync.sh` and `/sync/full-pipeline` are
retired — one pass needed 3+ days and the SSE stream never survived it
(TRIAGE-2026-09-03). `sync-new-tracks.sh` is likewise dead; it points at the
defunct native `:8000` backend.

The fleet, as of 2026-09-16 (see `~/nas/cron/crontab` for the full reasoning):

| When | Job | Stages |
|---|---|---|
| `*/30` | `playlist-lastfm-tracks` | `lastfm-tracks --limit 300` |
| `:12` | `playlist-album-tags` | `lastfm-album-tags --limit 300` |
| `:22` | `playlist-derived` | `embeddings profiles --limit 4000` |
| `:42` | `playlist-release-dates` | `release-dates --limit 300` |
| `:52` | `playlist-scan` | `scan` |
| `03:20` | `playlist-aggregates` | `studio-scores banger-flags clusters genre-manifold search-vectors` |
| `04:40` | `playlist-catchup` | `lastfm-artists musicbrainz metal-archives` |
| `05:10` | `playlist-audio` | `audio` (own lock — multi-hour) |

All but `playlist-audio` share `/tmp/nas-playlist-stage.lock`, so no two overlap.
Before 2026-09-16 only the first, second and fourth rows existed: the scan could
not report success at all (no `done` event — gotcha 12), and the derived stages
blocked `/health` (gotcha 13).

**Scans reconcile deletions.** Every scan (`scan_library`, used by `app.cli_v3
scan`, `/scan`, `/scan/stream`, and `/sync/full-pipeline`) hard-deletes tracks
whose files are all gone — i.e. every `track_files` row is `missing_since` — plus
the albums/artists left empty (cascades via `ON DELETE CASCADE`). A safety guard
**aborts the prune** if a scan finds zero files while tracks exist, or would
delete more than `PRUNE_MAX_FRACTION` (20%) of the library in one run — this
protects against an unmounted/partially-mounted `/mnt/drive` wiping the DB. Pass
`force_prune=true` (query param) / `--force-prune` (CLI) to bypass the 20%
threshold; the zero-files abort is never bypassable. Skip/removal counts surface
in the scan stats (`tracks_removed`, `albums_removed`, `artists_removed`,
`prune_skipped`).

## Gotchas

1. **DB-backed settings (singleton overlay)**: App-level settings (API keys, enrichment toggles, Jellyfin config, library paths, clustering params) live in the `app_settings` Postgres table. At startup and on every `/settings` save, `settings_store.reload_settings()` overlays the DB values onto the pydantic `settings` singleton via `setattr`. This works because the app runs as a **single uvicorn process** — no cache invalidation, TTL, or inter-process sync is needed. If you ever move to multi-worker mode this assumption breaks. `.env` values for these keys are **seed-only**: they are written to the DB on first boot (when the key is absent) and then ignored; editing `.env` after first boot has no effect on a live instance. Only `DATABASE_URL` remains strictly env-driven; the `NUXT_AUTH_*` / `NUXT_SESSION_PASSWORD` variables are gone (2026-09-04) along with the `nuxt-auth-utils` module they configured, which had no call sites at all.

2. **Nuxt auto-imports**: `defineEventHandler`, `useRuntimeConfig`, etc. are auto-imported - IDE may show errors but they work at runtime

3. **PostgreSQL connections**: Use `psycopg2` connection pool in `database_pg.py`; always return connections to the pool

4. **Embedding model**: First load downloads ~90MB model, subsequent loads use cache (~60s startup on Pi 5)

5. **Backend port**: Production runs on `:8000` (systemd service). Do not hardcode `:8100`.

6. **Environment variables**: Nuxt uses `NUXT_` prefix for runtime config (e.g., `NUXT_BACKEND_URL`)

7. **Docker image bakes the source.** Algorithm changes are NOT live until you rebuild. **Production** runs under the main NAS compose (project `nas`, image `nas/playlist-generator`, container `playlist-generator`, served via SWAG on internal port 80 — no host port published); deploy with `cd /home/tom/nas && docker compose up -d --build playlist-generator`. The **local** `docker-compose.yml` here (`unified` profile, image `jellyfin-playlist-generator-app`) is a standalone dev/eval stack that publishes the app on `127.0.0.1:8080` and the DB on `127.0.0.1:5432`; do NOT run `docker compose --profile unified up` while the production `nas`-project containers are running — the container names collide and compose aborts. Point `eval_loop.py` at whichever app is up via `BACKEND_URL` (the local unified app: `http://localhost:8080`; production has no host port, so eval it via `docker exec playlist-generator` against `http://127.0.0.1:8000`).

8. **Valence, instrumentalness, and acousticness are heuristic proxies, not ground-truth.** They are computed from raw audio signal via librosa (valence = 0.5×majorness + 0.3×bpm_norm + 0.2×brightness_norm; instrumentalness ≈ 1 − vocal-band-energy fraction; acousticness ≈ weighted harmonic ratio + low-brightness + low-flatness). They correlate with the intended qualities on average but are not reliable for individual tracks. Do not treat them as authoritative mood/genre labels.

9. **Adding audio metrics requires a full library re-analysis before B/C scoring is meaningful.** The `analyze_library()` function (`audio/analyzer.py`) re-analyzes any track where `valence IS NULL OR mfcc IS NULL`. On a large library (35k+ tracks) this takes several hours. Until the re-analysis is complete, valence trajectory scoring (Phase B) and the expanded acoustic continuity terms in the sequencer (Phase C) silently degrade to no-op for un-analyzed tracks — results will be correct but the new scoring only applies to the analyzed subset. Run `POST /enrich/audio` and monitor progress before evaluating Phase B/C behavior. It is on the NAS crontab daily at 05:10 as of 2026-09-16 (`playlist-audio`, its OWN lock so a multi-hour pass cannot starve the hourly stages); before that nothing scheduled it at all and 17,959 tracks had no features. `cron-sync.sh` no longer drives it -- that whole-pipeline script was retired on 2026-09-03.

10. **An enrichment sweep that selects "rows still missing X" MUST record the attempt, not just the success (migration 019, `enrichment_attempts`).** Every such pass here had the same shape: `WHERE NOT EXISTS (...) ORDER BY <stable key> LIMIT n`, writing a row only when the upstream API returned something. The moment the first `n` candidates are all ones the API has nothing for, nothing is written, the candidate set does not change, and the next run re-selects the identical batch — forever, at exit 0. Measured 2026-09-16 on `lastfm-album-tags`: 300 albums/hour, **0 tagged**, for weeks, with 6,032 of 6,332 outstanding albums never attempted even once. `release_dates` had it too (6 processed, 6 skipped, hourly). The fix is `LEFT JOIN enrichment_attempts` + `ORDER BY ea.attempted_at NULLS FIRST`, and stamping **every** id the pass looked at via `record_enrichment_attempts`. Use it for any new sweep.

11. **Last.fm matches names as literal strings, and this library is tagged with typographic punctuation.** U+2019 `’`, U+2026 `…`, U+2010 `‐` are all over the tags; Last.fm's catalogue uses the ASCII forms, so an exact lookup returns *nothing* — indistinguishable from "no data". Measured five for five: `Script for a Jester’s Tear` → 0 tags, `Script for a Jester's Tear` → 10. `ingestion/lastfm.py` now retries every lookup once with `fold_punctuation()` applied, and only when folding actually changes the string. The fold is punctuation-only on purpose — letters keep their diacritics, because Last.fm *does* hold `Motörhead` and `Sigur Rós` under their real names. Effect on the stuck album-tag batch: 0 tagged → 19 of 60 tagged, 111 tags.

12. **A stream that stops is not a stream that finished.** `scripts/playlist_sync_stage.py` in the NAS repo treats an SSE stage as successful only on an explicit `{"done": true}` event, because conflating the two is what let the old pipeline report progress for weeks while finishing nothing. `_make_enrichment_stream` emits it; `/scan/stream` did **not** until 2026-09-16, so `--stage scan` could never report success — a scan that added 9,079 tracks still exited 2, and that single missing key is why the library scan was the one stage never put on cron. If you add a streaming endpoint, emit `done`.

13. **CPU-bound stage bodies must not run on the event loop.** The backend is a single uvicorn worker, so a synchronous stage body blocks `/health` for its whole duration — that is what produced `unhealthy streak=23` at CPU=101% and kept the derived stages off cron. `profiles`, `banger-flags` and the full `rebuild_search_vectors` now run under `asyncio.to_thread`, and `_make_enrichment_stream`'s `progress_callback` is safe to call from a worker thread (it routes through `loop.call_soon_threadsafe`). Verified 2026-09-16 draining 17,390 embeddings + 15,890 profiles: container CPU 773–1001%, `/health` 0.06–0.24s, healthy throughout.

## Testing Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Stats
curl http://localhost:8000/stats

# Generate playlist
curl -X POST http://localhost:8000/generate-playlist \
  -H "Content-Type: application/json" \
  -d '{"prompt": "dark ambient atmospheric", "size": 20}'

# Semantic search
curl "http://localhost:8000/search?query=electronic&limit=10"
```

## Documentation Freshness Policy

**Whenever you make any change — code, config, architecture, dependencies, or infrastructure — update the relevant documentation files in the same commit.**

| What changed | Files to update |
|---|---|
| Scoring weights, trajectory logic, beam search, genre manifold | `AGENTS.md` (V4 Scoring section), `SKILL.md` (current weight state) |
| New module or directory added | `AGENTS.md` (Directory Structure), `README.md` (Directory Structure) |
| API endpoint added or removed | `AGENTS.md` (API Endpoints), `README.md` (API Reference) |
| Infrastructure / deployment change | `AGENTS.md` (Deployment), `CLAUDE.md` (Deploying, Gotchas) |
| Database schema change | `AGENTS.md` (PostgreSQL table list in Architecture diagram) |
| New environment variable | `AGENTS.md` (Environment Variables), `README.md` (Configuration table) |
| Key file renamed or repurposed | `AGENTS.md` (Directory Structure), `CLAUDE.md` (Important Files) |

Do not leave any of these files stale. A reader should be able to understand the current system from the docs alone.

## Algorithm Change Policy

**Any change to scoring, trajectory, genre, or sequencing logic MUST be validated with the evaluation skill before being considered complete.**

This applies to modifications in:
- `service/app/trajectory/` (candidates, sequencer, composer, intent, curves, gravity)
- `service/app/genre/` (manifold, GMS)
- Any scoring weights, penalties, or beam search constraints

Use the `eval-changes` skill (`.windsurf/skills/eval-changes/SKILL.md`) which covers:
1. Restarting the backend
2. Running `./eval_loop.py --multi --max-iter 2` (full 9-prompt batch, ~25 min)
3. Interpreting results against the historical baseline table
4. Applying the keep / revert / iterate decision tree

For a quick sanity check after a focused change: `./eval_loop.py --prompt "..." --max-iter 1` (~3 min).

Do not commit algorithm changes without a passing eval run.

## Architecture Decisions

1. **PostgreSQL + pgvector**: Native vector similarity search, concurrent writes, full SQL analytics
2. **SSE over WebSockets**: Simpler for one-way progress updates
3. **Nuxt server routes as proxy**: Keeps backend URL private, handles CORS
4. **sentence-transformers**: Good balance of quality vs speed for semantic search
5. **Native services over Docker**: Lower overhead on Pi 5; systemd + PM2 for process management
