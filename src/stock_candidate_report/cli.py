import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .cache import Cache
from .config import load_roots, project_settings
from .export import export_report
from .pipeline import run_report
from .providers.alpha_vantage import AlphaVantageProvider
from .providers.yahoo import YahooProvider
from .watchlist import import_watchlist, load_watchlist, save_watchlist


def parser():
    p = argparse.ArgumentParser(description="Generate traceable candidate-stock Excel snapshots")
    sub = p.add_subparsers(dest="command", required=True)
    imp = sub.add_parser(
        "import-watchlist", help="Read symbols and groups from an existing Excel file"
    )
    imp.add_argument("input", type=Path)
    imp.add_argument("--output", type=Path)
    gen = sub.add_parser("generate", help="Fetch data, calculate growth, export Excel and JSON")
    gen.add_argument("--watchlist", type=Path)
    gen.add_argument("--year", type=int, default=datetime.now(UTC).year)
    gen.add_argument("--refresh", action="store_true")
    gen.add_argument("--offline", action="store_true")
    gen.add_argument(
        "--preview", action="store_true", help="Render workbook ranges for visual review"
    )
    for sp in (imp, gen):
        sp.add_argument("--workspace-config", type=Path)
    return p


def main(argv=None):
    try:
        args = parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code
    try:
        roots = load_roots(args.workspace_config, {})
        settings = project_settings(roots)
        if args.command == "import-watchlist":
            items = import_watchlist(args.input)
            dest = args.output or roots.project_config / "watchlist.json"
            save_watchlist(items, dest)
            print(json.dumps({"stocks": len(items), "watchlist": str(dest)}, ensure_ascii=False))
            return 0
        if args.refresh and args.offline:
            raise ValueError("--refresh and --offline are mutually exclusive")
        if not 2000 <= args.year <= 2100:
            raise ValueError("--year must be between 2000 and 2100")
        items = load_watchlist(args.watchlist or roots.project_config / "watchlist.json")
        providers = [
            YahooProvider(symbol_metadata=settings.get("symbols", {})),
            AlphaVantageProvider(
                os.environ.get("ALPHAVANTAGE_API_KEY")
                or os.environ.get("ALPHA_VANTAGE_API_KEY")
                or settings.get("alpha_vantage", {}).get("api_key", ""),
                metadata=settings.get("symbols", {}),
            ),
        ]
        cache = Cache(
            roots.project_data / "cache.sqlite",
            settings.get("ttl_seconds", {}),
            settings.get("alpha_vantage", {}).get("daily_limit", 25),
        )
        now = datetime.now(UTC)
        result = run_report(
            items,
            args.year,
            now,
            args.refresh,
            args.offline,
            providers,
            cache,
            progress=lambda i, n, s: print(f"[{i}/{n}] {s}", file=sys.stderr),
        )
        folder = roots.project_data / "outputs" / result.run_id
        runtime = settings.get("excel", {})
        xlsx, manifest = export_report(
            result,
            args.year,
            folder,
            artifact_modules=Path(runtime["artifact_modules"])
            if runtime.get("artifact_modules")
            else None,
            node_executable=runtime.get("node_executable"),
            preview=args.preview,
        )
        print(
            json.dumps(
                {"excel": str(xlsx), "manifest": str(manifest), "coverage": result.coverage},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if result.coverage["prices_available"] else 2
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
