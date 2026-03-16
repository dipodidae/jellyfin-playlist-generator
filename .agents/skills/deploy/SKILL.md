---
name: deploy
description: Deploy playlist-generator frontend and/or backend to production. Use when the user asks to deploy, restart services, push changes live, or after completing code changes that need to go to production.
metadata:
  author: tom
  version: "2026.3.16"
---

# Deploying Playlist Generator

This project runs natively on a Raspberry Pi 5 (no Docker). Three services must stay in sync:

| Service | Port | Manager | Command |
|---------|------|---------|---------|
| PostgreSQL 16 + pgvector | 5432 | systemd (system) | `sudo systemctl restart postgresql` |
| Backend (FastAPI/uvicorn) | 8000 | systemd (user) | `systemctl --user restart playlist-generator-backend` |
| Frontend (Nuxt SSR) | 3000 | PM2 | `pm2 restart playlist-generator-frontend` |

SWAG reverse proxy routes `playlist-generator.4eva.me` to port 3000.

## When to deploy what

- **Frontend changes** (`.vue`, `.ts` in `frontend/`, `nuxt.config.ts`): Build then restart frontend
- **Backend changes** (`.py` in `service/`): Restart backend only
- **Both changed**: Deploy both (order doesn't matter, can run in parallel)
- **Database schema changes**: Run migrations first, then restart backend

## Frontend deployment

```bash
# 1. Build (required before restart — PM2 serves the .output/ directory)
cd /home/tom/projects/playlist-generator/frontend
pnpm build

# 2. Restart
pm2 restart playlist-generator-frontend

# 3. Verify
pm2 status playlist-generator-frontend
# Should show: online, uptime increasing
```

The build must succeed before restarting. If the build fails, the old version keeps running.

## Backend deployment

```bash
# 1. Restart
systemctl --user restart playlist-generator-backend

# 2. Wait for startup (~60 seconds on Pi 5 due to sentence-transformers model loading)
# 3. Verify
systemctl --user status playlist-generator-backend --no-pager
# Should show: Active: active (running)

# Or check the health endpoint (only works after model is loaded):
curl -s http://localhost:8000/health
```

**Important**: The backend takes approximately 60 seconds to become ready because it loads the sentence-transformers model (`all-MiniLM-L6-v2`) on startup. The health endpoint will fail until loading completes.

## Verifying deployment

```bash
# Frontend running?
pm2 status playlist-generator-frontend

# Backend running?
systemctl --user status playlist-generator-backend --no-pager

# Backend healthy? (wait 60s after restart)
curl -s http://localhost:8000/health

# Live site accessible?
curl -s -o /dev/null -w "%{http_code}" https://playlist-generator.4eva.me
```

## Configuration files

| Config | Path |
|--------|------|
| Backend systemd unit | `~/.config/systemd/user/playlist-generator-backend.service` |
| Backend env | `/home/tom/projects/playlist-generator/service/.env` |
| Frontend PM2 config | `/home/tom/projects/playlist-generator/frontend/ecosystem.config.cjs` |
| SWAG proxy | `~/nas/swag/playlist-generator.subdomain.conf` |

## Logs

```bash
# Backend logs (live)
journalctl --user -u playlist-generator-backend -f

# Backend logs (last 50 lines)
journalctl --user -u playlist-generator-backend --tail 50 --no-pager

# Frontend logs (live)
pm2 logs playlist-generator-frontend

# PostgreSQL logs
sudo journalctl -u postgresql -f
```

## Rollback

There is no automated rollback. To revert:

1. `git stash` or `git checkout` the previous commit
2. For frontend: `pnpm build && pm2 restart playlist-generator-frontend`
3. For backend: `systemctl --user restart playlist-generator-backend`

## Common issues

- **Frontend shows old content**: The build wasn't run before restart. Run `pnpm build` in `frontend/` first.
- **Backend not responding**: Wait 60 seconds for model loading. Check `journalctl --user -u playlist-generator-backend --tail 20`.
- **CSS missing/broken in production**: Check that `frontend/app/assets/css/main.css` has `@import "tailwindcss"` and `@import "@nuxt/ui"`. Verify CSS bundle size in `.output/public/_nuxt/*.css` is ~170KB (not <5KB).
- **502 from SWAG**: The target service is down. Check both `pm2 status` and `systemctl --user status playlist-generator-backend`.
