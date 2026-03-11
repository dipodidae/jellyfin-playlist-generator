#!/usr/bin/env python3
"""CLI for v3 architecture (file-based, PostgreSQL+pgvector)."""

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def init_db():
    """Initialize database connection."""
    from app.database_pg import init_database
    init_database()


async def cmd_scan(args):
    """Scan music library."""
    from app.ingestion.scanner import scan_library
    
    init_db()
    
    def progress(current, total, message):
        if total > 0:
            pct = int((current / total) * 100)
            print(f"\r  [{pct:3d}%] {current}/{total} - {message}", end="", flush=True)
        else:
            print(f"\r  {message}", end="", flush=True)
    
    logger.info(f"Scanning music library {'(full)' if args.full else '(incremental)'}...")
    stats = await scan_library(progress_callback=progress, full_scan=args.full)
    print()
    logger.info(f"Scan complete: {json.dumps(stats, indent=2)}")


async def cmd_enrich_lastfm(args):
    """Enrich artists from Last.fm."""
    from app.ingestion.lastfm import enrich_artists_from_lastfm
    
    init_db()
    
    logger.info("Enriching artists from Last.fm...")
    stats = await enrich_artists_from_lastfm()
    logger.info(f"Enrichment complete: {json.dumps(stats, indent=2)}")


async def cmd_generate_embeddings(args):
    """Generate track embeddings."""
    from app.embeddings.generator import generate_track_embeddings
    
    init_db()
    
    logger.info("Generating embeddings...")
    stats = await generate_track_embeddings()
    logger.info(f"Embedding generation complete: {json.dumps(stats, indent=2)}")


async def cmd_generate_profiles(args):
    """Generate semantic track profiles."""
    from app.profiles.generator import generate_profiles
    
    init_db()
    
    def progress(current, total, message):
        if total > 0:
            pct = int((current / total) * 100)
            print(f"\r  [{pct:3d}%] {current}/{total} - {message}", end="", flush=True)
    
    logger.info("Generating semantic profiles...")
    stats = await generate_profiles(progress_callback=progress)
    print()
    logger.info(f"Profile generation complete: {json.dumps(stats, indent=2)}")


async def cmd_sync_all(args):
    """Run full sync pipeline."""
    from app.ingestion.scanner import scan_library
    from app.ingestion.lastfm import enrich_artists_from_lastfm
    from app.embeddings.generator import generate_track_embeddings
    from app.profiles.generator import generate_profiles
    
    init_db()
    
    logger.info("=" * 60)
    logger.info("PLAYLIST GENERATOR V3 - FULL SYNC PIPELINE")
    logger.info("=" * 60)
    
    def progress(current, total, message):
        if total > 0:
            pct = int((current / total) * 100)
            print(f"\r  [{pct:3d}%] {current}/{total} - {message}", end="", flush=True)
        else:
            print(f"\r  {message}", end="", flush=True)
    
    # Step 1: Scan files
    logger.info("")
    logger.info("STEP 1/4: File Scanning")
    logger.info("-" * 40)
    scan_stats = await scan_library(progress_callback=progress, full_scan=args.full)
    print()
    logger.info(f"Scan: {scan_stats.get('tracks_added', 0)} added, {scan_stats.get('tracks_updated', 0)} updated")
    
    # Step 2: Last.fm enrichment
    logger.info("")
    logger.info("STEP 2/4: Last.fm Enrichment")
    logger.info("-" * 40)
    lastfm_stats = await enrich_artists_from_lastfm()
    logger.info(f"Last.fm: {lastfm_stats.get('artists_processed', 0)} artists, {lastfm_stats.get('tags_added', 0)} tags")
    
    # Step 3: Embeddings
    logger.info("")
    logger.info("STEP 3/4: Embedding Generation")
    logger.info("-" * 40)
    embed_stats = await generate_track_embeddings()
    logger.info(f"Embeddings: {embed_stats.get('embedded', 0)} tracks")
    
    # Step 4: Profiles
    logger.info("")
    logger.info("STEP 4/4: Semantic Profiles")
    logger.info("-" * 40)
    profile_stats = await generate_profiles(progress_callback=progress)
    print()
    logger.info(f"Profiles: {profile_stats.get('created', 0)} generated")
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    
    from app.database_pg import get_stats
    final_stats = get_stats()
    logger.info(f"Total tracks: {final_stats.get('tracks', 0)}")
    logger.info(f"Track files: {final_stats.get('track_files', 0)}")
    logger.info(f"Artists enriched: {final_stats.get('artists_with_tags', 0)}/{final_stats.get('artists', 0)}")
    logger.info(f"Tracks with embeddings: {final_stats.get('tracks_with_embeddings', 0)}")
    logger.info(f"Tracks with profiles: {final_stats.get('tracks_with_profiles', 0)}")


