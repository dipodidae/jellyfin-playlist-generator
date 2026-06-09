# Claude Development Guidelines

## Project Context

This is a playlist generator that creates intelligent playlists from a Jellyfin music library using:
- Semantic embeddings for understanding prompts
- 6D trajectory-based composition (energy, tempo, darkness, texture, era, valence)
- Multi-source enrichment: Last.fm (tags, similarity, play stats), MusicBrainz (IDs), Metal Archives (legitimacy), Discogs (release dates), RYM (ratings, genres, descriptors)
- Curation scoring: banger detection + album legitimacy + RYM cultural signal + studio/live preference
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
- `service/app/trajectory/intent.py` - Prompt parsing, PromptType, GenreMode, 5D waypoints, era mode
- `service/app/trajectory/composer_v4.py` - v4 playlist composition
- `service/app/trajectory/candidates.py` - Candidate pools, curation scoring, adaptive weights
- `service/app/trajectory/sequencer.py` - Beam search, acoustic continuity, era coherence
- `service/app/genre/manifold.py` - Genre Manifold System (GMS)
- `service/app/ingestion/release_dates.py` - Multi-source original release date resolver
- `service/app/ingestion/musicbrainz.py` - MusicBrainz ID resolution
- `service/app/ingestion/metal_archives.py` - Metal Archives album legitimacy
- `service/app/ingestion/version_classifier.py` - Pure studio/live/demo/remix/bonus classifier → (version_type, studio_score); no I/O
- `service/app/ingestion/studio_scores.py` - Backfill `track_studio_scores` from track + album title metadata
- `service/app/enrichment/banger_detector.py` - Banger detection from Last.fm
- `service/app/database_pg.py` - PostgreSQL + pgvector schema, queries, BM25 search vectors
- `service/app/config.py` - Environment settings (base defaults; DB overlays these at runtime)

### Frontend
- `frontend/app/pages/index.vue` - Main UI
- `frontend/app/pages/settings.vue` - In-app settings page (registry-driven)
- `frontend/app/composables/useSettings.ts` - fetch/save/test/OAuth composable
- `frontend/app/types/settings.ts` - TypeScript types for the settings API
- `frontend/server/api/` - Nuxt server routes (proxy to backend)
- `frontend/nuxt.config.ts` - Nuxt configuration

## Common Tasks

### Adding a new API endpoint
1. Add route in `service/app/api/routes.py`
2. Add schema in `service/app/api/schemas.py` if needed
3. Add proxy route in `frontend/server/api/`

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
`cron-sync.sh` runs the full incremental enrichment pipeline (audio included) via
`docker exec playlist-generator curl … /sync/full-pipeline?skip_audio=false`,
gated on a `find -newer` new-file check. Installed in the NAS crontab: `10 */6`
(gated) and `45 3 * * 0 --catch-up` (unconditional), `flock`-guarded, logging to
`~/nas/logs/playlist_sync.log`. It supersedes the manual `sync-new-tracks.sh`,
which still points at the defunct native `:8000` backend.

## Gotchas

1. **DB-backed settings (singleton overlay)**: App-level settings (API keys, enrichment toggles, Jellyfin config, library paths, clustering params) live in the `app_settings` Postgres table. At startup and on every `/settings` save, `settings_store.reload_settings()` overlays the DB values onto the pydantic `settings` singleton via `setattr`. This works because the app runs as a **single uvicorn process** — no cache invalidation, TTL, or inter-process sync is needed. If you ever move to multi-worker mode this assumption breaks. `.env` values for these keys are **seed-only**: they are written to the DB on first boot (when the key is absent) and then ignored; editing `.env` after first boot has no effect on a live instance. Only `DATABASE_URL` and `NUXT_AUTH_*` / `NUXT_SESSION_PASSWORD` remain strictly env-driven.

2. **Nuxt auto-imports**: `defineEventHandler`, `useRuntimeConfig`, etc. are auto-imported - IDE may show errors but they work at runtime

3. **PostgreSQL connections**: Use `psycopg2` connection pool in `database_pg.py`; always return connections to the pool

4. **Embedding model**: First load downloads ~90MB model, subsequent loads use cache (~60s startup on Pi 5)

5. **Backend port**: Production runs on `:8000` (systemd service). Do not hardcode `:8100`.

6. **Environment variables**: Nuxt uses `NUXT_` prefix for runtime config (e.g., `NUXT_BACKEND_URL`)

7. **Docker image bakes the source.** The running stack (`docker-compose.yml`, `unified` profile) builds `service/` into the `playlist-generator` image; only `/music` and `/playlists` are mounted. Algorithm changes are NOT live until you rebuild: `docker compose --profile unified up -d --build app`. The app serves on `127.0.0.1:8080`; the DB (`playlist-generator-db`) is published on `127.0.0.1:5432`. Point `eval_loop.py` at the running app with `BACKEND_URL=http://localhost:8080`.

8. **Valence, instrumentalness, and acousticness are heuristic proxies, not ground-truth.** They are computed from raw audio signal via librosa (valence = 0.5×majorness + 0.3×bpm_norm + 0.2×brightness_norm; instrumentalness ≈ 1 − vocal-band-energy fraction; acousticness ≈ weighted harmonic ratio + low-brightness + low-flatness). They correlate with the intended qualities on average but are not reliable for individual tracks. Do not treat them as authoritative mood/genre labels.

9. **Adding audio metrics requires a full library re-analysis before B/C scoring is meaningful.** The `analyze_library()` function (`audio/analyzer.py`) re-analyzes any track where `valence IS NULL OR mfcc IS NULL`. On a large library (35k+ tracks) this takes several hours. Until the re-analysis is complete, valence trajectory scoring (Phase B) and the expanded acoustic continuity terms in the sequencer (Phase C) silently degrade to no-op for un-analyzed tracks — results will be correct but the new scoring only applies to the analyzed subset. Run `POST /enrich/audio` (or let `cron-sync.sh` handle it) and monitor progress before evaluating Phase B/C behavior.

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
