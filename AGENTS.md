# Playlist Generator - Agent Guidelines

## Project Overview

A prompt-driven playlist generation system that creates intelligent, curated playlists from local music files using semantic understanding, trajectory-based composition, and AI-generated titles. Exports to M3U for use with any media service (Jellyfin, Plex, Kodi, etc.).

**Live URL**: https://playlist-generator.4eva.me
**Local Dev**: http://localhost:3000 (frontend), http://localhost:8000 (backend)

## Architecture (v4)

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Nuxt 4)                       │
│  - Streaming progress UI via SSE                                │
│  - Trajectory visualization                                     │
│  - Track explanations                                           │
│  - M3U export with multiple modes                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                          │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    V4 Playlist Composer                     ││
│  │  1. Single semantic search → global candidate pool          ││
│  │  2. Position-based pools → re-score per trajectory target   ││
│  │  3. Beam search sequencing → path optimization              ││
│  │  4. Dual-anchor gravity → prevent stylistic drift           ││
│  │  5. Auto bridge scoring → smooth cluster transitions        ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │ 5D Trajectories  │  │ Scene Clustering │  │ Audio Analysis │ │
│  │ - Energy         │  │ - Multi-cluster  │  │ - BPM          │ │
│  │ - Tempo          │  │   weights        │  │ - Loudness     │ │
│  │ - Darkness       │  │ - Auto bridges   │  │ - Brightness   │ │
│  │ - Texture        │  │ - Centroids      │  │ - (Optional)   │ │
│  │ - Era (temporal) │  │                  │  │                │ │
│  └──────────────────┘  └──────────────────┘  └────────────────┘ │
│                              │                                   │
│  ┌──────────────────┐  ┌──────────────────────────────────────┐ │
│  │ Curation Signals │  │ Release Date Resolution              │ │
│  │ - Banger detect  │  │ - Discogs / MusicBrainz / file meta  │ │
│  │ - MA legitimacy  │  │ - Multi-source cross-reference       │ │
│  │ - RYM culture    │  │ - Confidence scoring                 │ │
│  └──────────────────┘  └──────────────────────────────────────┘ │
│                              │                                   │
│  ┌──────────────────┐  ┌──────────────────────────────────────┐ │
│  │ Observability    │  │         M3U Exporter                 │ │
│  │ - Generation log │  │ - Absolute / Relative / Mapped paths │ │
│  │ - Track memory   │  │ - Configurable path mappings         │ │
│  │ - TTL caching    │  │                                      │ │
│  └──────────────────┘  └──────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PostgreSQL + pgvector                         │
│  tracks, track_files, artists, albums, track_embeddings,        │
│  track_profiles (4D), scene_clusters, artist_clusters,          │
│  track_audio_features (BPM/loudness/brightness + valence/       │
│    danceability/pulse_clarity/onset_rate/instrumentalness/      │
│    acousticness/mfcc — migration 013),                          │
│  track_studio_scores (version_type, studio_score — mig. 014),  │
│  track_usage, playlist_generation_log,                          │
│  track_genre_probabilities, genre_manifold, track_banger_flags, │
│  album_legitimacy, rym_albums, album_release_dates,             │
│  lastfm_stats, musicbrainz_artists, musicbrainz_albums,         │
│  app_settings                                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
playlist-generator/
├── frontend/                 # Nuxt 4 application
│   ├── app/
│   │   ├── pages/
│   │   │   └── index.vue    # Main UI with streaming progress
│   │   └── app.vue          # Root layout
│   ├── server/api/          # Nuxt server routes (proxy to backend)
│   └── nuxt.config.ts
├── service/                  # FastAPI backend
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes_v3.py # v3 API endpoints (PostgreSQL)
│   │   │   ├── routes.py    # Legacy API (DuckDB)
│   │   │   └── schemas.py   # Pydantic models
│   │   ├── trajectory/
│   │   │   ├── intent.py    # Prompt parsing, 5D waypoints, dimension weights, era mode
│   │   │   ├── curves.py    # Spline interpolation, trajectory curves (v4, 5D with era)
│   │   │   ├── gravity.py   # Dual-anchor gravity wells (v4)
│   │   │   ├── candidates.py # Position-based candidate pools, curation scoring (v4)
│   │   │   ├── sequencer.py # Beam search with constraints, era coherence (v4)
│   │   │   ├── composer_v4.py # Main v4 orchestration
│   │   │   ├── composer.py  # Legacy composition (v3)
│   │   │   └── title_generator.py  # AI title generation
│   │   ├── genre/
│   │   │   └── manifold.py  # Genre Manifold System (GMS): probabilistic genre identity vectors
│   │   ├── clustering/
│   │   │   └── scenes.py    # Multi-cluster artist grouping (v4)
│   │   ├── audio/
│   │   │   └── analyzer.py  # Librosa audio features (v4, optional)
│   │   ├── embeddings/
│   │   │   └── generator.py # Sentence-transformers embeddings
│   │   ├── ingestion/
│   │   │   ├── scanner.py   # File-based library scanner
│   │   │   ├── lastfm.py    # Last.fm enrichment
│   │   │   ├── musicbrainz.py # MusicBrainz ID resolution + release dates
│   │   │   ├── metal_archives.py # Metal Archives album legitimacy
│   │   │   ├── discogs.py   # Discogs release date resolution
│   │   │   ├── release_dates.py  # Multi-source original release date resolver
│   │   │   ├── version_classifier.py # Pure studio/live/demo/remix classifier → (version_type, studio_score)
│   │   │   ├── studio_scores.py  # Backfill track_studio_scores from title/album metadata
│   │   │   └── jellyfin_dates.py # Push resolved original release dates to Jellyfin (path-based album matching, locked fields)
│   │   ├── enrichment/
│   │   │   ├── banger_detector.py # Composite banger detection (DB orchestration)
│   │   │   └── banger_scoring.py   # Pure banger scoring math (popularity/sonic/replay)
│   │   ├── profiles/
│   │   │   └── generator.py # Semantic track profiles (4D: energy, darkness, tempo, texture) + RYM data
│   │   ├── export/
│   │   │   └── m3u.py       # M3U playlist exporter
│   │   ├── migrations/      # Database migrations
│   │   ├── database_pg.py   # PostgreSQL + pgvector
│   │   ├── observability.py # Logging, caching, cold start (v4)
│   │   ├── config.py        # Settings from environment
│   │   └── main.py          # FastAPI app entry
│   ├── Dockerfile
│   └── requirements.txt
├── data/                     # Misc data files
├── eval_runs/                # Evaluation run outputs (gitignored)
└── eval_loop.py              # Multi-prompt evaluation loop
```

## Key Technologies

- **Frontend**: Nuxt 4, Vue 3, Nuxt UI v4, TailwindCSS v4
- **Backend**: FastAPI, Python 3.12, uvicorn
- **Database**: PostgreSQL 16 + pgvector (vector similarity search)
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2)
- **Tag Extraction**: mutagen (audio file metadata)
- **AI**: OpenAI GPT-4o-mini for title generation
- **External APIs**: Last.fm, Discogs, MusicBrainz, Metal Archives

## API Endpoints (v3)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/stats` | GET | Library statistics |
| `/scan/status` | GET | Check scan progress |
| `/scan` | POST | Trigger library scan |
| `/scan/stream` | POST | Scan with SSE progress |
| `/enrich/musicbrainz` | POST | Resolve MusicBrainz IDs for artists & albums |
| `/enrich/lastfm` | POST | Enrich artists from Last.fm |
| `/enrich/metal-archives` | POST | Enrich album legitimacy from Metal Archives |
| `/enrich/release-dates` | POST | Resolve true original release dates |
| `/enrich/embeddings` | POST | Generate track embeddings |
| `/enrich/profiles` | POST | Generate semantic profiles |
| `/enrich/clusters` | POST | Generate scene clusters |
| `/enrich/banger-flags` | POST | Compute banger detection flags |
| `/enrich/audio` | POST | Analyze audio features |
| `/enrich/genre-manifold` | POST | Build genre probability vectors |
| `/enrich/rym` | POST | Scrape RateYourMusic album data |
| `/rebuild-search-vectors` | POST | Rebuild BM25 search vectors |
| `/sync/full-pipeline` | POST | Incremental scan + all enrichment (SSE) |
| `/path-mappings` | GET/POST | Manage path mappings |
| `/path-mappings/{name}` | DELETE | Delete path mapping |
| `/generate-playlist` | POST | Generate playlist |
| `/playlists` | GET | List generated playlists |
| `/playlists/{id}` | GET | Get playlist details |
| `/export/m3u` | POST | Export tracks to M3U content |
| `/export/m3u/file` | POST | Export to M3U file on server |
| `/export/m3u/download/{id}` | GET | Download playlist as M3U |
| `/search` | GET | Semantic search tracks |
| `/db/init` | POST | Initialize database schema |
| `/settings` | GET | Return registry + current values (secrets masked) |
| `/settings` | PUT | Update changed settings (masked/blank secrets ignored) |
| `/settings/test/{group}` | POST | Credential reachability check — `group` ∈ `lastfm`, `openai`, `discogs`, `jellyfin`; returns `{ok, message}` |
| `/settings/discogs/oauth/start` | POST | Begin Discogs 3-legged OAuth; returns `{authorize_url}` |
| `/settings/discogs/oauth/callback` | GET | Complete Discogs OAuth, store permanent access token, redirect to `/settings` |
| `/jellyfin/fix-release-dates` | POST | Push resolved original release dates onto matching Jellyfin albums; sets PremiereDate + ProductionYear and locks those fields (SSE progress) |

