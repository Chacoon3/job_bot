import json
import os
import tempfile
from functools import cache
from pathlib import Path
from typing import Any, Generic, Iterable, Optional, TypeVar

from google.cloud.storage import Client
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class GCSFlatFileTable(Generic[T]):
    def __init__(
        self,
        bucket,
        table_name: str,
        model_cls: type[T],
        primary_key: str = "id",
        prefix: str = "flatdb",
    ):
        self.bucket = bucket
        self.table_name = table_name
        self.model_cls = model_cls
        self.primary_key = primary_key
        self.prefix = prefix.strip("/")
        self.index: dict[str, int] = {}

        self.create_if_not_exists()
        self._load_index()

    def _blob_name(self) -> str:
        return f"{self.prefix}/{self.table_name}.jsonl"

    def _blob(self):
        return self.bucket.blob(self._blob_name())

    def create_if_not_exists(self) -> None:
        blob = self._blob()
        if not blob.exists():
            blob.upload_from_string("", content_type="application/jsonl")

    def _download(self, path: Path) -> None:
        self._blob().download_to_filename(path)

    def _upload(self, path: Path) -> None:
        self._blob().upload_from_filename(path, content_type="application/jsonl")

    def _get_pk(self, obj: T) -> str:
        value = getattr(obj, self.primary_key)
        return str(value)

    def _load_index(self) -> None:
        self.index.clear()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / f"{self.table_name}.jsonl"
            self._download(path)

            with path.open("rb") as f:
                while True:
                    offset = f.tell()
                    line = f.readline()

                    if not line:
                        break

                    if not line.strip():
                        continue

                    record = json.loads(line)
                    key = record["key"]

                    if record["op"] == "delete":
                        self.index.pop(key, None)
                    else:
                        self.index[key] = offset

    def insert(self, obj: T) -> T:
        key = self._get_pk(obj)

        if key in self.index:
            raise ValueError(f"Duplicate primary key: {key}")

        self._append(
            {
                "op": "insert",
                "key": key,
                "value": obj.model_dump(mode="json"),
            }
        )

        return obj

    def get(self, key: str) -> Optional[T]:
        key = str(key)
        offset = self.index.get(key)

        if offset is None:
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / f"{self.table_name}.jsonl"
            self._download(path)

            with path.open("rb") as f:
                f.seek(offset)
                record = json.loads(f.readline())

        return self.model_cls.model_validate(record["value"])

    def update(self, obj: T) -> T:
        key = self._get_pk(obj)

        if key not in self.index:
            raise KeyError(f"Primary key not found: {key}")

        self._append(
            {
                "op": "update",
                "key": key,
                "value": obj.model_dump(mode="json"),
            }
        )

        return obj

    def upsert(self, obj: T) -> T:
        key = self._get_pk(obj)

        op = "update" if key in self.index else "insert"

        self._append(
            {
                "op": op,
                "key": key,
                "value": obj.model_dump(mode="json"),
            }
        )

        return obj

    def delete(self, key: str) -> None:
        key = str(key)

        if key not in self.index:
            return

        self._append(
            {
                "op": "delete",
                "key": key,
            }
        )

    def all(self) -> list[T]:
        return [obj for _, obj in self.scan()]

    def scan(self) -> Iterable[tuple[str, T]]:
        for key in list(self.index.keys()):
            obj = self.get(key)
            if obj is not None:
                yield key, obj

    def filter(self, **conditions: Any) -> list[T]:
        result: list[T] = []

        for _, obj in self.scan():
            matched = True

            for field, expected in conditions.items():
                if getattr(obj, field) != expected:
                    matched = False
                    break

            if matched:
                result.append(obj)

        return result

    def compact(self) -> None:
        rows = list(self.scan())

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / f"{self.table_name}.jsonl"

            with path.open("w", encoding="utf-8") as f:
                for key, obj in rows:
                    f.write(
                        json.dumps(
                            {
                                "op": "insert",
                                "key": key,
                                "value": obj.model_dump(mode="json"),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

            self._upload(path)

        self._load_index()

    def _append(self, record: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / f"{self.table_name}.jsonl"

            self._download(path)

            with path.open("ab") as f:
                offset = f.tell()
                f.write(json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n")

            self._upload(path)

        key = record["key"]

        if record["op"] == "delete":
            self.index.pop(key, None)
        else:
            self.index[key] = offset


class GCSFlatFileDBClient:
    def __init__(self, bucket_name: str, prefix: str = "flatdb"):
        self.client = Client()
        self.bucket = self.client.bucket(bucket_name)
        self.prefix = prefix.strip("/")
        self.tables: dict[str, GCSFlatFileTable[Any]] = {}

    def register_table(
        self,
        table_name: str,
        model_cls: type[T],
        primary_key: str = "id",
    ) -> None:
        table = GCSFlatFileTable(
            bucket=self.bucket,
            table_name=table_name,
            model_cls=model_cls,
            primary_key=primary_key,
            prefix=self.prefix,
        )
        self.tables[table_name] = table

    def insert(self, table_name: str, obj: T) -> T:
        return self._table(table_name).insert(obj)

    def get(self, table_name: str, key: str) -> Optional[BaseModel]:
        return self._table(table_name).get(key)

    def update(self, table_name: str, obj: T) -> T:
        return self._table(table_name).update(obj)

    def upsert(self, table_name: str, obj: T) -> T:
        return self._table(table_name).upsert(obj)

    def delete(self, table_name: str, key: str) -> None:
        self._table(table_name).delete(key)

    def all(self, table_name: str) -> list[BaseModel]:
        return self._table(table_name).all()

    def filter(self, table_name: str, **conditions: Any) -> list[BaseModel]:
        return self._table(table_name).filter(**conditions)

    def compact(self, table_name: str) -> None:
        self._table(table_name).compact()

    def _table(self, table_name: str) -> GCSFlatFileTable[Any]:
        if table_name not in self.tables:
            raise KeyError(f"Table not registered: {table_name}")
        return self.tables[table_name]


@cache
def get_gcs_flat_file_db_client() -> GCSFlatFileDBClient:
    return GCSFlatFileDBClient(
        bucket_name=os.getenv("GCP_BUCKET_NAME"), prefix=f"trade-3{os.getenv('ENV')}-flatdb"
    )
