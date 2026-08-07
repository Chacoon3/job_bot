from dataclasses import dataclass
from enum import StrEnum


class StoragePolicy(StrEnum):
    PLAIN = "plain"
    ENCRYPT = "encrypt"
    HASH = "hash"


class ExposurePolicy(StrEnum):
    PLAIN = "plain"
    MASK = "mask"
    REDACT = "redact"


@dataclass(frozen=True)
class Sensitive:
    storage: StoragePolicy
    logging: ExposurePolicy = ExposurePolicy.REDACT
    llm: ExposurePolicy = ExposurePolicy.REDACT
