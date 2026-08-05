from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Core environment
    APP_ENV: str = "local"
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800

    # LLM / API credentials
    OPENAI_API_KEY: SecretStr | None = None
    GOOGLE_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    HUGGINGFACEHUB_API_TOKEN: SecretStr | None = None
    TAVILY_API_KEY: SecretStr | None = None
    JOB_BOT_LLM_MODEL: str = "gpt-5.6-luna"
    OLLAMA_BASE_URL: str | None = None

    # Cache
    REDIS_URL: str | None = None
    REDIS_CACHE_PREFIX: str = "job_bot:cache"
    REDIS_SOCKET_TIMEOUT_SECONDS: float = 1.0
    APP_CACHE_TTL_SECONDS: float | None = None
    DISK_CACHE_DIR: str = "./.cache"

    # Telemetry
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT: str | None = None
    OTEL_EXPORTER_OTLP_METRICS_ENDPOINT: str | None = None
    OTEL_SDK_DISABLED: str | None = None
    OTEL_SERVICE_NAME: str = "job-bot"
    OTEL_TRACES_EXPORTER: str = "otlp"
    OTEL_METRICS_EXPORTER: str = "otlp"

    # GCP / storage
    GCP_PROJECT_ID: str | None = None
    GCP_BUCKET_NAME: str | None = None
    GCS_API_BASE_URL: str = "https://storage.googleapis.com/storage/v1"
    GCS_READ_ONLY_SCOPE: str = "https://www.googleapis.com/auth/devstorage.read_only"
    ENV: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


def settings() -> Settings:
    return Settings(_env_file=None)


def setting_value(name: str) -> str | None:
    """Return a setting by field name as a string, unwrapping secrets."""
    cfg = settings()
    if name not in cfg.model_fields_set:
        return None
    value = getattr(cfg, name, None)
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if value is None:
        return None
    return str(value)
