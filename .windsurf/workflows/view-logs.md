---
description: View live or recent logs for the playlist-generator frontend and/or backend
---

## View all logs (last 100 lines each)

1. Show recent backend logs:
// turbo
Run `journalctl --user -u playlist-generator-backend -n 100 --no-pager`

2. Show recent frontend logs:
// turbo
Run `pm2 logs playlist-generator-frontend --lines 100 --nostream`

## Tail backend logs live

1. Stream backend logs:
Run `journalctl --user -u playlist-generator-backend -f`

## Tail frontend logs live

1. Stream frontend logs:
Run `pm2 logs playlist-generator-frontend`
