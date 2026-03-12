# Playlist Generator

A prompt-driven playlist generation system that treats every playlist as a **musical journey**, using semantic trajectory mapping, embeddings, and feature-space composition to transform arbitrary natural language prompts into coherent, DJ-quality playlists. Exports to M3U for use with Jellyfin, Plex, Kodi, or any media player.

## Architecture

| Layer | Stack |
|-------|-------|
| Frontend | Nuxt 4, Vue 3, Nuxt UI v4, TailwindCSS v4 |
| Backend | Python 3.12, FastAPI, uvicorn |
| Database | PostgreSQL 16 + pgvector |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Tag extraction | mutagen |
| Audio analysis | librosa (optional, for BPM/loudness/brightness) |
| AI titles | OpenAI GPT-4o-mini |
| External APIs | Last.fm |

Services run natively on the host, managed by **systemd** (backend) and **PM2** (frontend).

## Project Structure

```
├── frontend/          # Nuxt 4 SSR application
│   └── app/pages/     # Main UI
├── service/           # FastAPI backend
│   ├── app/           # Python application
│   └── requirements.txt
├── nginx/             # Reverse proxy config (SWAG)
├── rebuild-library.sh # Full library flush + rebuild script
└── .env.example       # Environment variable reference
```

## Prerequisites

- **PostgreSQL 16** with the [pgvector](https://github.com/pgvector/pgvector) extension
- **Python 3.12**
- **Node.js 20+** and [pnpm](https://pnpm.io)
- **PM2** (`npm install -g pm2`)
- Last.fm API key (free at https://www.last.fm/api)
- OpenAI API key (for AI playlist title generation)

## Installation

### 1. Database

```bash
# Create database and user
sudo -u postgres psql <<'SQL'
CREATE USER playlist WITH PASSWORD 'yourpassword';
CREATE DATABASE playlist_generator OWNER playlist;
\c playlist_generator
CREATE EXTENSION vector;
SQL

# Initialise schema via the API (once backend is running)
curl -X POST http://localhost:8000/db/init
```

### 2. Backend

```bash
cd service

# Create and activate virtualenv
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp ../.env.example .env
# Edit .env — set DATABASE_URL, MUSIC_DIRECTORIES, API keys

# Run in development (hot-reload)
uvicorn app.main:app --reload --port 8000
```

#### Run as a systemd service (production)

```bash
# Create service file
cat > ~/.config/systemd/user/playlist-generator-backend.service <<EOF
[Unit]
Description=Playlist Generator Backend
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/path/to/playlist-generator/service
ExecStart=/path/to/playlist-generator/service/.venv/bin/uvicorn \
    app.main:app --host 127.0.0.1 --port 8000 --workers 4 --timeout-keep-alive 30
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now playlist-generator-backend
```

### 3. Frontend

```bash
cd frontend

# Install dependencies
pnpm install

# Run in development
pnpm dev --port 3000

# Build and run in production via PM2
pnpm build
pm2 start ecosystem.config.cjs
pm2 save
```

### 4. Environment Variables

Copy `.env.example` to `service/.env` and configure:

```bash
# Required
DATABASE_URL=postgresql://playlist:yourpassword@localhost:5432/playlist_generator
MUSIC_DIRECTORIES=/path/to/your/music          # Comma-separated for multiple paths

# API keys
LASTFM_API_KEY=your_lastfm_api_key
LASTFM_API_SECRET=your_lastfm_api_secret
OPENAI_API_KEY=your_openai_api_key             # For AI playlist title generation

# Export
M3U_OUTPUT_DIR=/path/to/output/playlists

# Optional tuning
SCAN_THREADS=4
```

### 5. First-Run Library Build

Once services are running, initialise the database schema and build the library:

```bash
# Initialise schema
curl -X POST http://localhost:8000/db/init

# Full library build (scan → Last.fm → embeddings → profiles → clusters → audio)
# Run in screen so it survives disconnects — takes 30 min to several hours
screen -S rebuild ./rebuild-library.sh
```

See [Library Management](#library-management) for resume and incremental rebuild options.

## Library Management

### Full Flush & Rebuild

`rebuild-library.sh` runs the complete enrichment pipeline in order:

| Step | What it does |
|------|-------------|
| `flush` | TRUNCATE all library tables (preserves `path_mappings` and `generated_playlists`) |
| `scan` | Scan `MUSIC_DIRECTORIES` and import track metadata |
| `lastfm` | Enrich artist tags, similar artists, and play counts from Last.fm |
| `embeddings` | Generate sentence-transformer embeddings for all tracks |
| `profiles` | Generate 4D semantic profiles (energy / tempo / darkness / texture) |
| `clusters` | Build scene and artist clusters for diversity scoring |
| `audio` | Analyse audio features (BPM, loudness, spectral centroid) via librosa |

Each step writes a checkpoint file on success. **Re-running the script resumes from the last incomplete step** — safe to interrupt and re-run at any time.

```bash
# Run inside a screen session so it survives disconnects
screen -S rebuild ./rebuild-library.sh

# Reattach if disconnected
screen -r rebuild
```

#### Common invocations

```bash
# Full flush + rebuild (default)
./rebuild-library.sh

# Incremental rebuild — re-enrich without wiping the database
./rebuild-library.sh --no-flush

# Re-run from a specific step (clears that step and all later ones)
./rebuild-library.sh --from=embeddings

# Force re-run everything, skip the long audio analysis
./rebuild-library.sh --force --skip-audio

# Show help / all options
./rebuild-library.sh --help
```

#### Checkpoint files

Checkpoints are stored in `~/.local/state/playlist-generator/rebuild/` (one `<step>.done` file per completed step). Delete a file or use `--from=STEP` to re-run a step.

#### Audio analysis note

The `audio` step kicks off a **background job** in the FastAPI backend (it can take hours for large libraries). The script marks the step done and prints monitoring instructions — subsequent runs only process tracks not yet analysed. Monitor with:

```bash
journalctl --user -u playlist-generator-backend -f
```

## License

Private project.
