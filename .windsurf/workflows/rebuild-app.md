---
description: Rebuild and restart the playlist-generator app (frontend and/or backend)
---

## Rebuild the full app (frontend + backend)

1. Build the frontend:
// turbo
Run `pnpm build` in the `/home/tom/projects/playlist-generator/frontend` directory.

2. Restart the frontend PM2 process:
// turbo
Run `pm2 restart playlist-generator-frontend` in the `/home/tom/projects/playlist-generator/frontend` directory.

3. Restart the backend systemd service:
// turbo
Run `systemctl --user restart playlist-generator-backend`

4. Verify both services are running:
// turbo
Run `pm2 status playlist-generator-frontend && systemctl --user is-active playlist-generator-backend`

## Rebuild frontend only

1. Build the frontend:
// turbo
Run `pnpm build` in the `/home/tom/projects/playlist-generator/frontend` directory.

2. Restart the frontend PM2 process:
// turbo
Run `pm2 restart playlist-generator-frontend`

## Rebuild backend only

1. Restart the backend systemd service:
// turbo
Run `systemctl --user restart playlist-generator-backend`

2. Verify it is active:
// turbo
Run `systemctl --user is-active playlist-generator-backend`
