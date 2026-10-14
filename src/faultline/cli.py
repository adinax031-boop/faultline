"""Command-line interface. Exit 2 = input error; exit 1 = policy violation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from xml.sax.saxutils import escape

from . import __version__
from .analysis import analyze
from .report import html_report, markdown_report
from .store import Store


def demo_data() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        with Store(Path(directory) / "demo.db") as store:
            for run in range(12):
                cases = []
                for name, fail, seconds in [("refresh_token", run % 3 == 0, .24), ("checkout_concurrent", run % 4 < 2, 1.8), ("search_index", False, .08), ("migration_schema", run >= 6, .51), ("webhook_delivery", run % 5 == 0, .95)]:
                    failure = '<failure message="Timeout waiting for worker 123">Timeout waiting for worker 123</failure>' if fail else ''
                    cases.append(f'<testcase classname="platform.{escape(name.split("_")[0])}" name="{escape(name)}" time="{seconds}">{failure}</testcase>')
                path = Path(directory) / "report.xml"
                path.write_text('<testsuite name="integration">' + ''.join(cases) + '</testsuite>', encoding="utf-8")
                # Migration changes at the revision boundary: correctly not flaky.
                store.ingest(path, run_id=f"run-{run:02d}", revision="a1b2c3" if run < 6 else "d4e5f6", environment="linux-py312")
            return analyze(store.observations())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="faultline", description="Evidence-first flaky-test intelligence")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Atomically import a JUnit report")
    ingest.add_argument("report", type=Path)
    ingest.add_argument("--db", type=Path, default=Path("faultline.db"))
    ingest.add_argument("--run", required=True)
    ingest.add_argument("--revision", required=True)
    ingest.add_argument("--environment", default="default")
    ingest.add_argument("--shard", default="default")
    report = commands.add_parser("report", help="Export HTML, JSON, or Markdown")
    report.add_argument("--db", type=Path, default=Path("faultline.db"))
    report.add_argument("--format", choices=["html", "json", "markdown"], default="html")
    report.add_argument("--output", type=Path)
    report.add_argument("--fail-on-instability", action="store_true")
    demo = commands.add_parser("demo", help="Generate a reproducible synthetic dashboard")
    demo.add_argument("--output", type=Path, default=Path("faultline-demo.html"))
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            with Store(args.db) as store:
                count = store.ingest(args.report, run_id=args.run, revision=args.revision, environment=args.environment, shard=args.shard)
            print(f"Imported {count} observations" if count else "Already imported; no changes")
            return 0
        if args.command == "demo":
            data = demo_data()
            output = html_report(data)
        else:
            if not args.db.is_file():
                raise ValueError(f"Database does not exist: {args.db}")
            with Store(args.db) as store:
                data = analyze(store.observations())
            output = {"html": html_report, "json": lambda d: json.dumps(d, indent=2, allow_nan=False), "markdown": markdown_report}[args.format](data)
        if args.output:
            args.output.write_text(output, encoding="utf-8")
            print(f"Wrote {args.output}")
        else:
            print(output)
        return int(bool(getattr(args, "fail_on_instability", False) and data["summary"]["unstable"]))
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"faultline: {exc}", file=sys.stderr)
        return 2
