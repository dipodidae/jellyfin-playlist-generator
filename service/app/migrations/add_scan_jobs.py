import logging

from app.database_pg import get_connection

logger = logging.getLogger(__name__)


def migrate():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scan_jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    status VARCHAR(20) NOT NULL,
                    scan_type VARCHAR(20) NOT NULL DEFAULT 'incremental',
                    stage VARCHAR(50) NOT NULL DEFAULT 'idle',
                    started_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now(),
                    completed_at TIMESTAMPTZ,
                    current INTEGER DEFAULT 0,
                    total INTEGER DEFAULT 0,
                    files_found INTEGER DEFAULT 0,
                    files_scanned INTEGER DEFAULT 0,
                    files_skipped INTEGER DEFAULT 0,
                    tracks_added INTEGER DEFAULT 0,
                    tracks_updated INTEGER DEFAULT 0,
                    files_missing INTEGER DEFAULT 0,
                    errors INTEGER DEFAULT 0,
                    current_message TEXT,
                    error_summary TEXT
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_jobs_status_started ON scan_jobs(status, started_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_jobs_completed ON scan_jobs(completed_at DESC)")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS scan_job_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    job_id UUID NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    stage VARCHAR(50) NOT NULL,
                    event_type VARCHAR(20) NOT NULL DEFAULT 'progress',
                    message TEXT,
                    current INTEGER DEFAULT 0,
                    total INTEGER DEFAULT 0,
                    payload JSONB
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_job_events_job_created ON scan_job_events(job_id, created_at DESC)")

    logger.info("Scan job tables are ready")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate()