## V4 Trajectory Engine

The v4 system uses a sophisticated multi-stage pipeline:

### Arc Types
- **rise**: Building energy (workout, party warmup)
- **fall**: Decreasing energy (wind down, sleep)
- **peak**: Build → climax → resolve (60% build, 15% peak, 25% resolve)
- **steady**: Consistent mood throughout
- **journey**: Narrative arc with intro/build/climax/denouement
- **wave**: Oscillating energy pattern

### 6D Trajectory Dimensions
- **Energy**: Intensity/loudness (0-1)
- **Tempo**: Speed/BPM correlation (0-1)
- **Darkness**: Mood valence (0-1, 1=darkest)
- **Texture**: Density + complexity (0-1)
- **Era**: Temporal position (0-1), active only when `era_mode` ≠ "none"
- **Valence**: Perceived positivity/mood brightness (0-1, 1=most uplifting); opt-in like era — steered by mood words in the prompt (e.g. "uplifting", "melancholic"). Sourced from `track_audio_features.valence` (heuristic proxy: 0.5×majorness + 0.3×bpm_norm + 0.2×brightness_norm). Its `DimensionWeights.valence` is 0.0 by default and raised to ~0.25 when `parse_valence_target` detects relevant mood words.

### Era Modes (Temporal Trajectory)
- **none**: No temporal trajectory (default)
- **chronological**: Older → newer progression
- **reverse**: Newer → older progression
- **locked**: Tight era window (narrow year range)
- **arc**: Follows the arc shape through time

