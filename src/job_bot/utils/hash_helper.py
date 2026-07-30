import hashlib
import json

from pydantic import BaseModel


def model_schema_key(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()

    canonical_schema = json.dumps(
        schema,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    digest = hashlib.sha256(canonical_schema.encode("utf-8")).hexdigest()

    return f"{model.__module__}.{model.__qualname__}:{digest}"


def schema_string_key(
    value: str,
    model_type: type[BaseModel],
) -> str:
    schema = model_type.model_json_schema()

    payload = {
        "value": value,
        "schema": schema,
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
