# Playlist Generator

A prompt-driven playlist generation system that treats every playlist as a **musical journey**, using semantic trajectory mapping, embeddings, and feature-space composition to transform arbitrary natural language prompts into coherent, DJ-quality playlists.

## Architecture

- **Frontend**: Nuxt 4 + Nuxt UI (minimal UI with progress bar)
- **Backend**: Python FastAPI service (music intelligence)
- **Database**: DuckDB (tracks, embeddings, features, similarity graphs)
- **External APIs**: Jellyfin, Last.fm, OpenAI

## Quick Start

```bash
# Copy environment file
cp .env.example .env
# Edit .env with your API keys

# Start services
docker compose up -d

# Access at http://localhost:3000
```

## Development

### Frontend (Nuxt 4)

```bash
cd frontend
pnpm install
pnpm dev
```

### Backend (Python)

```bash
cd service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Project Structure

```
├── frontend/          # Nuxt 4 application
├── service/           # Python FastAPI service
├── docker-compose.yml
└── nginx/             # SWAG proxy config
```

## License

Private project.
# jellyfin-playlist-generator
