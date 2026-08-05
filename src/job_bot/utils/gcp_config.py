from dataclasses import dataclass
from functools import cache

from job_bot.config import settings


@dataclass(frozen=True)
class GCPConfig:
    GCP_PROJECT_ID: str
    GCS_API_BASE_URL: str
    GCS_READ_ONLY_SCOPE: str
    GCP_BUCKET_NAME: str


@cache
def get_gcp_config() -> GCPConfig:
    """Get GCP configuration from environment variables."""
    cfg = settings()
    return GCPConfig(
        GCP_PROJECT_ID=cfg.GCP_PROJECT_ID or "",
        GCS_API_BASE_URL=cfg.GCS_API_BASE_URL,
        GCS_READ_ONLY_SCOPE=cfg.GCS_READ_ONLY_SCOPE,
        GCP_BUCKET_NAME=cfg.GCP_BUCKET_NAME or "",
    )
