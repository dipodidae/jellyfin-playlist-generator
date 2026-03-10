from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine project root for local development
# __file__ = service/app/config.py → parent.parent.parent = playlist-generator/
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # playlist-generator/
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "data" / "music.duckdb")


class Settings(BaseSettings):
    jellyfin_url: str = "https://jellyfin.4eva.me"
    jellyfin_api_key: str = ""
    jellyfin_user_id: str = ""
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""
    openai_api_key: str = ""
    database_path: str = _DEFAULT_DB_PATH

    model_config = SettingsConfigDict(
        env_file=[
            _PROJECT_ROOT / ".env",
            Path(__file__).parent.parent.parent / ".env",  # service/.env
            ".env",
        ],
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
