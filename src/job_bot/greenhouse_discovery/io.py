from __future__ import annotations

import csv
import json
from pathlib import Path

from job_bot.greenhouse_discovery.models import DiscoveryReport


def write_json(path: Path, report: DiscoveryReport) -> None:
    path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def write_csv(path: Path, report: DiscoveryReport) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        fields = [
            "company_name",
            "board_token",
            "board_url",
            "api_url",
            "active_job_count",
            "sample_job_titles",
            "crawl_indexes",
            "discovered_urls",
            "verified_at",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for board in report.boards:
            writer.writerow(
                {
                    "company_name": board.company_name or "",
                    "board_token": board.token,
                    "board_url": board.board_url,
                    "api_url": board.api_url,
                    "active_job_count": board.active_job_count,
                    "sample_job_titles": " | ".join(board.sample_job_titles),
                    "crawl_indexes": " | ".join(board.crawl_indexes),
                    "discovered_urls": " | ".join(board.discovered_urls),
                    "verified_at": board.verified_at.isoformat(),
                }
            )