### V4 Scoring Components (Normalized 0-1)
Weights are adaptive per `PromptType` (see `candidates.py → get_adaptive_weights()`):
```python
# Candidate total_score (used in beam search)
total_score = (
    semantic_score   * w_semantic   +  # GENRE=0.29 / ARC=0.10 / MIXED=0.28
    trajectory_score * w_trajectory +  # GENRE=0.15 / ARC=0.45 / MIXED=0.26
    genre_match_score * w_genre    +   # GENRE=0.23 / ARC=0.16 / MIXED=0.15
    curation_score   * w_curation  +   # GENRE=0.08 / ARC=0.04 / MIXED=0.06 (+ impact_pref boost)
    year_score                     +   # soft bonus/penalty for year-range match (verified > file)
    - gravity_penalty * w_gravity  +   # all types: 0.15
    - duration_penalty * w_duration    # all types: 0.10
    - tourist_match_penalty            # 0.50 when genre hint present + zero genre match
    - negative_constraint_penalty      # avoid_keywords violations (checks genres + RYM data)
    - usage_penalty                    # time-decayed track reuse penalty
    - studio_penalty * _w_studio       # _w_studio=0.08; penalizes (1-studio_score) by default,
                                       # or studio_score when prefer_live (inverted for live/acoustic prompts)
)

# trajectory_score also includes a valence term when DimensionWeights.valence > 0
# (opt-in: parse_valence_target raises it to ~0.25 when mood words are detected in the prompt)

# curation_score = banger_score * w1 + album_legitimacy * w2 + rym_signal * w3
# (graceful degradation when data sources are partially available)

# Beam extension score (sequencer)
extension_score = (
    candidate.total_score +
    transition_score * 0.40 +
    lookahead * 0.30 +
    bridge_bonus * 0.05 -
    direction_penalty -
    genre_drift_penalty               # GMS beam-level drift (when genre_probs available)
)

# transition_score (acoustic continuity) — graceful degradation when fields are NULL
# base terms (require bpm_norm/loudness_norm/brightness_norm):
#   bpm_score (w=0.35), loudness_score (w=0.30), brightness_score (w=0.15)
# added when available:
#   danceability delta (w=0.10), pulse_clarity delta (w=0.05),
#   mfcc_continuity — euclidean distance of 12-d MFCC timbre vectors (w=0.10),
#   vocal_jump_score — instrumentalness jump penalty (w=0.10)
# all weights renormalized to sum=1 so missing terms don't deflate the score
```

