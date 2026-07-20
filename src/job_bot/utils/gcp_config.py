import os
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class GCPConfig:
    GCP_PROJECT_ID: str
    GCS_API_BASE_URL: str
    GCS_READ_ONLY_SCOPE: str
    GCP_BUCKET_NAME: str


@cache
def get_gcp_config() -> GCPConfig:
    """Get GCP configuration from environment variables."""
    return GCPConfig(
        GCP_PROJECT_ID=os.environ.get("GCP_PROJECT_ID", ""),
        GCS_API_BASE_URL=os.environ.get(
            "GCS_API_BASE_URL", "https://storage.googleapis.com/storage/v1"
        ),
        GCS_READ_ONLY_SCOPE=os.environ.get(
            "GCS_READ_ONLY_SCOPE", "https://www.googleapis.com/auth/devstorage.read_only"
        ),
        GCP_BUCKET_NAME=os.environ.get("GCP_BUCKET_NAME", ""),
    )
