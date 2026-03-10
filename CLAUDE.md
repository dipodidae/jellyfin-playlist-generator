# Claude Development Guidelines

## Project Context

This is a playlist generator that creates intelligent playlists from a Jellyfin music library using:
- Semantic embeddings for understanding prompts
- Trajectory-based composition for energy flow
- Last.fm data for artist similarity and genre tags
- OpenAI for creative playlist titles

## Code Style

### Python (Backend)
- Python 3.12+ with type hints
- FastAPI for API routes
- Pydantic for data validation
- DuckDB for database (no ORM)
- Use `async`/`await` for I/O operations
- Keep functions focused and small

### TypeScript/Vue (Frontend)
- Nuxt 4 with Vue 3 Composition API
- `<script setup lang="ts">` for components
- Nuxt UI Pro for components
- TailwindCSS for styling
- Use `ref()` and `computed()` for reactivity

## Important Files

### Backend
- `service/app/api/routes.py` - All API endpoints
- `service/app/trajectory/intent.py` - Prompt parsing logic
- `service/app/trajectory/composer.py` - Playlist composition
- `service/app/database.py` - Schema and queries
- `service/app/config.py` - Environment settings

### Frontend
- `frontend/app/pages/index.vue` - Main UI
- `frontend/server/api/` - Nuxt server routes (proxy to backend)
- `frontend/nuxt.config.ts` - Nuxt configuration

## Common Tasks

### Adding a new API endpoint
1. Add route in `service/app/api/routes.py`
2. Add schema in `service/app/api/schemas.py` if needed
3. Add proxy route in `frontend/server/api/`

### Modifying the database schema
1. Update `service/app/database.py` `init_database()`
2. Delete local `data/music.duckdb` to recreate
3. Re-sync from Jellyfin

### Testing locally
```bash
# Backend
cd service && uvicorn app.main:app --reload --port 8100

# Frontend
cd frontend && pnpm dev --port 3100
```

### Deploying
```bash
cd ~/nas
docker compose build playlist-generator-service playlist-generator-frontend
docker compose up -d playlist-generator-service playlist-generator-frontend
docker exec swag nginx -s reload
```

## Gotchas

1. **Nuxt auto-imports**: `defineEventHandler`, `useRuntimeConfig`, etc. are auto-imported - IDE may show errors but they work at runtime

2. **DuckDB connections**: Always close connections after use, DuckDB doesn't handle concurrent writes well

3. **Embedding model**: First load downloads ~90MB model, subsequent loads use cache

4. **SWAG nginx config**: Must be copied to `/config/nginx/proxy-confs/` inside the container, or mounted via docker-compose

5. **Environment variables**: Nuxt uses `NUXT_` prefix for runtime config (e.g., `NUXT_MUSIC_SERVICE_URL`)

## Testing Endpoints

```bash
# Health check
curl http://localhost:8100/health

# Stats
curl http://localhost:8100/stats

# Generate playlist
curl -X POST http://localhost:8100/generate-playlist \
  -H "Content-Type: application/json" \
  -d '{"prompt": "dark ambient atmospheric", "size": 20}'

# Semantic search
curl "http://localhost:8100/search?query=electronic&limit=10"
```

## Architecture Decisions

1. **DuckDB over SQLite**: Better analytics queries, native array support for embeddings
2. **SSE over WebSockets**: Simpler for one-way progress updates
3. **Nuxt server routes as proxy**: Keeps backend URL private, handles CORS
4. **sentence-transformers**: Good balance of quality vs speed for semantic search
5. **No background task persistence**: Simplicity over complexity for now
