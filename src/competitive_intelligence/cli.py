from __future__ import annotations

import argparse
import json
import logging

from .db import init_db, seed_catalog
from .reporting import save_weekly_brief
from .service import collect_all


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Competitive Intelligence Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create database tables and seed the monitored catalog")
    sub.add_parser("collect", help="Collect current real prices from configured public product pages")
    sub.add_parser("report", help="Generate deterministic competitive intelligence brief")
    export_demo = sub.add_parser("export-demo", help="Export the current database to a portable SQLite demo snapshot")
    export_demo.add_argument("--overwrite", action="store_true", help="Replace an existing demo snapshot")
    sources = sub.add_parser("sources", help="Diagnose catalog discovery sources and sitemap availability")
    sources.add_argument("--refresh", action="store_true", help="Ignore discovery cache and refresh public sitemap indexes")

    discover = sub.add_parser(
        "discover",
        help="Expand the catalog automatically using real public product pages and validated cross-store matches",
    )
    discover.add_argument("--target", type=int, default=None, help="Target number of canonical products (default from .env, 100)")
    discover.add_argument("--min-sources", type=int, default=None, help="Minimum validated stores per product (default 2)")
    discover.add_argument("--max-candidates", type=int, default=None, help="Maximum source candidates to inspect")

    agent = sub.add_parser("ask", help="Ask the MCP-powered AI market analyst")
    agent.add_argument("question", nargs="+", help="Question for the market analyst")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    args = build_parser().parse_args()

    if args.command == "init":
        init_db()
        result = seed_catalog()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "collect":
        result = collect_all()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.command == "discover":
        from .config import DISCOVERY_MAX_CANDIDATES, DISCOVERY_MIN_SOURCES, DISCOVERY_TARGET_PRODUCTS
        from .discovery import expand_catalog

        result = expand_catalog(
            target=args.target or DISCOVERY_TARGET_PRODUCTS,
            min_sources=args.min_sources or DISCOVERY_MIN_SOURCES,
            max_candidates=args.max_candidates or DISCOVERY_MAX_CANDIDATES,
        )
        # Synchronize the newly discovered YAML into the database immediately.
        init_db()
        result["database_sync"] = seed_catalog()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.command == "sources":
        from .discovery import CatalogDiscovery
        result = CatalogDiscovery().diagnose_sources(force_refresh=args.refresh)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.command == "export-demo":
        from .snapshot import export_demo_snapshot
        result = export_demo_snapshot(overwrite=args.overwrite)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.command == "report":
        print(save_weekly_brief())
    elif args.command == "ask":
        from .agent import ask_agent_sync
        print(ask_agent_sync(" ".join(args.question)))


if __name__ == "__main__":
    main()
