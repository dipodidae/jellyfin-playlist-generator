# Playlist Generator

Turn a vibe into a playlist. Describe what you want to hear in plain English and this thing will dig through your local music library, map out a sonic trajectory, and spit out a curated M3U playlist. Works with Jellyfin, Plex, Kodi -- anything that reads M3U.

## How It Works

```
prompt --> LLM intent parsing --> 4D trajectory curves --> semantic search (pgvector)
                |                        |                        |
          GPT-4o-mini             energy / tempo /         sentence-transformers
          extracts arc,           darkness / texture        find candidates per
          dimensions,             spline interpolation       trajectory position
          genres, moods                  |                        |
                |                        v                        v
          (keyword fallback      beam search sequencing --> scored playlist
           if no API key)        dual-anchor gravity        with explanations
                                 cluster bridge scoring           |
                                                                  v
                                                            M3U export
```

A user prompt like *"start ambient and dreamy, build through post-rock, end with crushing doom"* goes through this pipeline:

1. **Prompt interpretation** -- GPT-4o-mini parses the prompt into structured parameters: arc type, base dimensions (energy, darkness, tempo, texture), genre hints, artist seeds, mood keywords, avoidances, year range, target duration, dimension weights, and custom trajectory waypoints. Falls back to keyword/regex extraction if no OpenAI key is configured.

2. **Trajectory generation** -- The extracted intent is converted into a 4D trajectory curve (energy, tempo, darkness, texture) using spline interpolation across the playlist length. Seven arc types shape the curve: `rise`, `fall`, `peak`, `steady`, `journey`, `wave`, and `valley`.

3. **Candidate selection** -- A single semantic search against pgvector embeddings produces a global candidate pool. Candidates are then re-scored per trajectory position using the 4D target at each point.

4. **Sequencing** -- Beam search with lookahead optimizes the track order. Dual-anchor gravity wells (prompt centroid + weighted scene centroid) prevent stylistic drift. Auto-bridge scoring rewards tracks that smooth transitions between distant clusters.

5. **Finishing** -- GPT-4o-mini generates a short evocative title and per-track explanations describing why each track was selected and how it fits its position in the arc.

6. **Export** -- The playlist is saved and can be exported as M3U with absolute, relative, or mapped paths.

### AI Features

All three OpenAI integrations use `gpt-4o-mini` and are **optional** -- every one degrades gracefully without an API key:

| Feature | With OpenAI | Fallback |
|---------|-------------|----------|
| Prompt interpretation | Full structured extraction (arc, 4D dimensions, genres, moods, custom waypoints) | Keyword/regex matching against 400+ genre aliases and mood dictionaries |
| Playlist titles | Creative 2-6 word evocative titles | First words of the prompt, title-cased |
| Track explanations | 1-sentence per-track explanation of selection and arc fit | Score-based descriptions from the sequencer |

## Architecture

```
Frontend (Nuxt 4, SSR)  -->  Backend (FastAPI)  -->  PostgreSQL 16 + pgvector
  :3000                        :8000                    :5432
  Nuxt UI v4                   sentence-transformers    tracks, embeddings,
  SSE streaming                GPT-4o-mini              profiles, clusters,
  M3U export UI                4D trajectory engine     audio features
```

### Key Technologies

- **Frontend**: Nuxt 4, Vue 3, Nuxt UI v4, Tailwind CSS v4
- **Backend**: FastAPI, Python 3.12, uvicorn
- **Database**: PostgreSQL 16 + pgvector (vector similarity search)
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2)
- **Audio analysis**: librosa (BPM, loudness, spectral brightness)
- **Tag extraction**: mutagen (audio file metadata)
- **AI**: OpenAI GPT-4o-mini (prompt parsing, titles, explanations)
- **External APIs**: Last.fm (artist tags, similarity data)

### Directory Structure

