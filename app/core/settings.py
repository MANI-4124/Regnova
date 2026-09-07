from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """

    # -------------------------------------------------
    # Application
    # -------------------------------------------------

    app_name: str = "Regnova"
    app_version: str = "0.1.0"
    debug: bool = True

    api_prefix: str = "/api/v1"

    # -------------------------------------------------
    # Database
    # -------------------------------------------------

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/regnova"
    )

    database_echo: bool = False

    # -------------------------------------------------
    # Authentication
    # -------------------------------------------------

    secret_key: str = (
        "change-this-secret-key"
    )

    jwt_algorithm: str = "HS256"

    access_token_expire_minutes: int = 30

    refresh_token_expire_days: int = 7

    bcrypt_rounds: int = 12

    # -------------------------------------------------
    # Document storage (FR-04) - see app/storage/DocumentStorage
    # -------------------------------------------------

    document_storage_backend: str = "local"

    document_storage_root: str = "./storage/documents"

    # 100 MB, per FR-04's V1 upload limit.
    document_max_size_bytes: int = 100 * 1024 * 1024

    # -------------------------------------------------
    # Pydantic
    # -------------------------------------------------

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