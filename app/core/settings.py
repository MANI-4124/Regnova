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
    # Malware scanning (AC-FR-04-01) - see app/scanning/MalwareScanner
    # -------------------------------------------------

    # Deliberately defaults to "noop" - safe for local dev and tests,
    # but a REAL security consequence if left unset in production
    # (uploads would never be scanned at all - see CLAUDE.md "Malware
    # scanning"). Must be explicitly set to "clamav" via
    # MALWARE_SCANNER_BACKEND for any deployed environment.
    malware_scanner_backend: str = "noop"

    clamav_host: str = "localhost"

    clamav_port: int = 3310

    clamav_timeout_seconds: float = 30.0

    # -------------------------------------------------
    # Semantic analysis (Claims + Label) - see app/analysis/ + CLAUDE.md
    # -------------------------------------------------

    # Defaults to "stub" (StubSemanticAnalyzer - always returns the benign
    # answer per question) for the same reason malware_scanner_backend defaults
    # to "noop": the AI path stays completely inert until an environment
    # deliberately opts in. Set to "gemini" via SEMANTIC_ANALYZER_BACKEND.
    semantic_analyzer_backend: str = "stub"

    # .env ONLY. Never a literal in code, never committed - .env is gitignored
    # the same way SECRET_KEY / DATABASE_URL are.
    gemini_api_key: str | None = None

    # Verified working against AI Studio on 2026-09-10 (gemini-2.0-flash and
    # gemini-2.5-flash are both retired now - the API 404s them). This is a
    # setting, not hardcoded; the model string that lands on a proposal is
    # whatever the API reports back (modelVersion), not this default.
    gemini_model: str = "gemini-3.6-flash"

    ai_analyzer_timeout_seconds: float = 20.0

    # Demo default, flagged for RegNova Knowledge Lead sign-off - no spec number
    # exists for this the way D5.1 supplies DEFAULT_MIN_CONFIDENCE. A model
    # "equivalent" verdict BELOW this threshold -> NO proposal (recorded on the
    # StepRun trace only). See CLAUDE.md.
    claim_semantic_confidence_threshold: float = 0.7

    # ⚠ Google's AI Studio free tier may train on submitted inputs. Must be
    # explicitly set true to use the "gemini" backend at all - a deliberate
    # speed-bump forcing the operator to assert "only synthetic data is in this
    # environment". NOT a technical guarantee - the real fix
    # (Organization.is_synthetic) is logged, not built. See app/analysis/ and
    # CLAUDE.md "Claims semantic analysis".
    gemini_synthetic_data_ack: bool = False

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