def cmd_stats(args):
    """Show library statistics."""
    from app.database_pg import get_stats
    
    init_db()
    
    stats = get_stats()
    print(json.dumps(stats, indent=2))


def cmd_export_m3u(args):
    """Export playlist to M3U."""
    from app.export.m3u import export_playlist_to_file
    from pathlib import Path
    
    init_db()
    
    output_path = Path(args.output) if args.output else Path(f"playlist_{args.playlist_id}.m3u")
    
    result = export_playlist_to_file(
        playlist_id=args.playlist_id,
        output_path=output_path,
        mode=args.mode,
        mapping_name=args.mapping,
    )
    
    logger.info(f"Exported to {result}")


def cmd_path_mapping(args):
    """Manage path mappings."""
    from app.export.m3u import get_path_mappings, create_path_mapping, delete_path_mapping
    
    init_db()
    
    if args.action == "list":
        mappings = get_path_mappings()
        if not mappings:
            print("No path mappings configured")
        else:
            for m in mappings:
                print(f"  {m['name']}: {m['source_prefix']} → {m['target_prefix']}")
    
    elif args.action == "add":
        if not args.name or not args.source or not args.target:
            print("Error: --name, --source, and --target are required for 'add'")
            sys.exit(1)
        
        mapping_id = create_path_mapping(
            name=args.name,
            source_prefix=args.source,
            target_prefix=args.target,
            priority=args.priority or 0,
        )
        print(f"Created mapping '{args.name}' (id: {mapping_id})")
    
    elif args.action == "delete":
        if not args.name:
            print("Error: --name is required for 'delete'")
            sys.exit(1)
        
        if delete_path_mapping(args.name):
            print(f"Deleted mapping '{args.name}'")
        else:
            print(f"Mapping '{args.name}' not found")


def main():
    parser = argparse.ArgumentParser(description="Playlist Generator v3 CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # sync-all
    sync_parser = subparsers.add_parser("sync-all", help="Run full sync pipeline")
    sync_parser.add_argument("--full", action="store_true", help="Force full file scan")
    
    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan music library")
    scan_parser.add_argument("--full", action="store_true", help="Force full scan")
    
    # enrich-lastfm
    subparsers.add_parser("enrich-lastfm", help="Enrich from Last.fm")
    
    # generate-embeddings
    subparsers.add_parser("generate-embeddings", help="Generate embeddings")
    
    # generate-profiles
    subparsers.add_parser("generate-profiles", help="Generate semantic profiles")
    
    # stats
    subparsers.add_parser("stats", help="Show library statistics")
    
    # export-m3u
    export_parser = subparsers.add_parser("export-m3u", help="Export playlist to M3U")
    export_parser.add_argument("playlist_id", help="Playlist UUID")
    export_parser.add_argument("-o", "--output", help="Output file path")
    export_parser.add_argument("-m", "--mode", choices=["absolute", "relative", "mapped"], default="absolute")
    export_parser.add_argument("--mapping", help="Path mapping name (for mapped mode)")
    
    # path-mapping
    mapping_parser = subparsers.add_parser("path-mapping", help="Manage path mappings")
    mapping_parser.add_argument("action", choices=["list", "add", "delete"])
    mapping_parser.add_argument("--name", help="Mapping name")
    mapping_parser.add_argument("--source", help="Source prefix")
    mapping_parser.add_argument("--target", help="Target prefix")
    mapping_parser.add_argument("--priority", type=int, help="Priority (higher = preferred)")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == "sync-all":
        asyncio.run(cmd_sync_all(args))
    elif args.command == "scan":
        asyncio.run(cmd_scan(args))
    elif args.command == "enrich-lastfm":
        asyncio.run(cmd_enrich_lastfm(args))
    elif args.command == "generate-embeddings":
        asyncio.run(cmd_generate_embeddings(args))
    elif args.command == "generate-profiles":
        asyncio.run(cmd_generate_profiles(args))
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "export-m3u":
        cmd_export_m3u(args)
    elif args.command == "path-mapping":
        cmd_path_mapping(args)


if __name__ == "__main__":
    main()