### Key V4 Features
- **Single semantic search**: Query once, re-score per position
- **Position-based pools**: Candidate pool per track position
- **Dual-anchor gravity**: Prompt + weighted scene centroid
- **Beam search**: Path optimization with lookahead
- **Auto bridges**: Tracks connecting distant clusters
- **Playlist memory**: Time-decayed track usage penalty
- **Adaptive weights**: Per-`PromptType` scoring weights (GENRE / ARC / MIXED)
- **Genre-aware admissibility**: The candidate gate (`is_admissible()` in `admission.py`) admits a track when it clears the semantic floor **OR** is a strong primary-genre match (`genre_match_score ≥ 0.50`). This lets the genre/tag secondary pools (which carry a low baseline `semantic_score`) actually contribute, widening artist diversity on genre and sparse-genre prompts.
- **Artist + album caps**: `max_artist_count=4` and `max_album_count=2` per playlist, plus **absolute** `hard_max_artist_count`/`hard_max_album_count` ceilings derived from playlist size (artist ≈ 25%, album ≈ 15%, set by the composer) that the relaxation ladder can **never** exceed. The fallback ladder no longer relaxes the artist cap to unbounded (`999`); when diversity is exhausted the playlist returns short rather than dumping one artist/album.
- **Near-duplicate dedup**: Candidate pool is collapsed by `(normalize_artist, normalize_title)` (`textnorm.py`), so re-imports and `(live)`/`(demo)`/`(remix)`/`(... session)`/`(single version)` variants count as one song. The tie-breaking order is: (1) highest `studio_score` (studio cut preferred), or lowest when `prefer_live` is active; (2) highest `total_score`. A signature backstop in the beam search (`BeamPath.signatures`) guards against any that slip through.
- **Studio/live preference**: `version_classifier.py` classifies each track as `studio` (score 1.0), `live` (0.35), `demo` (0.50), `session` (0.55), `acoustic` (0.65), `remix` (0.70), or `bonus` (0.75), stored in `track_studio_scores`. By default a soft penalty (`_w_studio=0.08`) down-ranks non-studio cuts; `detect_prefer_live()` inverts it for prompts containing live/acoustic/unplugged cues.
- **Per-segment genre waypoints**: For multi-genre journeys, the LLM emits per-waypoint `genres`; `build_phase_queries()` retrieves each segment's genre, a DB genre pool guarantees those styles are present, and `generate_position_pools()` scores `genre_match` per position against that position's segment genres (`PlaylistIntent.segment_genres_at()`) — so "ambient → doom" actually opens ambient and closes doom.
- **Genre Manifold System (GMS)**: Probabilistic genre identity vectors (`genre_probs`) loaded from `track_genre_probabilities` table; used for `compute_genre_probability_score()` (replaces Jaccard when available), `compute_genre_drift_penalty()` in beam search, STRICT mode hard filter, and hybrid query embedding construction
- **Curation scoring**: Combined signal from banger detection (composite: Last.fm popularity + sonic audio profile + replay ratio), Metal Archives album legitimacy (percentile-normalized), and RYM album ratings; weighted by `impact_preference`
- **RYM genre enrichment**: High-resolution RYM genres supplement Jaccard genre matching and BM25 search vectors; RYM descriptors feed negative constraint checking
- **True original release dates**: Multi-source (Discogs/MusicBrainz/file) verified dates used for year scoring (stronger signal than file metadata) and 5D era trajectory dimension
- **BM25 search vectors**: Composed of track title + artist (Weight A), file genres + Last.fm tags + RYM genres (Weight B), RYM descriptors (Weight C)

