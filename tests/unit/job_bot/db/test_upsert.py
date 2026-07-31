from unittest.mock import Mock

import pytest

from job_bot.db.job_models import Job
from job_bot.db.upsert import _resolve_upsert_metadata, batched_upsert


def _row(index: int) -> dict[str, object]:
    return {
        "source": "greenhouse",
        "job_title": f"Engineer {index}",
        "url": f"https://example.com/jobs/{index}",
    }


def test_batched_upsert_executes_batches_and_returns_row_count() -> None:
    session = Mock()

    rows_processed = batched_upsert(
        session,
        Job,
        (_row(index) for index in range(5)),
        conflict_columns=[Job.url],
        update_columns=[Job.source, Job.job_title],
        batch_size=2,
    )

    assert rows_processed == 5
    assert session.execute.call_count == 3
    statements = [str(call.args[0]) for call in session.execute.call_args_list]
    assert all("ON CONFLICT (url) DO UPDATE" in statement for statement in statements)


def test_batched_upsert_obeys_bind_parameter_limit() -> None:
    session = Mock()

    batched_upsert(
        session,
        Job,
        [_row(1), _row(2)],
        conflict_columns=["url"],
        update_columns=["job_title"],
        batch_size=10,
        max_bind_parameters=3,
    )

    assert session.execute.call_count == 2


def test_batched_upsert_rejects_inconsistent_rows() -> None:
    session = Mock()

    with pytest.raises(ValueError, match="same columns"):
        batched_upsert(
            session,
            Job,
            [_row(1), {"source": "greenhouse", "url": "https://example.com/jobs/2"}],
            conflict_columns=["url"],
            update_columns=["job_title"],
        )


def test_batched_upsert_caches_resolved_model_metadata() -> None:
    session = Mock()
    _resolve_upsert_metadata.cache_clear()

    for index in range(2):
        batched_upsert(
            session,
            Job,
            [_row(index)],
            conflict_columns=[Job.url],
            update_columns=[Job.job_title],
        )

    cache_info = _resolve_upsert_metadata.cache_info()
    assert cache_info.misses == 1
    assert cache_info.hits == 1