```
playlist-generator/
  frontend/               Nuxt 4 application
    app/pages/            Single-page UI with streaming progress
    app/components/       34 components (library, playlist, observatory, shared)
    server/api/           Nuxt server routes (proxy to backend)
  service/                FastAPI backend
    app/trajectory/       Intent parsing, curves, gravity, sequencer, composer
    app/genre/            Genre Manifold System (probabilistic genre identity vectors)
    app/clustering/       Scene and artist clustering
    app/audio/            Librosa audio feature analysis
    app/embeddings/       Sentence-transformer embedding generation
    app/profiles/         4D semantic profile generation
    app/export/           M3U and Jellyfin exporters
    app/ingestion/        File scanner, Last.fm enrichment
    app/api/              API routes and Pydantic schemas
```

See `AGENTS.md` for detailed architecture documentation including scoring formulas, adaptive weights, trajectory dimensions, and the full v4 pipeline.

## Features

### Trajectory Engine

The v4 composer sequences playlists along 4D trajectory curves:

- **Energy** -- Intensity and loudness (0-1)
- **Tempo** -- Speed and BPM correlation (0-1)
- **Darkness** -- Mood valence, 1 = darkest (0-1)
- **Texture** -- Density and sonic complexity (0-1)

Seven arc types control the shape: **rise** (building energy), **fall** (winding down), **peak** (build-climax-resolve), **steady** (consistent mood), **journey** (narrative arc with intro/build/climax/denouement), **wave** (oscillating), **valley** (dip and recover).

### Streaming Progress

Playlist generation streams real-time progress via SSE through 8 stages: parsing, trajectory generation, candidate search, matching, composing, metrics, explaining, and titling.

### M3U Export

Three path modes for compatibility with different media servers:

- **Absolute** -- Full filesystem paths
- **Relative** -- Paths relative to the M3U file location
- **Mapped** -- Configurable path prefix replacements (e.g., `/mnt/music` to `/media/music`)

### Observatory

Collection analytics dashboard with taste fingerprints, scene cluster visualization, genre maps, darkness index, audio feature distributions, and generation history.

## Prerequisites

