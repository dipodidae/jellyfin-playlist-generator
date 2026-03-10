# Playlist Generator - Agent Guidelines

## Project Overview

A prompt-driven playlist generation system that creates intelligent, curated playlists from a Jellyfin music library using semantic understanding, trajectory-based composition, and AI-generated titles.

**Live URL**: https://playlist-generator.4eva.me
**Local Dev**: http://localhost:3100 (frontend), http://localhost:8100 (backend)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Nuxt 4)                       │
│  - Streaming progress UI via SSE                                │
│  - Sync controls for Jellyfin/Last.fm/Embeddings                │
│  - Nuxt UI Pro components                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  Trajectory │  │  Embeddings │  │      Last.fm            │  │
│  │   Engine    │  │  Generator  │  │    Enrichment           │  │
│  │             │  │             │  │                         │  │
│  │ - Intent    │  │ - Sentence  │  │ - Artist tags           │  │
│  │   parsing   │  │   Transform │  │ - Track tags            │  │
│  │ - Arc types │  │ - Semantic  │  │ - Artist similarity     │  │
│  │ - Waypoints │  │   search    │  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    Playlist Composer                        ││
│  │  - Multi-factor scoring (semantic, artist, genre, energy)  ││
│  │  - Diversity penalties                                      ││
│  │  - Smooth transitions                                       ││
│  │  - AI title generation (OpenAI)                             ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        DuckDB Database                          │
│  tracks, artists, albums, genres, lastfm_tags, track_embeddings │
│  artist_similarity, playlists, playlist_tracks                  │
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
│   │   │   ├── routes.py    # API endpoints
│   │   │   └── schemas.py   # Pydantic models
│   │   ├── trajectory/
│   │   │   ├── intent.py    # Prompt parsing, arc detection
│   │   │   ├── composer.py  # Playlist composition logic
│   │   │   └── title_generator.py  # AI title generation
│   │   ├── embeddings/
│   │   │   └── generator.py # Sentence-transformers embeddings
│   │   ├── ingestion/
│   │   │   ├── jellyfin.py  # Jellyfin sync & playlist creation
│   │   │   └── lastfm.py    # Last.fm enrichment
│   │   ├── database.py      # DuckDB schema & connections
│   │   ├── config.py        # Settings from environment
│   │   └── main.py          # FastAPI app entry
│   ├── Dockerfile
│   └── requirements.txt
├── nginx/                    # SWAG proxy config
├── data/                     # Local DuckDB database
└── docker-compose.yml        # Local development
```

## Key Technologies

- **Frontend**: Nuxt 4, Vue 3, Nuxt UI v4, TailwindCSS v4
- **Backend**: FastAPI, Python 3.12, uvicorn
- **Database**: DuckDB (embedded, file-based)
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2)
- **AI**: OpenAI GPT-4o-mini for title generation
- **External APIs**: Jellyfin, Last.fm

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/stats` | GET | Library statistics |
| `/generate-playlist` | POST | Generate playlist (non-streaming) |
| `/generate-playlist/stream` | POST | Generate with SSE progress |
| `/sync/status` | GET | Check if sync is in progress |
| `/sync/jellyfin` | POST | Sync library from Jellyfin |
| `/sync/jellyfin/stream` | POST | Sync with SSE progress (returns 409 if already syncing) |
| `/sync/lastfm/artists` | POST | Enrich artists from Last.fm |
| `/sync/lastfm/tracks` | POST | Enrich tracks from Last.fm |
| `/sync/embeddings` | POST | Generate track embeddings |
| `/search` | GET | Semantic search tracks |

## Trajectory Engine

The system parses natural language prompts into structured intents:

### Arc Types
- **rise**: Building energy (workout, party warmup)
- **fall**: Decreasing energy (wind down, sleep)
- **peak**: Build → climax → resolve
- **steady**: Consistent mood throughout

### Scoring Factors
1. **Semantic similarity**: Embedding cosine similarity to prompt
2. **Artist similarity**: Last.fm similar artists graph
3. **Genre matching**: Tag overlap scoring
4. **Energy estimation**: Based on genre/tags
5. **Diversity penalty**: Avoid artist repetition

## Environment Variables

```bash
# Jellyfin
JELLYFIN_URL=http://jellyfin:8096
JELLYFIN_API_KEY=your-api-key
JELLYFIN_USER_ID=your-user-id

# Last.fm
LASTFM_API_KEY=your-api-key
LASTFM_API_SECRET=your-api-secret

# OpenAI (for title generation)
OPENAI_API_KEY=your-api-key

# Database
DATABASE_PATH=/data/music.duckdb

# Frontend (Nuxt)
NUXT_MUSIC_SERVICE_URL=http://playlist-generator-service:8000
```

## Development

```bash
# Backend
cd service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8100

# Frontend
cd frontend
pnpm install
pnpm dev --port 3100
```

## Deployment

Deployed via Docker Compose in `~/nas/docker-compose.yml`:
- `playlist-generator-service`: FastAPI backend
- `playlist-generator-frontend`: Nuxt frontend
- SWAG reverse proxy at `playlist-generator.4eva.me`

### Deploying Frontend Changes

```bash
# Build locally
cd frontend && pnpm build

# Copy to container and restart
docker exec playlist-generator-frontend rm -rf /app/.output
docker cp frontend/.output playlist-generator-frontend:/app/
docker restart playlist-generator-frontend
```

### Deploying Backend Changes

The backend service mounts source code from the host via docker-compose volume:
```yaml
volumes:
  - /home/tom/projects/playlist-generator/service/app:/app/app
```

To apply changes, restart the container:
```bash
docker restart playlist-generator-service
```

**Note**: The service takes ~60 seconds to start on Pi 5 due to sentence-transformers model loading.

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

1. **Sync**: Jellyfin → DuckDB (tracks, artists, albums, genres)
2. **Enrich**: Last.fm → DuckDB (tags, artist similarity)
3. **Embed**: tracks → sentence-transformers → DuckDB (embeddings)
4. **Generate**: prompt → intent → candidates → scoring → composition → Jellyfin playlist

## Known Limitations

- Last.fm track enrichment is slow due to API rate limits
- Embedding generation takes ~1 hour for 35k tracks on Pi 5
- Jellyfin sync is blocking (no background task persistence yet)

## Troubleshooting

### CSS Not Loading in Production

If styles don't appear after deployment:
1. Verify `app/assets/css/main.css` has correct imports (not `@tailwind` directives)
2. Check CSS file size in `.output/public/_nuxt/*.css` - should be ~170KB, not <5KB
3. Ensure using `@nuxt/ui` module, not `@nuxt/ui-pro`

### Backend Not Responding After Restart

The sentence-transformers model takes ~60 seconds to load on Pi 5. Wait for health check to pass:
```bash
docker logs playlist-generator-service --tail 5
# Should show: "Application startup complete"
```

### Sync Button Stuck

The `/sync/status` endpoint tracks global sync state. If sync appears stuck:
```bash
curl https://playlist-generator.4eva.me/api/sync/status
```

Returns `{"is_syncing": true/false, ...}`. The frontend polls this on load and shows progress if sync is running.

### Docker BuildKit Errors

If `docker compose build` fails with BuildKit errors:
```bash
DOCKER_BUILDKIT=0 docker compose build <service>
```

Or use the volume mount approach for backend (already configured in docker-compose.yml).
