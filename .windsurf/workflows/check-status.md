---
description: Check the health and status of all playlist-generator services
---

1. Check all service statuses at once:
// turbo
Run `systemctl --user is-active playlist-generator-backend && pm2 status playlist-generator-frontend && systemctl is-active postgresql`

2. Hit the backend health endpoint:
// turbo
Run `curl -s http://localhost:8000/health | python3 -m json.tool`

3. Check library stats:
// turbo
Run `curl -s http://localhost:8000/stats | python3 -m json.tool`
