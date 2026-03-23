"""API routes for v3 architecture (file-based, PostgreSQL+pgvector)."""

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID
import time

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from app.config import settings
from app.database_pg import get_stats, get_cursor, get_connection, init_database, rebuild_search_vectors
from app.ingestion.scanner import scan_library
from app.ingestion.lastfm import enrich_artists_from_lastfm
from app.embeddings.generator import generate_track_embeddings, search_tracks_by_text
from app.profiles.generator import generate_profiles
from app.export.m3u import (
    get_path_mappings, create_path_mapping, delete_path_mapping,
    export_tracks_to_file, export_playlist_to_file, generate_m3u, get_track_files
)
from app.trajectory.composer_v4 import compose_playlist_v4, compose_playlist_v4_streaming
from app.trajectory.title_generator import generate_playlist_title
from app.observability import log_generation, update_track_usage, check_cold_start
from app.clustering.scenes import generate_clusters
from app.audio.analyzer import analyze_library
from app.transitions import record_skip
from app.export.jellyfin import test_connection as jellyfin_test_connection, export_to_jellyfin

logger = logging.getLogger(__name__)
router = APIRouter()

# Global state for long-running operations
_operation_state = {
    "is_running": False,
    "operation": None,
    "started_at": None,
    "current": 0,
    "total": 0,
    "message": "",
    "stage": "idle",
    "job_id": None,
    "scan_type": None,
    "stats": {
        "files_found": 0,
        "files_scanned": 0,
        "files_skipped": 0,
        "tracks_added": 0,
        "tracks_updated": 0,
        "files_missing": 0,
        "errors": 0,
    },
}
_scan_job_runtime: dict[str, dict] = {}


# ============================================================================
# Schemas
# ============================================================================

class PathMappingCreate(BaseModel):
    name: str
    source_prefix: str
    target_prefix: str
    priority: int = 0


class PathMappingResponse(BaseModel):
    id: str
    name: str
    source_prefix: str
    target_prefix: str
    priority: int


class ExportRequest(BaseModel):
    track_ids: list[str]
    mode: str = "absolute"  # absolute, relative, mapped
    mapping_name: str | None = None
    playlist_name: str | None = None


class JellyfinExportRequest(BaseModel):
    track_ids: list[str]
    playlist_name: str


class GeneratePlaylistRequest(BaseModel):
    prompt: str
    size: int = 25
    save: bool = True


class PlaylistResponse(BaseModel):
    id: str
    prompt: str
    track_count: int
    created_at: datetime
    tracks: list[dict] | None = None


def _empty_scan_stats() -> dict[str, int]:
    return {
        "files_found": 0,
        "files_scanned": 0,
        "files_skipped": 0,
        "tracks_added": 0,
        "tracks_updated": 0,
        "files_missing": 0,
        "errors": 0,
    }


def _serialize_scan_job_row(row) -> dict | None:
    if not row:
        return None

    return {
        "job_id": str(row[0]),
        "status": row[1],
        "scan_type": row[2],
        "stage": row[3],
        "started_at": row[4].isoformat() if row[4] else None,
        "updated_at": row[5].isoformat() if row[5] else None,
        "completed_at": row[6].isoformat() if row[6] else None,
        "current": row[7] or 0,
        "total": row[8] or 0,
        "message": row[16] or "",
        "error": row[17],
        "stats": {
            "files_found": row[9] or 0,
            "files_scanned": row[10] or 0,
            "files_skipped": row[11] or 0,
            "tracks_added": row[12] or 0,
            "tracks_updated": row[13] or 0,
            "files_missing": row[14] or 0,
            "errors": row[15] or 0,
        },
    }


def _set_operation_state(payload: dict | None) -> None:
    global _operation_state

    if not payload:
        _operation_state = {
            "is_running": False,
            "operation": None,
            "started_at": None,
            "current": 0,
            "total": 0,
            "message": "",
            "stage": "idle",
            "job_id": None,
            "scan_type": None,
            "stats": _empty_scan_stats(),
        }
        return

    _operation_state["is_running"] = payload.get("status") == "running"
    _operation_state["operation"] = "scan" if payload.get("job_id") else None
    _operation_state["started_at"] = datetime.fromisoformat(payload["started_at"]) if payload.get("started_at") else None
    _operation_state["current"] = payload.get("current", 0)
    _operation_state["total"] = payload.get("total", 0)
    _operation_state["message"] = payload.get("message", "")
    _operation_state["stage"] = payload.get("stage", "idle")
    _operation_state["job_id"] = payload.get("job_id")
    _operation_state["scan_type"] = payload.get("scan_type")
    _operation_state["stats"] = payload.get("stats", _empty_scan_stats())


def _build_scan_response(payload: dict | None, source: str) -> dict:
    if not payload:
        return {
            "is_running": False,
            "operation": None,
            "job_id": None,
            "status": "idle",
            "scan_type": None,
            "stage": "idle",
            "started_at": None,
            "updated_at": None,
            "completed_at": None,
            "current": 0,
            "total": 0,
            "progress": 0,
            "message": "",
            "error": None,
            "stats": _empty_scan_stats(),
            "source": source,
            "is_live": False,
        }

    total = payload.get("total", 0) or 0
    current = payload.get("current", 0) or 0
    progress = int((current / total) * 100) if total > 0 else 0

    return {
        "is_running": payload.get("status") == "running",
        "operation": "scan" if payload.get("job_id") else None,
        "job_id": payload.get("job_id"),
        "status": payload.get("status"),
        "scan_type": payload.get("scan_type"),
        "stage": payload.get("stage", "idle"),
        "started_at": payload.get("started_at"),
        "updated_at": payload.get("updated_at"),
        "completed_at": payload.get("completed_at"),
        "current": current,
        "total": total,
        "progress": progress,
        "message": payload.get("message", ""),
        "error": payload.get("error"),
        "stats": payload.get("stats", _empty_scan_stats()),
        "source": source,
        "is_live": source == "stream",
    }


