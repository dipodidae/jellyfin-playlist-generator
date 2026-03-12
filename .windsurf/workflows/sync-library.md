---
description: Sync the music library (scan files, enrich from Last.fm, generate embeddings and profiles)
---

## Full sync pipeline (scan → Last.fm → embeddings → profiles)

1. Run the full sync via the CLI:
Run `python -m app.cli_v3 sync-all` in the `/home/tom/projects/playlist-generator/service` directory with the virtualenv active (`. .venv/bin/activate`).

Or trigger it via the API (runs in background, check logs for progress):
// turbo
Run `curl -s -X POST http://localhost:8000/scan/stream -H "Content-Type: application/json" -d "{}" | head -50`

## Scan only (incremental)

// turbo
Run `curl -s -X POST http://localhost:8000/scan -H "Content-Type: application/json" -d "{}" | python3 -m json.tool`

## Scan only (full re-scan)

// turbo
Run `curl -s -X POST http://localhost:8000/scan -H "Content-Type: application/json" -d '{"full_scan": true}' | python3 -m json.tool`

## Enrich from Last.fm only

// turbo
Run `curl -s -X POST http://localhost:8000/enrich/lastfm | python3 -m json.tool`

## Generate embeddings only

// turbo
Run `curl -s -X POST http://localhost:8000/enrich/embeddings | python3 -m json.tool`

## Generate semantic profiles only

// turbo
Run `curl -s -X POST http://localhost:8000/enrich/profiles | python3 -m json.tool`
