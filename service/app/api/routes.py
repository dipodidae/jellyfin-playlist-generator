import json
import asyncio
from typing import AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import GeneratePlaylistRequest, GeneratedPlaylist, ProgressEvent, Track
from app.database import get_connection
from app.ingestion.jellyfin import sync_jellyfin_library
from app.ingestion.lastfm import enrich_artists_from_lastfm, enrich_tracks_from_lastfm
from app.embeddings.generator import generate_track_embeddings, search_tracks_by_text
from app.trajectory.intent import parse_prompt
from app.trajectory.composer import compose_playlist, smooth_transitions
from app.trajectory.title_generator import generate_playlist_title
from app.ingestion.jellyfin import create_jellyfin_playlist

router = APIRouter()

# Global sync state
_sync_state = {
    "is_syncing": False,
    "started_at": None,
    "current": 0,
    "total": 0,
    "message": "",
}


@router.get("/sync/status")
async def get_sync_status():
    """Get current sync status."""
    return {
        "is_syncing": _sync_state["is_syncing"],
        "started_at": _sync_state["started_at"].isoformat() if _sync_state["started_at"] else None,
        "current": _sync_state["current"],
        "total": _sync_state["total"],
        "message": _sync_state["message"],
    }


async def generate_playlist_stream(
    prompt: str, size: int, create_in_jellyfin: bool = True
) -> AsyncGenerator[str, None]:
    """Generate playlist with SSE progress events."""
    
    def sse_event(stage: str, progress: int, message: str, **kwargs) -> str:
        event = ProgressEvent(
            stage=stage,
            progress=progress,
            message=message,
            **kwargs
        )
        return f"data: {event.model_dump_json()}\n\n"
    
    try:
        yield sse_event("parsing", 5, "Parsing prompt...")
        
        # Parse the prompt into structured intent
        intent = parse_prompt(prompt, target_size=size)
        
        yield sse_event("trajectory", 15, f"Generating {intent.arc_type.value} trajectory...")
        
        yield sse_event("candidates", 25, "Gathering candidate tracks...")
        
        # Compose playlist using trajectory engine
        scored_tracks = compose_playlist(intent)
        
        yield sse_event("matching", 50, f"Selected {len(scored_tracks)} tracks...")
        
        yield sse_event("composing", 70, "Optimizing track order...")
        
        # Smooth transitions
        scored_tracks = smooth_transitions(scored_tracks)
        
        # Convert to Track objects
        tracks = [
            Track(
                id=t.id,
                title=t.title,
                artist_name=t.artist_name,
                album_name=t.album_name,
                year=t.year,
                duration_ms=t.duration_ms
            )
            for t in scored_tracks
        ]
        
        # Generate AI title
        yield sse_event("jellyfin", 85, "Generating playlist title...")
        track_artists = [t.artist_name for t in tracks]
        playlist_title = generate_playlist_title(prompt, track_artists)
        
        jellyfin_id = None
        if create_in_jellyfin and tracks:
            yield sse_event("jellyfin", 92, "Creating Jellyfin playlist...")
            try:
                jellyfin_id = await create_jellyfin_playlist(
                    name=playlist_title,
                    track_ids=[t.id for t in tracks]
                )
            except Exception as e:
                yield sse_event("jellyfin", 92, f"Jellyfin playlist creation failed: {e}")
        
        playlist = GeneratedPlaylist(
            prompt=prompt,
            title=playlist_title,
            playlist_size=len(tracks),
            tracks=tracks,
            jellyfin_playlist_id=jellyfin_id,
            partial=len(tracks) < size,
            warning=f"Only {len(tracks)} tracks found." if len(tracks) < size else None
        )
        
        yield sse_event("complete", 100, "Done!", playlist=playlist)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield sse_event("error", 0, str(e), error=str(e))


