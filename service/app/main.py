import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Use v3 (PostgreSQL) or legacy (DuckDB) based on environment
USE_POSTGRES = os.getenv("DATABASE_URL", "").startswith("postgresql")

if USE_POSTGRES:
    from app.database_pg import init_database, get_stats, close_pool
    from app.api.routes_v3 import router
    logger.info("Using PostgreSQL + pgvector backend")
else:
    from app.database import init_database, get_stats
    from app.api.routes import router
    close_pool = lambda: None  # No-op for DuckDB
    logger.info("Using DuckDB backend (legacy)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_database()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down...")
    close_pool()


app = FastAPI(
    title="Playlist Generator Service",
    description="Music intelligence service for playlist generation",
    version="3.0.0" if USE_POSTGRES else "2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
