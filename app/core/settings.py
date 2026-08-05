from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """

    app_name: str = "Regnova"
    app_version: str = "0.1.0"
    debug: bool = True

    api_prefix: str = "/api/v1"

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/regnova"
    )
    database_echo: bool = False

    secret_key: str = "change-this-secret-key"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.
    """
    return Settings()