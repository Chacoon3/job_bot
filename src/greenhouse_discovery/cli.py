from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from greenhouse_discovery.io import write_csv, write_json
from greenhouse_discovery.models import DiscoveryConfig
from greenhouse_discovery.service import GreenhouseGlobalDiscoverer


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Discover live Greenhouse boards from recent public web "
            "indexes. No company names or seed file required."
        )
    )
    result.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of live boards to return.",
    )
    result.add_argument(
        "--max-candidates",
        type=int,
        default=10_000,
        help="Maximum unique token candidates to enumerate.",
    )
    result.add_argument(
        "--crawl-count",
        type=int,
        default=2,
        help="Number of newest Common Crawl indexes to search.",
    )
    result.add_argument(
        "--max-pages-per-query",
        type=int,
        default=100,
        help="Bound Common Crawl pages per host/index query.",
    )
    result.add_argument(
        "--include-empty",
        action="store_true",
        help="Include valid boards that currently have zero open jobs.",
    )
    result.add_argument(
        "--no-enrich-names",
        action="store_true",
        help="Do not fetch board HTML to resolve company display names.",
    )
    result.add_argument(
        "--verification-concurrency",
        type=int,
        default=30,
    )
    result.add_argument(
        "--json-output",
        type=Path,
        default=Path("greenhouse_boards.json"),
    )
    result.add_argument(
        "--csv-output",
        type=Path,
        default=Path("greenhouse_boards.csv"),
    )
    return result


async def run(args: argparse.Namespace) -> int:
    config = DiscoveryConfig(
        limit=args.limit,
        max_candidates=args.max_candidates,
        crawl_count=args.crawl_count,
        max_pages_per_query=args.max_pages_per_query,
        include_empty_boards=args.include_empty,
        enrich_company_names=not args.no_enrich_names,
        verification_concurrency=args.verification_concurrency,
    )

    report = await GreenhouseGlobalDiscoverer(config).discover()
    write_json(args.json_output, report)
    write_csv(args.csv_output, report)

    print(
        f"Discovered {len(report.boards)} live Greenhouse board(s); "
        f"enumerated {report.stats.unique_candidates} candidate token(s); "
        f"verified {report.stats.candidates_verified}."
    )
    print(f"JSON: {args.json_output}")
    print(f"CSV:  {args.csv_output}")

    if report.errors:
        print(f"Non-fatal errors: {len(report.errors)}")

    return 0 if report.boards else 1


def main() -> None:
    raise SystemExit(asyncio.run(run(parser().parse_args())))


if __name__ == "__main__":
    main()