def _get_active_scan_job() -> dict | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, scan_type, stage, started_at, updated_at, completed_at,
                       current, total, files_found, files_scanned, files_skipped,
                       tracks_added, tracks_updated, files_missing, errors,
                       current_message, error_summary
                FROM scan_jobs
                WHERE status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
            """)
            return _serialize_scan_job_row(cur.fetchone())


def _get_scan_job(job_id: str) -> dict | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, scan_type, stage, started_at, updated_at, completed_at,
                       current, total, files_found, files_scanned, files_skipped,
                       tracks_added, tracks_updated, files_missing, errors,
                       current_message, error_summary
                FROM scan_jobs
                WHERE id = %s
            """, (job_id,))
            return _serialize_scan_job_row(cur.fetchone())


def _list_scan_jobs(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, status, scan_type, stage, started_at, updated_at, completed_at,
                       current, total, files_found, files_scanned, files_skipped,
                       tracks_added, tracks_updated, files_missing, errors,
                       current_message, error_summary
                FROM scan_jobs
                ORDER BY started_at DESC
                LIMIT %s
            """, (limit,))
            return [_serialize_scan_job_row(row) for row in cur.fetchall()]


def _list_scan_job_events(job_id: str, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT created_at, stage, event_type, message, current, total
                FROM scan_job_events
                WHERE job_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (job_id, limit))
            rows = cur.fetchall()
            return [
                {
                    "created_at": row[0].isoformat() if row[0] else None,
                    "stage": row[1],
                    "event_type": row[2],
                    "message": row[3] or "",
                    "current": row[4] or 0,
                    "total": row[5] or 0,
                }
                for row in rows
            ][::-1]


def _create_scan_job(full: bool) -> dict:
    scan_type = "full" if full else "incremental"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO scan_jobs (
                    status, scan_type, stage, current_message
                ) VALUES ('running', %s, 'starting', %s)
                RETURNING id, status, scan_type, stage, started_at, updated_at, completed_at,
                          current, total, files_found, files_scanned, files_skipped,
                          tracks_added, tracks_updated, files_missing, errors,
                          current_message, error_summary
            """, (scan_type, "Starting scan..."))
            job = _serialize_scan_job_row(cur.fetchone())
    _scan_job_runtime[job["job_id"]] = {
        "last_db_write": 0.0,
        "last_event_key": None,
    }
    return job


def _append_scan_job_event(job_id: str, payload: dict, event_type: str = "progress") -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO scan_job_events (
                    job_id, stage, event_type, message, current, total, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """, (
                job_id,
                payload.get("stage", "idle"),
                event_type,
                payload.get("message", ""),
                payload.get("current", 0),
                payload.get("total", 0),
                json.dumps(payload),
            ))
            cur.execute("""
                DELETE FROM scan_job_events
                WHERE job_id = %s
                  AND id NOT IN (
                    SELECT id FROM scan_job_events
                    WHERE job_id = %s
                    ORDER BY created_at DESC
                    LIMIT 50
                  )
            """, (job_id, job_id))


def _update_scan_job(job_id: str, payload: dict, status: str | None = None, final: bool = False, error: str | None = None) -> dict:
    runtime = _scan_job_runtime.setdefault(job_id, {"last_db_write": 0.0, "last_event_key": None})
    now = time.monotonic()
    event_key = (payload.get("stage"), payload.get("message"), payload.get("current"), payload.get("total"))
    should_write = final or (now - runtime["last_db_write"] >= 0.75) or (payload.get("stage") != "scanning_files")
    event_type = "progress"

    next_status = status or ("failed" if error else payload.get("status", "running"))
    completed_clause = "completed_at = now()," if final else ""

    if should_write:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE scan_jobs
                    SET status = %s,
                        stage = %s,
                        updated_at = now(),
                        {completed_clause}
                        current = %s,
                        total = %s,
                        files_found = %s,
                        files_scanned = %s,
                        files_skipped = %s,
                        tracks_added = %s,
                        tracks_updated = %s,
                        files_missing = %s,
                        errors = %s,
                        current_message = %s,
                        error_summary = %s
                    WHERE id = %s
                    RETURNING id, status, scan_type, stage, started_at, updated_at, completed_at,
                              current, total, files_found, files_scanned, files_skipped,
                              tracks_added, tracks_updated, files_missing, errors,
                              current_message, error_summary
                """, (
                    next_status,
                    payload.get("stage", "idle"),
                    payload.get("current", 0),
                    payload.get("total", 0),
                    payload.get("stats", {}).get("files_found", 0),
                    payload.get("stats", {}).get("files_scanned", 0),
                    payload.get("stats", {}).get("files_skipped", 0),
                    payload.get("stats", {}).get("tracks_added", 0),
                    payload.get("stats", {}).get("tracks_updated", 0),
                    payload.get("stats", {}).get("files_missing", 0),
                    payload.get("stats", {}).get("errors", 0),
                    payload.get("message", ""),
                    error,
                    job_id,
                ))
                job = _serialize_scan_job_row(cur.fetchone())
        runtime["last_db_write"] = now
    else:
        job = _get_scan_job(job_id)

    should_append_event = final or event_key != runtime["last_event_key"] and payload.get("stage") in {"discovering", "saving_tracks", "complete", "error"}
    if final:
        event_type = "error" if error else "complete"
    if should_append_event:
        _append_scan_job_event(job_id, {**payload, "status": next_status, "error": error}, event_type=event_type)
        runtime["last_event_key"] = event_key

    return job


# ============================================================================
# Health & Stats
# ============================================================================

@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "playlist-generator-v3"}


@router.get("/stats")
async def get_library_stats():
    """Get library statistics including enrichment coverage and cold-start quality."""
    try:
        stats = get_stats()
        stats["cold_start"] = check_cold_start()
        return stats
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/generation-stats")
async def get_playlist_generation_stats(days: int = Query(default=7, ge=1, le=90)):
    """Get playlist generation statistics for the last N days."""
    try:
        from app.observability import get_generation_stats
        return get_generation_stats(days=days)
    except Exception as e:
        logger.error(f"Error getting generation stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observatory/stats")