## Environment Variables

```bash
# Database (PostgreSQL + pgvector) - native install on localhost
DATABASE_URL=postgresql://playlist:password@localhost:5432/playlist_generator

# Music Library
MUSIC_DIRECTORIES=/mnt/drive-next/Music
SCAN_THREADS=4

# M3U Export
M3U_OUTPUT_DIR=/home/tom/projects/playlist-generator/playlists

# Last.fm
LASTFM_API_KEY=your-api-key
LASTFM_API_SECRET=your-api-secret

# OpenAI (for title generation)
OPENAI_API_KEY=your-api-key

# Discogs (for original release date resolution)
DISCOGS_TOKEN=your-discogs-personal-access-token
```

### DB-backed settings (seed-only env vars)

`DATABASE_URL` and `AUTH_*` credentials are the only purely env-driven settings. Every other app-level key listed above (`LASTFM_API_KEY`, `OPENAI_API_KEY`, `DISCOGS_TOKEN`, `MUSICBRAINZ_CONTACT`, `JELLYFIN_*`, scan/cluster params, etc.) is now stored in the `app_settings` Postgres table and managed in-app at `/settings`.

On **first boot** the app seeds `app_settings` with any matching env var that is not already in the table (idempotent — it never overwrites an existing row). After that the DB is the source of truth; editing `.env` for these keys has no effect on a running instance. Use the `/settings` page to update them live.

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

## Development

```bash
# Backend (already running as systemd service)
systemctl --user status playlist-generator-backend

# For development with hot reload:
cd service
source .venv/bin/activate
systemctl --user stop playlist-generator-backend  # stop production
uvicorn app.main:app --reload --port 8000

# Frontend (already running via PM2)
pm2 status

# For development with hot reload:
cd frontend
pm2 stop playlist-generator-frontend  # stop production
pnpm dev --port 3000
```

## Deployment (Native Services)

Services run natively on the host (no Docker), managed by systemd and PM2:

| Service | Port | Management |
|---------|------|------------|
| PostgreSQL 16 + pgvector | 5432 | `systemctl status postgresql` |
| Backend (FastAPI) | 8000 | `systemctl --user status playlist-generator-backend` |
| Frontend (Nuxt SSR) | 3000 | `pm2 status playlist-generator-frontend` |

SWAG reverse proxy (in `~/nas/docker-compose.yml`) routes `playlist-generator.4eva.me` → `172.30.0.1:3000`

### Deploying Frontend Changes

```bash
cd frontend
pnpm build
pm2 restart playlist-generator-frontend
```

### Deploying Backend Changes

```bash
systemctl --user restart playlist-generator-backend
```

**Note**: The service takes ~60 seconds to start on Pi 5 due to sentence-transformers model loading.

### Service Configuration Files

- **Backend systemd**: `~/.config/systemd/user/playlist-generator-backend.service`
- **Backend env**: `/home/tom/projects/playlist-generator/service/.env`
- **Frontend PM2**: `/home/tom/projects/playlist-generator/frontend/ecosystem.config.cjs`
- **SWAG proxy**: `~/nas/swag/playlist-generator.subdomain.conf`

### Logs

```bash
# Backend
journalctl --user -u playlist-generator-backend -f

# Frontend
pm2 logs playlist-generator-frontend

# PostgreSQL
sudo journalctl -u postgresql -f
```

### Persistence Across Reboots

All services auto-start on boot:
- PostgreSQL: `systemctl enable postgresql`
- Backend: `systemctl --user enable playlist-generator-backend` + `loginctl enable-linger tom`
- Frontend: PM2 startup script (`pm2 startup` + `pm2 save`)

### Frontend Auth

Uses `nuxt-auth-utils` with session-based auth:
- `NUXT_AUTH_USERNAME` / `NUXT_AUTH_PASSWORD` - login credentials
- `NUXT_SESSION_PASSWORD` - must be 32+ characters for session encryption

