"""Helpers for reading GCP bucket resources and secrets."""

from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from google.cloud import secretmanager, storage


def get_storage_client() -> storage.Client:
    """Create an authenticated Google Cloud Storage client."""

    return storage.Client()


@dataclass(frozen=True)
class BucketResource:
    """Metadata for a single object stored in a GCS bucket."""

    name: str
    size: int | None = None
    updated: datetime | None = None
    media_link: str | None = None


async def list_bucket_resources(
    bucket_name: str,
    prefix: str | None = None,
    client: storage.Client | None = None,
) -> list[BucketResource]:
    """List objects stored in a GCS bucket."""

    storage_client = client or get_storage_client()

    def _list_resources() -> list[BucketResource]:
        blobs = storage_client.list_blobs(bucket_name, prefix=prefix)
        return [
            BucketResource(
                name=blob.name,
                size=blob.size,
                updated=blob.updated,
                media_link=blob.media_link,
            )
            for blob in blobs
        ]

    return await asyncio.to_thread(_list_resources)


async def download_bucket_resource(
    bucket_name: str,
    object_name: str,
    destination_path: str | Path,
    client: storage.Client | None = None,
) -> Path:
    """Download a bucket object to a local file."""

    storage_client = client or get_storage_client()
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def _download() -> None:
        blob = storage_client.bucket(bucket_name).blob(object_name)
        blob.download_to_filename(str(destination))

    await asyncio.to_thread(_download)
    return destination


async def read_bucket_resource_text(
    bucket_name: str,
    object_name: str,
    encoding: str = "utf-8",
    client: storage.Client | None = None,
) -> str:
    """Read a text object from a GCS bucket."""

    storage_client = client or get_storage_client()

    def _read_text() -> str:
        blob = storage_client.bucket(bucket_name).blob(object_name)
        return blob.download_as_text(encoding=encoding)

    return await asyncio.to_thread(_read_text)


async def read_bucket_resource_with_metadata(
    bucket_name: str,
    object_name: str,
    client: storage.Client | None = None,
) -> tuple[BytesIO, BucketResource]:
    """Read an object into memory and return it with metadata."""

    storage_client = client or get_storage_client()

    def _read_with_metadata() -> tuple[BytesIO, BucketResource]:
        blob = storage_client.bucket(bucket_name).blob(object_name)
        blob.reload()
        content_buffer = BytesIO(blob.download_as_bytes())
        content_buffer.seek(0)

        metadata = BucketResource(
            name=blob.name,
            size=blob.size,
            updated=blob.updated,
            media_link=blob.media_link,
        )
        return content_buffer, metadata

    return await asyncio.to_thread(_read_with_metadata)


async def write_bucket_resource_text(
    bucket_name: str,
    object_name: str,
    content: str,
    content_type: str = "text/plain; charset=utf-8",
    client: storage.Client | None = None,
) -> None:
    """Write text content to an object in a GCS bucket."""

    storage_client = client or get_storage_client()

    def _write_text() -> None:
        blob = storage_client.bucket(bucket_name).blob(object_name)
        blob.upload_from_string(content, content_type=content_type)

    await asyncio.to_thread(_write_text)


@functools.lru_cache
def get_secret_value(
    project_id: str,
    secret_id: str,
    version: str = "latest",
) -> str:
    """Read a secret value from Google Secret Manager."""

    client = secretmanager.SecretManagerServiceClient()
    secret_name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": secret_name})
    return response.payload.data.decode("utf-8")
