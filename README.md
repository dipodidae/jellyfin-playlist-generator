# Playlist Generator

Turn a vibe into a playlist. Describe what you want to hear in plain English and this thing will dig through your local music library, map out a sonic trajectory, and spit out a curated M3U playlist. Works with Jellyfin, Plex, Kodi — anything that reads M3U.

## Prerequisites

- **PostgreSQL 16** with [pgvector](https://github.com/pgvector/pgvector)
- **Python 3.12**
- **Node.js 20+** and [pnpm](https://pnpm.io)
- **PM2** (`npm install -g pm2`)
- [Last.fm API key](https://www.last.fm/api) (free)
- [OpenAI API key](https://platform.openai.com) (for AI-generated playlist titles)

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
# Edit .env — set DATABASE_URL, MUSIC_DIRECTORIES, and API keys

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
OPENAI_API_KEY=...
M3U_OUTPUT_DIR=/path/to/output/playlists
```

## Development

```bash
# Backend (hot-reload)
cd service && source .venv/bin/activate
uvicorn app.main:app --reload --port 8000

# Frontend (hot-reload)
cd frontend
pnpm dev --port 3000
```

## Library Rebuild

After setup, you need to build the library index. This scans your music, pulls metadata from Last.fm, generates embeddings, and builds the clusters the playlist engine uses.

```bash
# Full flush + rebuild (run in screen — can take a while)
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

Safe to interrupt and re-run — it picks up where it left off via checkpoint files in `~/.local/state/playlist-generator/rebuild/`.

## License

Private project.