@router.post("/generate-playlist/stream")
async def generate_playlist_stream_endpoint(request: GeneratePlaylistRequest):
    """Generate playlist with SSE streaming progress."""
    return StreamingResponse(
        generate_playlist_stream(request.prompt, request.size),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/generate-playlist")
async def generate_playlist_endpoint(request: GeneratePlaylistRequest):
    """Generate playlist and return final result (non-streaming)."""
    result = None
    async for event_str in generate_playlist_stream(request.prompt, request.size):
        if event_str.startswith("data: "):
            event_data = json.loads(event_str[6:].strip())
            if event_data.get("stage") == "complete":
                result = event_data.get("playlist")
            elif event_data.get("stage") == "error":
                from fastapi import HTTPException
                raise HTTPException(status_code=500, detail=event_data.get("error"))
    
    return result


@router.post("/sync/jellyfin")
async def sync_jellyfin():
    """Trigger Jellyfin library sync."""
    stats = await sync_jellyfin_library()
    return {"status": "ok", "stats": stats}


@router.post("/sync/jellyfin/stream")
async def sync_jellyfin_stream(full: bool = False):
    """Trigger Jellyfin library sync with SSE progress.
    
    Args:
        full: If True, do a full sync of all tracks. If False (default), 
              only sync new tracks added since last sync.
    """
    global _sync_state
    
    # Check if already syncing
    if _sync_state["is_syncing"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Sync already in progress",
                "started_at": _sync_state["started_at"].isoformat() if _sync_state["started_at"] else None,
                "current": _sync_state["current"],
                "total": _sync_state["total"],
                "message": _sync_state["message"],
            }
        )
    
    sync_complete = asyncio.Event()
    sync_result = {"stats": None, "error": None}
    
    def progress_callback(current: int, total: int, message: str):
        _sync_state["current"] = current
        _sync_state["total"] = total
        _sync_state["message"] = message
    
    async def run_sync():
        global _sync_state
        try:
            stats = await sync_jellyfin_library(progress_callback=progress_callback, full_sync=full)
            sync_result["stats"] = stats
        except Exception as e:
            sync_result["error"] = str(e)
        finally:
            _sync_state["is_syncing"] = False
            sync_complete.set()
    
    async def generate_events():
        global _sync_state
        _sync_state["is_syncing"] = True
        _sync_state["started_at"] = datetime.now()
        _sync_state["current"] = 0
        _sync_state["total"] = 0
        _sync_state["message"] = "Starting sync..."
        
        task = asyncio.create_task(run_sync())
        
        yield f"data: {json.dumps({'stage': 'starting', 'progress': 0, 'message': 'Connecting to Jellyfin...'})}\n\n"
        
        while not sync_complete.is_set():
            await asyncio.sleep(0.5)
            if _sync_state["total"] > 0:
                pct = int((_sync_state["current"] / _sync_state["total"]) * 100)
                yield f"data: {json.dumps({'stage': 'syncing', 'progress': pct, 'current': _sync_state['current'], 'total': _sync_state['total'], 'message': _sync_state['message']})}\n\n"
        
        await task
        
        if sync_result["error"]:
            yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': sync_result['error'], 'error': sync_result['error']})}\n\n"
        else:
            yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'message': 'Sync complete!', 'stats': sync_result['stats']})}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.post("/sync/lastfm/artists")
async def sync_lastfm_artists(background_tasks: BackgroundTasks):
    """Trigger Last.fm artist enrichment (runs in background)."""
    background_tasks.add_task(enrich_artists_from_lastfm)
    return {"status": "started", "message": "Artist enrichment started in background"}


@router.post("/sync/lastfm/tracks")
async def sync_lastfm_tracks(background_tasks: BackgroundTasks, max_tracks: int = 1000):
    """Trigger Last.fm track enrichment (runs in background)."""
    background_tasks.add_task(enrich_tracks_from_lastfm, max_tracks=max_tracks)
    return {"status": "started", "message": f"Track enrichment started for up to {max_tracks} tracks"}


@router.post("/sync/embeddings")
async def sync_embeddings(background_tasks: BackgroundTasks, max_tracks: int | None = None):
    """Generate embeddings for tracks (runs in background)."""
    background_tasks.add_task(generate_track_embeddings, max_tracks=max_tracks)
    return {"status": "started", "message": "Embedding generation started in background"}


@router.get("/search")
async def search_tracks(q: str, limit: int = 20):
    """Search tracks by semantic similarity to query text."""
    results = search_tracks_by_text(q, limit=limit)
    return {"query": q, "results": results}