async def get_observatory_statistics(refresh: bool = Query(default=False)):
    """Get comprehensive music collection statistics for the observatory page.

    Results are cached server-side for 1 hour. Pass ?refresh=true to force recompute.
    """
    try:
        from app.database_pg import get_observatory_stats
        return get_observatory_stats(force_refresh=refresh)
    except Exception as e:
        logger.error(f"Error computing observatory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Scan Operations
# ============================================================================

@router.get("/scan/status")
async def get_scan_status():
    """Get current scan/operation status."""
    payload = _get_active_scan_job()
    if payload:
        _set_operation_state(payload)
        return _build_scan_response(payload, "snapshot")

    fallback_payload = None
    if _operation_state["job_id"]:
        fallback_payload = {
            "job_id": _operation_state["job_id"],
            "status": "running" if _operation_state["is_running"] else "idle",
            "scan_type": _operation_state["scan_type"],
            "stage": _operation_state["stage"],
            "started_at": _operation_state["started_at"].isoformat() if _operation_state["started_at"] else None,
            "updated_at": _operation_state["started_at"].isoformat() if _operation_state["started_at"] else None,
            "completed_at": None,
            "current": _operation_state["current"],
            "total": _operation_state["total"],
            "message": _operation_state["message"],
            "error": None,
            "stats": _operation_state["stats"],
        }

    return _build_scan_response(fallback_payload, "memory")


@router.post("/scan")
async def trigger_scan(full: bool = False):
    """Trigger a library scan (non-streaming)."""
    active_job = _get_active_scan_job()
    if active_job:
        raise HTTPException(
            status_code=409,
            detail=_build_scan_response(active_job, "snapshot"),
        )

    job = _create_scan_job(full)
    _set_operation_state(job)

    def progress_callback(payload: dict):
        job_state = _update_scan_job(job["job_id"], payload, status="running")
        _set_operation_state(job_state)

    try:
        stats = await scan_library(progress_callback=progress_callback, full_scan=full)
        final_payload = {
            "stage": "complete",
            "current": stats.get("files_scanned", 0) + stats.get("files_skipped", 0),
            "total": stats.get("files_found", 0),
            "message": "Scan complete",
            "stats": stats,
        }
        job_state = _update_scan_job(job["job_id"], final_payload, status="completed", final=True)
        _set_operation_state(job_state)

        # Rebuild BM25 search vectors after scan (non-blocking best-effort)
        try:
            rebuild_search_vectors()
            logger.info("Search vectors rebuilt after scan")
        except Exception as rebuild_err:
            logger.warning(f"Search vector rebuild after scan failed: {rebuild_err}")

        return _build_scan_response(job_state, "snapshot")
    except Exception as e:
        error_payload = {
            "stage": "error",
            "current": _operation_state["current"],
            "total": _operation_state["total"],
            "message": "Scan failed",
            "stats": _operation_state["stats"],
        }
        job_state = _update_scan_job(job["job_id"], error_payload, status="failed", final=True, error=str(e))
        _set_operation_state(job_state)
        raise


@router.post("/scan/stream")
async def trigger_scan_stream(full: bool = False):
    """Trigger a library scan with SSE progress."""
    active_job = _get_active_scan_job()
    if active_job:
        raise HTTPException(
            status_code=409,
            detail=_build_scan_response(active_job, "snapshot"),
        )

    job = _create_scan_job(full)
    _set_operation_state(job)

    async def generate_events():
        scan_complete = asyncio.Event()
        scan_result = {"stats": None, "error": None, "job": job}

        def progress_callback(payload: dict):
            job_state = _update_scan_job(job["job_id"], payload, status="running")
            _set_operation_state(job_state)
            scan_result["job"] = job_state

        async def run_scan():
            try:
                stats = await scan_library(progress_callback=progress_callback, full_scan=full)
                scan_result["stats"] = stats
                final_payload = {
                    "stage": "complete",
                    "current": stats.get("files_scanned", 0) + stats.get("files_skipped", 0),
                    "total": stats.get("files_found", 0),
                    "message": "Scan complete",
                    "stats": stats,
                }
                job_state = _update_scan_job(job["job_id"], final_payload, status="completed", final=True)
                _set_operation_state(job_state)
                scan_result["job"] = job_state

                # Rebuild BM25 search vectors after scan (best-effort)
                try:
                    rebuild_search_vectors()
                    logger.info("Search vectors rebuilt after streaming scan")
                except Exception as rebuild_err:
                    logger.warning(f"Search vector rebuild after streaming scan failed: {rebuild_err}")

            except Exception as e:
                scan_result["error"] = str(e)
                error_payload = {
                    "stage": "error",
                    "current": _operation_state["current"],
                    "total": _operation_state["total"],
                    "message": "Scan failed",
                    "stats": _operation_state["stats"],
                }
                job_state = _update_scan_job(job["job_id"], error_payload, status="failed", final=True, error=str(e))
                _set_operation_state(job_state)
                scan_result["job"] = job_state
            finally:
                scan_complete.set()

        asyncio.create_task(run_scan())

        last_updated_at = None
        while not scan_complete.is_set():
            payload = _get_scan_job(job["job_id"])
            if payload and payload.get("updated_at") != last_updated_at:
                last_updated_at = payload.get("updated_at")
                event = _build_scan_response(payload, "stream")
                yield f"data: {json.dumps(event)}\n\n"
            await asyncio.sleep(0.5)

        payload = scan_result.get("job") or _get_scan_job(job["job_id"])
        if scan_result["error"]:
            event = _build_scan_response(payload, "stream")
        else:
            event = _build_scan_response(payload, "stream")
        yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.get("/scan/jobs/active")
async def get_active_scan_job_endpoint():
    payload = _get_active_scan_job()
    return _build_scan_response(payload, "snapshot")


@router.get("/scan/jobs/history")
async def get_scan_job_history(limit: int = Query(default=10, ge=1, le=50)):
    jobs = _list_scan_jobs(limit=limit)
    return [_build_scan_response(job, "snapshot") for job in jobs]


@router.get("/scan/jobs/{job_id}")
async def get_scan_job_detail(job_id: str):
    payload = _get_scan_job(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Scan job not found")

    response = _build_scan_response(payload, "snapshot")
    response["events"] = _list_scan_job_events(job_id)
    return response


# ============================================================================
# Enrichment Operations
# ============================================================================

def _make_enrichment_stream(label: str, coro_factory):
    """
    Return a StreamingResponse that runs an async enrichment coroutine and
    emits SSE progress events.  coro_factory must be a zero-arg callable that
    returns the coroutine (so we can pass a progress_callback into it).
    """
    def format_completion_message(stats: dict | None) -> str:
        if not stats:
            return f"{label} complete"
        if {"processed", "success", "failed", "skipped"} <= stats.keys():
            return (
                f"{label} complete: {stats['success']} succeeded, "
                f"{stats['failed']} failed, {stats['skipped']} skipped "
                f"({stats['processed']} processed)"
            )
        if {"artists", "clusters"} <= stats.keys():
            small_assigned = stats.get("small_artists_assigned", 0)
            return (
                f"{label} complete: {stats['clusters']} clusters from "
                f"{stats['artists']} artists, {small_assigned} small artists assigned"
            )
        if {"processed", "created", "fallback", "skipped"} <= stats.keys():
            return (
                f"{label} complete: {stats['created']} created, "
                f"{stats['fallback']} fallback, {stats['skipped']} skipped "
                f"({stats['processed']} processed)"
            )
        if {"processed", "embedded", "errors"} <= stats.keys():
            return (
                f"{label} complete: {stats['embedded']} embedded, "
                f"{stats['errors']} errors ({stats['processed']} processed)"
            )
        return f"{label} complete"

    async def generate_events() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()
        result_holder: dict = {}

        def progress_callback(current: int, total: int, message: str):
            pct = int((current / total) * 100) if total > 0 else 0
            queue.put_nowait({"progress": pct, "message": message, "current": current, "total": total})

        async def run():
            try:
                # Call the factory - returns coroutine for async, result for sync
                result = coro_factory(progress_callback)
                if asyncio.iscoroutine(result):
                    # Async function - await it
                    result_holder["stats"] = await result
                else:
                    # Sync function already executed and returned result
                    result_holder["stats"] = result
            except Exception as exc:
                result_holder["error"] = str(exc)
            finally:
                queue.put_nowait(sentinel)

        yield f"data: {json.dumps({'progress': 0, 'message': f'Starting {label}...'})}"
        yield "\n\n"
        task = asyncio.create_task(run())

        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield f"data: {json.dumps(item)}"
            yield "\n\n"

        await task

        if "error" in result_holder:
            yield f"data: {json.dumps({'progress': 0, 'message': result_holder['error'], 'error': result_holder['error'], 'done': True})}"
        else:
            stats = result_holder.get("stats", {})
            yield f"data: {json.dumps({'progress': 100, 'message': format_completion_message(stats), 'stats': stats, 'done': True})}"
        yield "\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/enrich/lastfm")
async def trigger_lastfm_enrichment(background_tasks: BackgroundTasks):
    """Trigger Last.fm artist enrichment (runs in background)."""
    async def enrich_then_rebuild():
        await enrich_artists_from_lastfm()
        try:
            rebuild_search_vectors()
            logger.info("Search vectors rebuilt after Last.fm enrichment")
        except Exception as e:
            logger.warning(f"Search vector rebuild after Last.fm enrichment failed: {e}")

    background_tasks.add_task(enrich_then_rebuild)
    return {"status": "started", "message": "Last.fm enrichment started in background"}


@router.post("/enrich/lastfm/stream")
async def trigger_lastfm_enrichment_stream():
    """Trigger Last.fm artist enrichment with SSE progress."""
    return _make_enrichment_stream(
        "Last.fm enrichment",
        lambda cb: enrich_artists_from_lastfm(progress_callback=cb),
    )


@router.post("/enrich/embeddings")
async def trigger_embedding_generation(background_tasks: BackgroundTasks):
    """Trigger embedding generation (runs in background)."""
    background_tasks.add_task(generate_track_embeddings)
    return {"status": "started", "message": "Embedding generation started in background"}


@router.post("/enrich/embeddings/stream")
async def trigger_embedding_generation_stream():
    """Trigger embedding generation with SSE progress."""
    return _make_enrichment_stream(
        "Embedding generation",
        lambda cb: generate_track_embeddings(progress_callback=cb),
    )


@router.post("/enrich/profiles")
async def trigger_profile_generation(background_tasks: BackgroundTasks):
    """Trigger semantic profile generation (runs in background)."""
    background_tasks.add_task(generate_profiles)
    return {"status": "started", "message": "Profile generation started in background"}


@router.post("/enrich/profiles/stream")
async def trigger_profile_generation_stream():
    """Trigger profile generation with SSE progress."""
    return _make_enrichment_stream(
        "Profile generation",
        lambda cb: generate_profiles(progress_callback=cb),
    )


@router.post("/enrich/clusters")
async def trigger_cluster_generation(background_tasks: BackgroundTasks):
    """Trigger scene clustering (runs in background)."""
    background_tasks.add_task(generate_clusters)
    return {"status": "started", "message": "Cluster generation started in background"}


@router.post("/enrich/clusters/stream")
async def trigger_cluster_generation_stream():
    """Trigger scene clustering with SSE progress.

    generate_clusters is CPU-bound (UMAP + HDBSCAN), so we run it in a
    thread to keep the event loop free for flushing SSE events.
    """
    def factory(cb):
        loop = asyncio.get_running_loop()

        def threadsafe_cb(current: int, total: int, message: str):
            loop.call_soon_threadsafe(cb, current, total, message)

        return asyncio.to_thread(
            generate_clusters, progress_callback=threadsafe_cb,
        )

    return _make_enrichment_stream("Scene clustering", factory)


@router.post("/enrich/audio")
async def trigger_audio_analysis(background_tasks: BackgroundTasks):
    """Trigger audio feature analysis (runs in background, requires librosa)."""
    background_tasks.add_task(analyze_library)
    return {"status": "started", "message": "Audio analysis started in background"}


_audio_analysis_lock = asyncio.Lock()


@router.post("/enrich/audio/stream")
async def trigger_audio_analysis_stream(request: Request):
    """Trigger audio feature analysis with SSE progress (requires librosa)."""

    if _audio_analysis_lock.locked():
        raise HTTPException(status_code=409, detail="Audio analysis is already running")

    stop_event = threading.Event()

    async def analyze_library_async(progress_callback):
        """Wrap sync analyze_library in thread pool."""
        loop = asyncio.get_running_loop()

        def threadsafe_callback(current: int, total: int, message: str):
            loop.call_soon_threadsafe(progress_callback, current, total, message)

        async with _audio_analysis_lock:
            return await asyncio.to_thread(
                analyze_library,
                progress_callback=threadsafe_callback,
                stop_event=stop_event,
            )

    async def watch_disconnect():
        """Signal stop_event when the client disconnects."""
        while not stop_event.is_set():
            if await request.is_disconnected():
                stop_event.set()
                return
            await asyncio.sleep(2)

    asyncio.create_task(watch_disconnect())

    return _make_enrichment_stream(
        "Audio analysis",
        analyze_library_async,
    )


# ============================================================================
# Combined Sync (scan + all enrichment in one shot)
# ============================================================================

@router.post("/sync/full-pipeline")
async def sync_full_pipeline(request: Request, skip_lastfm: bool = False, skip_audio: bool = True):
    """Run incremental scan followed by all enrichment steps in sequence.

    Chains: scan → Last.fm → embeddings → profiles → clusters → search vectors.
    Each step is incremental — only new/unprocessed tracks are touched.
    Streams SSE progress events throughout the entire pipeline.

    Query params:
        skip_lastfm: Skip Last.fm enrichment (default false). Useful to avoid
                     slow API calls when you just want embeddings/profiles.
        skip_audio:  Skip audio analysis (default true). Audio analysis is very
                     slow on Pi hardware and usually not needed for new tracks.
    """
    active_job = _get_active_scan_job()
    if active_job:
        raise HTTPException(
            status_code=409,
            detail="A scan is already running",
        )

    async def generate_events() -> AsyncGenerator[str, None]:
        def emit(stage: str, progress: int, message: str, **extra) -> str:
            payload = {"stage": stage, "progress": progress, "message": message, **extra}
            return f"data: {json.dumps(payload)}\n\n"

        pipeline_stats: dict[str, dict] = {}

        # --- Stage 1: Incremental scan ---
        yield emit("scan", 0, "Starting incremental scan...")
        scan_error = None
        try:
            scan_done = asyncio.Event()
            scan_result: dict = {}

            def scan_progress(payload: dict):
                current = payload.get("current", 0)
                total = payload.get("total", 0)
                pct = int((current / total) * 100) if total > 0 else 0
                msg = payload.get("message", "Scanning...")
                # Scale scan to 0-15% of overall pipeline
                scan_result["last_event"] = emit("scan", min(pct // 7, 14), msg)

            async def do_scan():
                try:
                    stats = await scan_library(progress_callback=scan_progress, full_scan=False)
                    scan_result["stats"] = stats
                except Exception as exc:
                    scan_result["error"] = str(exc)
                finally:
                    scan_done.set()

            asyncio.create_task(do_scan())

            while not scan_done.is_set():
                if "last_event" in scan_result:
                    yield scan_result.pop("last_event")
                await asyncio.sleep(0.4)

            if "error" in scan_result:
                scan_error = scan_result["error"]
                yield emit("error", 0, f"Scan failed: {scan_error}", error=scan_error, done=True)
                return

            stats = scan_result.get("stats", {})
            pipeline_stats["scan"] = stats
            new_tracks = stats.get("tracks_added", 0) + stats.get("tracks_updated", 0)
            yield emit("scan", 15, f"Scan complete: {new_tracks} new/updated tracks, {stats.get('files_skipped', 0)} unchanged")

            # Rebuild search vectors after scan
            try:
                rebuild_search_vectors()
            except Exception:
                pass

        except Exception as exc:
            yield emit("error", 0, f"Scan failed: {exc}", error=str(exc), done=True)
            return

        # --- Stage 2: Last.fm enrichment (optional) ---
        if not skip_lastfm:
            yield emit("lastfm", 16, "Starting Last.fm enrichment...")
            try:
                lastfm_done = asyncio.Event()
                lastfm_result: dict = {}

                def lastfm_progress(current: int, total: int, message: str):
                    pct = int((current / total) * 100) if total > 0 else 0
                    # Scale to 16-35%
                    scaled = 16 + (pct * 19 // 100)
                    lastfm_result["last_event"] = emit("lastfm", scaled, message)

                async def do_lastfm():
                    try:
                        result = await enrich_artists_from_lastfm(progress_callback=lastfm_progress)
                        lastfm_result["stats"] = result
                    except Exception as exc:
                        lastfm_result["error"] = str(exc)
                    finally:
                        lastfm_done.set()

                asyncio.create_task(do_lastfm())

                while not lastfm_done.is_set():
                    if "last_event" in lastfm_result:
                        yield lastfm_result.pop("last_event")
                    await asyncio.sleep(0.4)

                if "error" in lastfm_result:
                    yield emit("lastfm", 35, f"Last.fm enrichment failed (continuing): {lastfm_result['error']}")
                else:
                    pipeline_stats["lastfm"] = lastfm_result.get("stats", {})
                    yield emit("lastfm", 35, "Last.fm enrichment complete")

                # Rebuild search vectors after Last.fm
                try:
                    rebuild_search_vectors()
                except Exception:
                    pass

            except Exception as exc:
                yield emit("lastfm", 35, f"Last.fm enrichment failed (continuing): {exc}")
        else:
            yield emit("lastfm", 35, "Last.fm enrichment skipped")

        # --- Stage 3: Embeddings ---
        embed_start = 36
        yield emit("embeddings", embed_start, "Starting embedding generation...")
        try:
            embed_done = asyncio.Event()
            embed_result: dict = {}

            def embed_progress(current: int, total: int, message: str):
                pct = int((current / total) * 100) if total > 0 else 0
                # Scale to 36-60%
                scaled = embed_start + (pct * 24 // 100)
                embed_result["last_event"] = emit("embeddings", scaled, message)

            async def do_embeddings():
                try:
                    result = await generate_track_embeddings(progress_callback=embed_progress)
                    embed_result["stats"] = result
                except Exception as exc:
                    embed_result["error"] = str(exc)
                finally:
                    embed_done.set()

            asyncio.create_task(do_embeddings())

            while not embed_done.is_set():
                if "last_event" in embed_result:
                    yield embed_result.pop("last_event")
                await asyncio.sleep(0.4)

            if "error" in embed_result:
                yield emit("error", 0, f"Embedding generation failed: {embed_result['error']}", error=embed_result["error"], done=True)
                return

            pipeline_stats["embeddings"] = embed_result.get("stats", {})
            yield emit("embeddings", 60, "Embedding generation complete")

        except Exception as exc:
            yield emit("error", 0, f"Embedding generation failed: {exc}", error=str(exc), done=True)
            return

        # --- Stage 4: Profiles ---
        yield emit("profiles", 61, "Starting profile generation...")
        try:
            profile_done = asyncio.Event()
            profile_result: dict = {}

            def profile_progress(current: int, total: int, message: str):
                pct = int((current / total) * 100) if total > 0 else 0
                # Scale to 61-80%
                scaled = 61 + (pct * 19 // 100)
                profile_result["last_event"] = emit("profiles", scaled, message)

            async def do_profiles():
                try:
                    result = await generate_profiles(progress_callback=profile_progress)
                    profile_result["stats"] = result
                except Exception as exc:
                    profile_result["error"] = str(exc)
                finally:
                    profile_done.set()

            asyncio.create_task(do_profiles())

            while not profile_done.is_set():
                if "last_event" in profile_result:
                    yield profile_result.pop("last_event")
                await asyncio.sleep(0.4)

            if "error" in profile_result:
                yield emit("profiles", 80, f"Profile generation failed (continuing): {profile_result['error']}")
            else:
                pipeline_stats["profiles"] = profile_result.get("stats", {})
                yield emit("profiles", 80, "Profile generation complete")

        except Exception as exc:
            yield emit("profiles", 80, f"Profile generation failed (continuing): {exc}")

        # --- Stage 5: Clustering ---
        yield emit("clusters", 81, "Starting scene clustering...")
        try:
            loop = asyncio.get_running_loop()
            cluster_done = asyncio.Event()
            cluster_result: dict = {}

            def cluster_progress_raw(current: int, total: int, message: str):
                pct = int((current / total) * 100) if total > 0 else 0
                # Scale to 81-93%
                scaled = 81 + (pct * 12 // 100)
                cluster_result["last_event"] = emit("clusters", scaled, message)

            def threadsafe_cluster_cb(current: int, total: int, message: str):
                loop.call_soon_threadsafe(cluster_progress_raw, current, total, message)

            async def do_clusters():
                try:
                    result = await asyncio.to_thread(generate_clusters, progress_callback=threadsafe_cluster_cb)
                    cluster_result["stats"] = result
                except Exception as exc:
                    cluster_result["error"] = str(exc)
                finally:
                    cluster_done.set()

            asyncio.create_task(do_clusters())

            while not cluster_done.is_set():
                if "last_event" in cluster_result:
                    yield cluster_result.pop("last_event")
                await asyncio.sleep(0.4)

            if "error" in cluster_result:
                yield emit("clusters", 93, f"Clustering failed (continuing): {cluster_result['error']}")
            else:
                pipeline_stats["clusters"] = cluster_result.get("stats", {})
                yield emit("clusters", 93, "Scene clustering complete")

        except Exception as exc:
            yield emit("clusters", 93, f"Clustering failed (continuing): {exc}")

        # --- Stage 6: Audio analysis (optional) ---
        if not skip_audio:
            yield emit("audio", 94, "Starting audio analysis...")
            try:
                audio_stop = threading.Event()
                audio_done_evt = asyncio.Event()
                audio_result: dict = {}

                def audio_progress_raw(current: int, total: int, message: str):
                    pct = int((current / total) * 100) if total > 0 else 0
                    scaled = 94 + (pct * 4 // 100)
                    audio_result["last_event"] = emit("audio", scaled, message)

                def threadsafe_audio_cb(current: int, total: int, message: str):
                    loop.call_soon_threadsafe(audio_progress_raw, current, total, message)

                async def do_audio():
                    try:
                        result = await asyncio.to_thread(
                            analyze_library,
                            progress_callback=threadsafe_audio_cb,
                            stop_event=audio_stop,
                        )
                        audio_result["stats"] = result
                    except Exception as exc:
                        audio_result["error"] = str(exc)
                    finally:
                        audio_done_evt.set()

                asyncio.create_task(do_audio())

                while not audio_done_evt.is_set():
                    if await request.is_disconnected():
                        audio_stop.set()
                        break
                    if "last_event" in audio_result:
                        yield audio_result.pop("last_event")
                    await asyncio.sleep(0.4)

                if "error" in audio_result:
                    yield emit("audio", 98, f"Audio analysis failed (continuing): {audio_result['error']}")
                else:
                    pipeline_stats["audio"] = audio_result.get("stats", {})
                    yield emit("audio", 98, "Audio analysis complete")

            except Exception as exc:
                yield emit("audio", 98, f"Audio analysis failed (continuing): {exc}")

        # --- Final: rebuild search vectors ---
        yield emit("search_vectors", 99, "Rebuilding search vectors...")
        try:
            rebuild_search_vectors()
            yield emit("search_vectors", 100, "Search vectors rebuilt")
        except Exception as exc:
            yield emit("search_vectors", 100, f"Search vector rebuild failed: {exc}")

        # --- Done ---
        yield emit("complete", 100, "Full pipeline complete", stats=pipeline_stats, done=True)

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ============================================================================
# Path Mappings
# ============================================================================

@router.get("/path-mappings")
async def list_path_mappings() -> list[PathMappingResponse]:
    """List all path mappings."""
    mappings = get_path_mappings()
    return [PathMappingResponse(**m) for m in mappings]


@router.post("/path-mappings")
async def create_or_update_path_mapping(mapping: PathMappingCreate) -> PathMappingResponse:
    """Create or update a path mapping."""
    mapping_id = create_path_mapping(
        name=mapping.name,
        source_prefix=mapping.source_prefix,
        target_prefix=mapping.target_prefix,
        priority=mapping.priority,
    )
    return PathMappingResponse(
        id=mapping_id,
        name=mapping.name,
        source_prefix=mapping.source_prefix,
        target_prefix=mapping.target_prefix,
        priority=mapping.priority,
    )


@router.delete("/path-mappings/{name}")
async def remove_path_mapping(name: str):
    """Delete a path mapping."""
    if delete_path_mapping(name):
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Path mapping not found")


# ============================================================================
# Playlist Generation
# ============================================================================

_STEP_TO_STAGE: dict[int, str] = {
    1: "parsing",
    2: "trajectory",
    3: "candidates",
    4: "matching",
    5: "composing",
    6: "metrics",
    7: "titling",
}


def _candidate_tracks_to_dicts(tracks) -> list[dict]:
    """Convert CandidateTrack objects to API-serialisable dicts."""
    return [
        {
            "id": str(t.id),
            "title": t.title,
            "artist_name": t.artist_name,
            "album_name": t.album_name,
            "year": t.year,
            "duration_ms": t.duration_ms,
            "genres": t.genres or [],
            "scores": {
                "semantic": round(t.semantic_score, 3),
                "admissibility": round(t.admissibility_score, 3),
                "trajectory": round(t.trajectory_score, 3),
                "genre_match": round(t.genre_match_score, 3),
                "impact": round(t.impact_score, 3),
                "negative_constraint_penalty": round(t.negative_constraint_penalty, 3),
                "tourist_match_penalty": round(t.tourist_match_penalty, 3),
                "gravity_penalty": round(t.gravity_penalty, 3),
                "total": round(t.total_score, 3),
            },
            "profile": {
                "energy": round(t.energy, 2),
                "tempo": round(t.tempo, 2),
                "darkness": round(t.darkness, 2),
                "texture": round(t.texture, 2),
            },
        }
        for t in tracks
    ]


def _save_playlist(prompt: str, tracks) -> str | None:
    """Persist a generated playlist and return its UUID string."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO generated_playlists (prompt, track_count)
                VALUES (%s, %s)
                RETURNING id
            """, (prompt, len(tracks)))
            playlist_id = str(cur.fetchone()[0])

            for i, track in enumerate(tracks):
                track_id = track.id if hasattr(track, "id") else track["id"]
                cur.execute("""
                    INSERT INTO playlist_tracks (playlist_id, track_id, position)
                    VALUES (%s, %s, %s)
                """, (playlist_id, track_id, i))
    return playlist_id


@router.post("/generate-playlist")
async def generate_playlist(request: GeneratePlaylistRequest):
    """Generate a playlist from a prompt (non-streaming, v4 composer)."""
    try:
        result = await asyncio.to_thread(
            compose_playlist_v4, request.prompt, request.size
        )

        if not result.tracks:
            raise HTTPException(status_code=404, detail="No matching tracks found")

        # Build rich track dicts for the title generator
        title_tracks = [
            {
                "artist": t.artist_name,
                "title": t.title,
                "album": t.album_name,
                "year": t.year,
                "genres": list(t.genres),
                "energy": t.energy,
                "darkness": t.darkness,
                "tempo": t.tempo,
                "texture": t.texture,
            }
            for t in result.tracks
        ]
        genre_hints = result.intent.genre_hints if result.intent else []
        arc_type_str = result.intent.arc_type.value if result.intent else "journey"

        title = await asyncio.to_thread(
            generate_playlist_title, request.prompt, title_tracks, arc_type_str, genre_hints,
        )

        tracks = _candidate_tracks_to_dicts(result.tracks)

        playlist_id = None
        if request.save:
            playlist_id = await asyncio.to_thread(_save_playlist, request.prompt, result.tracks)

        return {
            "id": playlist_id,
            "title": title,
            "prompt": request.prompt,
            "track_count": len(tracks),
            "tracks": tracks,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating playlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-playlist/stream")
async def generate_playlist_stream(request: GeneratePlaylistRequest):
    """Generate a playlist with SSE progress updates (v4 composer)."""

    async def generate_events() -> AsyncGenerator[str, None]:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        result_holder: dict = {}

        def progress_callback(step: int, total: int, message: str):
            stage = _STEP_TO_STAGE.get(step, "composing")
            progress = int((step / total) * 90)
            event = {"stage": stage, "progress": progress, "message": message}
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def run_composer():
            try:
                result_holder["result"] = compose_playlist_v4_streaming(
                    prompt=request.prompt,
                    target_size=request.size,
                    progress_callback=progress_callback,
                )
            except Exception as exc:
                result_holder["error"] = str(exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        yield f"data: {json.dumps({'stage': 'parsing', 'progress': 0, 'message': 'Starting...'})}"
        yield "\n\n"

        composer_task = asyncio.ensure_future(asyncio.to_thread(run_composer))

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}"
            yield "\n\n"

        await composer_task

        if "error" in result_holder:
            err = result_holder["error"]
            logger.error(f"Playlist generation failed: {err}")
            yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': 'Generation failed', 'error': err})}"
            yield "\n\n"
            return

        result = result_holder.get("result")
        if not result or not result.tracks:
            yield f"data: {json.dumps({'stage': 'error', 'progress': 0, 'message': 'No matching tracks found', 'error': 'No tracks found for this prompt'})}"
            yield "\n\n"
            return

        title_tracks = [
            {
                "artist": t.artist_name,
                "title": t.title,
                "album": t.album_name,
                "year": t.year,
                "genres": list(t.genres),
                "energy": t.energy,
                "darkness": t.darkness,
                "tempo": t.tempo,
                "texture": t.texture,
            }
            for t in result.tracks
        ]
        genre_hints = result.intent.genre_hints if result.intent else []
        arc_type_str = result.intent.arc_type.value if result.intent else "journey"

        # Generate title
        yield f"data: {json.dumps({'stage': 'titling', 'progress': 90, 'message': 'Naming your playlist...'})}"
        yield "\n\n"
        title = await asyncio.to_thread(
            generate_playlist_title,
            request.prompt,
            title_tracks,
            arc_type_str,
            genre_hints,
        )

        tracks = _candidate_tracks_to_dicts(result.tracks)

        playlist_id = None
        if request.save:
            try:
                playlist_id = await asyncio.to_thread(_save_playlist, request.prompt, result.tracks)
            except Exception as exc:
                logger.error(f"Failed to save playlist: {exc}")

        log_generation(
            prompt=request.prompt,
            arc_type=result.intent.arc_type.value,
            playlist_length=len(result.tracks),
            generation_time_ms=result.generation_time_ms,
            metrics=result.metrics,
        )
        update_track_usage([str(t.id) for t in result.tracks])

        playlist = {
            "id": playlist_id,
            "prompt": request.prompt,
            "title": title,
            "playlist_size": len(tracks),
            "tracks": tracks,
        }
        yield f"data: {json.dumps({'stage': 'complete', 'progress': 100, 'message': 'Playlist ready', 'playlist': playlist})}"
        yield "\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/playlists")
async def list_playlists(limit: int = 50, offset: int = 0) -> list[PlaylistResponse]:
    """List generated playlists."""
    with get_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, prompt, track_count, created_at
            FROM generated_playlists
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (limit, offset))
        return [PlaylistResponse(**row) for row in cur.fetchall()]


@router.get("/playlists/{playlist_id}")
async def get_playlist(playlist_id: str) -> PlaylistResponse:
    """Get a playlist with its tracks."""
    with get_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT id, prompt, track_count, created_at
            FROM generated_playlists
            WHERE id = %s
        """, (playlist_id,))
        playlist = cur.fetchone()

        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        # Get tracks
        cur.execute("""
            SELECT
                t.id, t.title, t.duration_ms,
                a.name as artist_name,
                al.title as album_name,
                pt.position
            FROM playlist_tracks pt
            JOIN tracks t ON pt.track_id = t.id
            LEFT JOIN track_artists ta ON ta.track_id = t.id AND ta.role = 'primary'
            LEFT JOIN artists a ON ta.artist_id = a.id
            LEFT JOIN track_albums tal ON tal.track_id = t.id
            LEFT JOIN albums al ON tal.album_id = al.id
            WHERE pt.playlist_id = %s
            ORDER BY pt.position
        """, (playlist_id,))
        tracks = [dict(row) for row in cur.fetchall()]

        return PlaylistResponse(
            id=str(playlist["id"]),
            prompt=playlist["prompt"],
            track_count=playlist["track_count"],
            created_at=playlist["created_at"],
            tracks=tracks,
        )


# ============================================================================
# M3U Export
# ============================================================================

@router.post("/export/m3u")
async def export_m3u(request: ExportRequest):
    """Export tracks to M3U and return the content."""
    tracks = get_track_files(request.track_ids)

    if not tracks:
        raise HTTPException(status_code=404, detail="No valid tracks found")

    content = generate_m3u(
        tracks=tracks,
        mode=request.mode,
        mapping_name=request.mapping_name,
    )

    return {
        "content": content,
        "track_count": len(tracks),
        "mode": request.mode,
    }


@router.post("/export/m3u/file")
async def export_m3u_to_file(request: ExportRequest):
    """Export tracks to M3U file on server."""
    output_dir = Path(settings.m3u_output_dir)

    try:
        output_path = export_tracks_to_file(
            track_ids=request.track_ids,
            output_path=output_dir,
            mode=request.mode,
            mapping_name=request.mapping_name,
            playlist_name=request.playlist_name,
        )

        return {
            "status": "ok",
            "path": str(output_path),
            "track_count": len(request.track_ids),
        }
    except Exception as e:
        logger.error(f"Error exporting M3U: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/m3u/download/{playlist_id}")
async def download_playlist_m3u(
    playlist_id: str,
    mode: str = "absolute",
    mapping_name: str | None = None,
):
    """Download a playlist as M3U file."""
    # Get playlist tracks
    with get_cursor(dict_cursor=True) as cur:
        cur.execute("""
            SELECT prompt FROM generated_playlists WHERE id = %s
        """, (playlist_id,))
        playlist = cur.fetchone()

        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

    from app.export.m3u import get_playlist_tracks
    tracks = get_playlist_tracks(playlist_id)

    if not tracks:
        raise HTTPException(status_code=404, detail="Playlist has no tracks")

    content = generate_m3u(
        tracks=tracks,
        mode=mode,
        mapping_name=mapping_name,
    )

    # Generate filename from prompt
    prompt = playlist["prompt"][:50].replace(" ", "_")
    filename = f"{prompt}.m3u"

    return StreamingResponse(
        iter([content]),
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ============================================================================
# Jellyfin Export
# ============================================================================

@router.get("/jellyfin/status")
async def jellyfin_status():
    """Check whether Jellyfin is configured and reachable."""
    result = await jellyfin_test_connection()
    return result


@router.post("/export/jellyfin")
async def export_jellyfin(request: JellyfinExportRequest):
    """Export a playlist to Jellyfin by resolving local tracks to Jellyfin IDs."""
    try:
        result = await export_to_jellyfin(
            track_ids=request.track_ids,
            playlist_name=request.playlist_name,
        )
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Export failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Jellyfin export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Search
# ============================================================================

@router.get("/search")
async def search_tracks(q: str, limit: int = 50):
    """Search tracks by text query using embeddings."""
    try:
        results = search_tracks_by_text(q, limit=limit)
        return {"query": q, "results": results}
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Transition Feedback
# ============================================================================

class TransitionFeedbackRequest(BaseModel):
    track_a_id: str
    track_b_id: str
    skipped: bool = False


@router.post("/transitions/record")
async def record_transition_feedback(req: TransitionFeedbackRequest):
    """Record user feedback for a track transition (skip or play signal)."""
    try:
        if req.skipped:
            record_skip(req.track_a_id, req.track_b_id)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error recording transition: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Database Management
# ============================================================================

@router.post("/db/init")
async def initialize_database():
    """Initialize the database schema."""
    try:
        init_database()
        return {"status": "ok", "message": "Database initialized"}
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild-search-vectors")
async def trigger_rebuild_search_vectors():
    """Rebuild BM25 search vectors for all tracks (streaming SSE progress)."""
    return _make_enrichment_stream(
        "Search vector rebuild",
        lambda cb: rebuild_search_vectors(progress_callback=cb),
    )