- **PostgreSQL 16** with [pgvector](https://github.com/pgvector/pgvector)
- **Python 3.12**
- **Node.js 20+** and [pnpm](https://pnpm.io)
- **PM2** (`npm install -g pm2`)
- [Last.fm API key](https://www.last.fm/api) (free -- used for artist tags and similarity data)
- [OpenAI API key](https://platform.openai.com) (optional -- used for prompt interpretation, playlist titles, and track explanations; falls back to keyword parsing and heuristics without it)

## Setup

### 1. Database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER playlist WITH PASSWORD 'yourpassword';
CREATE DATABASE playlist_generator OWNER playlist;
\c playlist_generator
CREATE EXTENSION vector;
SQL
```

### 2. Backend

```bash
cd service
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp ../.env.example .env
# Edit .env -- set DATABASE_URL, MUSIC_DIRECTORIES, and API keys

# Initialise the database schema
uvicorn app.main:app --port 8000 &
curl -X POST http://localhost:8000/db/init
```

### 3. Frontend

```bash
cd frontend
pnpm install
pnpm build
pm2 start ecosystem.config.cjs
pm2 save
```

### 4. Environment

Copy `.env.example` to `service/.env` and fill in:

```bash
DATABASE_URL=postgresql://playlist:yourpassword@localhost:5432/playlist_generator
MUSIC_DIRECTORIES=/path/to/your/music   # comma-separated for multiple
LASTFM_API_KEY=...
LASTFM_API_SECRET=...
OPENAI_API_KEY=...                       # optional but recommended
M3U_OUTPUT_DIR=/path/to/output/playlists
```

## Library Rebuild

After setup, you need to build the library index. This scans your music, pulls metadata from Last.fm, generates embeddings, builds semantic profiles, and clusters the collection.

```bash
# Full flush + rebuild (run in screen -- can take a while)
screen -S rebuild ./rebuild-library.sh

# Incremental rebuild (no wipe)
./rebuild-library.sh --no-flush

# Resume from a specific step
./rebuild-library.sh --from=embeddings

# Skip the slow audio analysis pass
./rebuild-library.sh --skip-audio

# All options
./rebuild-library.sh --help
```

The pipeline runs 7 steps: **flush** (truncate tables), **scan** (read music files), **lastfm** (enrich from Last.fm), **embeddings** (sentence-transformers), **profiles** (4D semantic profiles), **clusters** (scene/artist grouping), **audio** (librosa analysis).

Safe to interrupt and re-run -- it picks up where it left off via checkpoint files in `~/.local/state/playlist-generator/rebuild/`.

## Development

```bash
# Backend (hot-reload)
cd service && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend (hot-reload)
cd frontend
pnpm dev --port 3000
```

## API Reference

All endpoints are served from the backend at `:8000`. Interactive docs available at `/docs` (Swagger UI).

### Health and Stats

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/stats` | Library statistics and cold-start quality assessment |
| GET | `/generation-stats` | Playlist generation analytics |
| GET | `/observatory/stats` | Comprehensive collection analytics (cached 1hr) |

### Scan Operations

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scan/status` | Current scan status |
| POST | `/scan` | Trigger library scan (`?full=true` for full rescan) |
| POST | `/scan/stream` | Scan with SSE progress stream |
| GET | `/scan/jobs/active` | Currently active scan job |
| GET | `/scan/jobs/history` | Recent scan jobs |
| GET | `/scan/jobs/{job_id}` | Scan job detail with events |

### Enrichment

Each enrichment type has a fire-and-forget endpoint and an SSE streaming variant (`/stream`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/enrich/lastfm[/stream]` | Last.fm artist tag enrichment |
| POST | `/enrich/embeddings[/stream]` | Sentence-transformer embedding generation |
| POST | `/enrich/profiles[/stream]` | 4D semantic profile generation |
| POST | `/enrich/clusters[/stream]` | Scene and artist clustering |
| POST | `/enrich/audio[/stream]` | Audio feature analysis (BPM, loudness, brightness) |

### Playlist Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/generate-playlist` | Generate playlist (returns result) |
| POST | `/generate-playlist/stream` | Generate with SSE progress (8 stages) |
| GET | `/playlists` | List saved playlists |
| GET | `/playlists/{id}` | Get playlist with full track details |

### Export

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/export/m3u` | Export tracks to M3U content string |
| POST | `/export/m3u/file` | Write M3U file to server disk |
| GET | `/export/m3u/download/{id}` | Download playlist as M3U file |
| GET | `/jellyfin/status` | Check Jellyfin connection |
| POST | `/export/jellyfin` | Push playlist to Jellyfin |

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/search` | Semantic text search against track embeddings |
| GET/POST | `/path-mappings` | List or create path mappings for M3U export |
| DELETE | `/path-mappings/{name}` | Delete a path mapping |
| POST | `/transitions/record` | Record skip/play feedback for transitions |
| POST | `/db/init` | Initialize database schema |
| POST | `/rebuild-search-vectors` | Rebuild full-text search vectors (SSE) |

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string with pgvector |
| `MUSIC_DIRECTORIES` | Yes | Comma-separated paths to music libraries |
| `LASTFM_API_KEY` | Yes | Last.fm API key for tag enrichment |
| `LASTFM_API_SECRET` | Yes | Last.fm API secret |
| `OPENAI_API_KEY` | No | GPT-4o-mini for prompt parsing, titles, and track explanations |
| `M3U_OUTPUT_DIR` | No | Directory for exported M3U files |
| `SCAN_THREADS` | No | Parallel scan threads (default: 8) |
| `NUXT_AUTH_USERNAME` | No | Frontend login username |
| `NUXT_AUTH_PASSWORD` | No | Frontend login password |
| `NUXT_SESSION_PASSWORD` | No | Session encryption key (32+ chars) |

## License

Private project.
