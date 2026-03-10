#!/usr/bin/env python3
"""CLI script for running sync operations via the local API."""

import argparse
import json
import logging
import sys
import time
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

API_BASE = "http://localhost:8000"


def api_get(endpoint: str) -> dict:
    """Make a GET request to the API."""
    url = f"{API_BASE}{endpoint}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def api_post(endpoint: str, data: dict = None) -> dict:
    """Make a POST request to the API."""
    url = f"{API_BASE}{endpoint}"
    req = urllib.request.Request(url, method='POST')
    req.add_header('Content-Type', 'application/json')
    body = json.dumps(data or {}).encode() if data else None
    with urllib.request.urlopen(req, body, timeout=300) as resp:
        return json.loads(resp.read().decode())


def stream_sse(endpoint: str) -> dict:
    """Stream SSE events from an endpoint and return final result."""
    url = f"{API_BASE}{endpoint}"
    req = urllib.request.Request(url, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=7200) as resp:  # 2 hour timeout
            result = {}
            for line in resp:
                line = line.decode().strip()
                if line.startswith('data: '):
                    try:
                        event = json.loads(line[6:])
                        msg = event.get('message', '')
                        progress = event.get('progress', 0)
                        current = event.get('current', 0)
                        total = event.get('total', 0)
                        
                        if total > 0:
                            print(f"\r  [{progress:3d}%] {current}/{total} - {msg}", end="", flush=True)
                        else:
                            print(f"\r  {msg}", end="", flush=True)
                        
                        if event.get('stage') == 'complete':
                            result = event.get('stats', {})
                        elif event.get('stage') == 'error':
                            print()
                            logger.error(f"Error: {event.get('error')}")
                            return None
                    except json.JSONDecodeError:
                        pass
            print()  # newline
            return result
    except urllib.error.HTTPError as e:
        if e.code == 409:
            error_data = json.loads(e.read().decode())
            logger.warning(f"Sync already in progress: {error_data.get('detail', {}).get('message', 'unknown')}")
            # Poll for completion
            return poll_sync_status()
        raise


def poll_sync_status() -> dict:
    """Poll sync status until complete."""
    logger.info("Waiting for existing sync to complete...")
    while True:
        status = api_get("/sync/status")
        if not status.get("is_syncing"):
            logger.info("Sync completed")
            return {}
        
        current = status.get("current", 0)
        total = status.get("total", 0)
        msg = status.get("message", "")
        if total > 0:
            pct = int((current / total) * 100)
            print(f"\r  [{pct:3d}%] {current}/{total} - {msg}", end="", flush=True)
        time.sleep(2)


def run_jellyfin_sync(full: bool = False):
    """Run Jellyfin library sync via API."""
    logger.info("Starting Jellyfin sync..." + (" (full)" if full else " (incremental)"))
    endpoint = f"/sync/jellyfin/stream?full={str(full).lower()}"
    stats = stream_sse(endpoint)
    if stats:
        logger.info(f"Jellyfin sync complete: {stats}")
    return stats or {}


def run_lastfm_enrichment():
    """Run Last.fm artist enrichment via API."""
    logger.info("Starting Last.fm artist enrichment (this runs in background)...")
    result = api_post("/sync/lastfm/artists")
    logger.info(f"Last.fm enrichment started: {result}")
    
    # Poll stats to show progress
    logger.info("Monitoring progress (check logs for detailed progress)...")
    prev_count = 0
    stable_count = 0
    while stable_count < 5:  # Wait until count is stable for 10 seconds
        time.sleep(2)
        stats = api_get("/stats")
        current_count = stats.get("artists_with_tags", 0)
        if current_count == prev_count:
            stable_count += 1
        else:
            stable_count = 0
            print(f"\r  Artists enriched: {current_count}", end="", flush=True)
        prev_count = current_count
    print()
    logger.info(f"Last.fm enrichment complete: {prev_count} artists enriched")
    return {"artists_enriched": prev_count}


def run_embedding_generation():
    """Run embedding generation via API."""
    logger.info("Starting embedding generation (this runs in background)...")
    result = api_post("/sync/embeddings")
    logger.info(f"Embedding generation started: {result}")
    
    # Poll stats to show progress
    logger.info("Monitoring progress (check logs for detailed progress)...")
    prev_count = 0
    stable_count = 0
    while stable_count < 5:  # Wait until count is stable for 10 seconds
        time.sleep(2)
        stats = api_get("/stats")
        current_count = stats.get("tracks_with_embeddings", 0)
        if current_count == prev_count:
            stable_count += 1
        else:
            stable_count = 0
            print(f"\r  Tracks embedded: {current_count}", end="", flush=True)
        prev_count = current_count
    print()
    logger.info(f"Embedding generation complete: {prev_count} tracks embedded")
    return {"tracks_embedded": prev_count}


def run_full_pipeline(full_sync: bool = False):
    """Run the complete sync pipeline."""
    logger.info("=" * 60)
    logger.info("PLAYLIST GENERATOR - FULL SYNC PIPELINE")
    logger.info("=" * 60)
    
    # Check API is available
    try:
        api_get("/health")
    except Exception as e:
        logger.error(f"API not available at {API_BASE}: {e}")
        sys.exit(1)
    
    # Step 1: Jellyfin sync
    logger.info("")
    logger.info("STEP 1/3: Jellyfin Library Sync")
    logger.info("-" * 40)
    jellyfin_stats = run_jellyfin_sync(full=full_sync)
    
    # Step 2: Last.fm enrichment
    logger.info("")
    logger.info("STEP 2/3: Last.fm Artist Enrichment")
    logger.info("-" * 40)
    lastfm_stats = run_lastfm_enrichment()
    
    # Step 3: Embedding generation
    logger.info("")
    logger.info("STEP 3/3: Track Embedding Generation")
    logger.info("-" * 40)
    embedding_stats = run_embedding_generation()
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    
    # Get final stats
    final_stats = api_get("/stats")
    logger.info(f"Total tracks: {final_stats.get('tracks', 0)}")
    logger.info(f"Artists enriched: {final_stats.get('artists_with_tags', 0)}/{final_stats.get('artists', 0)}")
    logger.info(f"Tracks embedded: {final_stats.get('tracks_with_embeddings', 0)}/{final_stats.get('tracks', 0)}")


def main():
    parser = argparse.ArgumentParser(description="Playlist Generator CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Full pipeline
    pipeline_parser = subparsers.add_parser("sync-all", help="Run full sync pipeline")
    pipeline_parser.add_argument("--full", action="store_true", help="Force full Jellyfin sync")
    
    # Individual commands
    jellyfin_parser = subparsers.add_parser("sync-jellyfin", help="Sync from Jellyfin only")
    jellyfin_parser.add_argument("--full", action="store_true", help="Force full sync")
    
    subparsers.add_parser("enrich-lastfm", help="Enrich from Last.fm only")
    subparsers.add_parser("generate-embeddings", help="Generate embeddings only")
    subparsers.add_parser("stats", help="Show current stats")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "sync-all":
        run_full_pipeline(full_sync=args.full)
    elif args.command == "sync-jellyfin":
        run_jellyfin_sync(full=args.full)
    elif args.command == "enrich-lastfm":
        run_lastfm_enrichment()
    elif args.command == "generate-embeddings":
        run_embedding_generation()
    elif args.command == "stats":
        stats = api_get("/stats")
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