### Critical: Nuxt UI v4 + Tailwind CSS v4

The frontend uses **Nuxt 4** with **@nuxt/ui v4** (not ui-pro). CSS setup:

```css
/* app/assets/css/main.css */
@import "tailwindcss";
@import "@nuxt/ui";
```

```ts
// nuxt.config.ts
modules: ['@nuxt/ui'],
css: ['~/assets/css/main.css'],
```

**DO NOT use `@nuxt/ui-pro`** - it requires Nuxt 3 and has different CSS handling.

## Data Flow

1. **Scan**: Music files → PostgreSQL (tracks, track_files, artists, albums, genres)
2. **MusicBrainz**: Resolve artist/album MBIDs for downstream enrichment
3. **Last.fm**: Enrich artists with tags, similarity; fetch per-track play/listener counts
4. **Metal Archives**: Scrape album ratings → album_legitimacy (match_confidence ≥ 0.7)
5. **Release Dates**: Multi-source (Discogs/MusicBrainz/file) → album_release_dates (true original year)
6. **Embed**: tracks + RYM data → sentence-transformers → pgvector (embeddings)
7. **Profile**: tags → heuristics → PostgreSQL (energy, darkness, tempo, texture)
8. **Cluster**: artist embeddings → KMeans → scene_clusters, artist_clusters
9. **Banger Detection**: composite → track_banger_flags. Three groups (weights renormalized over those present): popularity 0.45 (Last.fm within-artist rank + global percentile), sonic 0.35 (track_audio_features energy/dance/loudness/tempo/valence; valence dropped for dark genres), replay 0.20 (log playcount/listeners percentile)
10. **Genre Manifold**: kNN voting → track_genre_probabilities + genre centroids
11. **Search Vectors**: BM25 tsvector (title/artist/genres + Last.fm tags + RYM genres/descriptors)
12. **Audio Analysis** (`/enrich/audio`): librosa → BPM, loudness, brightness + valence, danceability, pulse_clarity, onset_rate, instrumentalness, acousticness, MFCC timbre → track_audio_features (migration 013; re-runs for rows missing new metrics)
13. **Studio Scores** (`ingestion/studio_scores.py backfill_studio_scores()`): title + album cues → (version_type, studio_score) → track_studio_scores (migration 014; fast — pure metadata, no I/O)
14. **Generate (v4)**: prompt → 6D trajectory → semantic+BM25 search → curation + studio scoring → position pools → beam search → M3U export

### Quick Sync: Add & Analyze New Tracks

To incrementally scan for new music files and run all analysis in one command:

```bash
curl -N -X POST 'http://localhost:8000/sync/full-pipeline'
```

This streams SSE progress through: scan → MusicBrainz → Last.fm → Metal Archives → release dates → embeddings → profiles → clusters → banger flags → audio (optional) → search vectors.
Each step is incremental — only new/unprocessed tracks are touched. Options:

- `?skip_lastfm=true` — skip Last.fm enrichment (faster, avoids API rate limits)
- `?skip_audio=false` — include audio analysis (slow on Pi, off by default)

## Known Limitations

- Last.fm track enrichment is slow due to API rate limits
- Embedding generation takes ~1 hour for 35k tracks on Pi 5
- Initial file scan can take 10-30 minutes for large libraries

## Troubleshooting

### CSS Not Loading in Production

If styles don't appear after deployment:
1. Verify `app/assets/css/main.css` has correct imports (not `@tailwind` directives)
2. Check CSS file size in `.output/public/_nuxt/*.css` - should be ~170KB, not <5KB
3. Ensure using `@nuxt/ui` module, not `@nuxt/ui-pro`

### Backend Not Responding After Restart

The sentence-transformers model takes ~60 seconds to load on Pi 5. Wait for health check to pass:
```bash
journalctl --user -u playlist-generator-backend --tail 10
# Should show: "Application startup complete"
```

### Sync Button Stuck

The `/sync/status` endpoint tracks global sync state. If sync appears stuck:
```bash
curl https://playlist-generator.4eva.me/api/sync/status
```

Returns `{"is_syncing": true/false, ...}`. The frontend polls this on load and shows progress if sync is running.
