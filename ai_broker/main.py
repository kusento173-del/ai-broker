from __future__ import annotations

import argparse
from pathlib import Path

from .config import DEFAULT_CONFIG
from .pipeline import run_loop, run_once


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI broker live warning workflow.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--refresh-export", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--call-ai", action="store_true")
    parser.add_argument("--write-table", action="store_true")
    parser.add_argument("--send-table-webhook", action="store_true")
    parser.add_argument("--rerun-today", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--loop", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.write_table and not args.call_ai:
        raise SystemExit("--write-table 需要同时加 --call-ai")
    if args.send_table_webhook and not args.call_ai:
        raise SystemExit("--send-table-webhook 需要同时加 --call-ai")
    if args.loop:
        run_loop(args)
    else:
        run_once(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

