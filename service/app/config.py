from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    # Database (PostgreSQL + pgvector)
    database_url: str = "postgresql://playlist:playlist_dev@localhost:5432/playlist_generator"
    
    # Scanner
    music_directories: str = "/music"  # Comma-separated paths
    scan_threads: int = 8
    
    # Export
    m3u_output_dir: str = "/playlists"
    
    # Embeddings
    embedding_model_version: int = 1
    
    # Last.fm
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    
    # OpenAI (for title generation)
    openai_api_key: str = ""
    
    # Legacy (deprecated, kept for migration)
    jellyfin_url: str = ""
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    database_path: str = ""  # Old DuckDB path

    model_config = SettingsConfigDict(
        env_file=[
            _PROJECT_ROOT / ".env",
            ".env",
        ],
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    @property
    def music_dirs(self) -> list[str]:
        """Parse comma-separated music directories."""
        return [d.strip() for d in self.music_directories.split(",") if d.strip()]


settings = Settings()
