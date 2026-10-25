#!/usr/bin/env python
"""Run AgentCore Alembic commands without requiring alembic.ini.

Examples:
  python scripts/alembic_cli.py heads
  python scripts/alembic_cli.py current
  python scripts/alembic_cli.py upgrade heads
  python scripts/alembic_cli.py revision --autogenerate -m "add foo column"
  python scripts/alembic_cli.py merge heads -m "merge concurrent heads"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_BASE_DIR = ROOT_DIR / "src" / "backend" / "base"
AGENTCORE_BASE_DIR = BACKEND_BASE_DIR / "agentcore"
ALEMBIC_DIR = AGENTCORE_BASE_DIR / "alembic"


def build_config() -> Config:
    """Create an Alembic config entirely in code."""
    sys.path.insert(0, str(BACKEND_BASE_DIR))

    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_BASE_DIR))
    return cfg


def require_message(args: argparse.Namespace) -> str:
    if not args.message:
        raise SystemExit("This command requires -m/--message.")
    return args.message


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AgentCore Alembic commands without alembic.ini.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("heads", help="Show Alembic heads.")
    subparsers.add_parser("current", help="Show current DB revision.")
    subparsers.add_parser("history", help="Show Alembic history.")
    subparsers.add_parser("check", help="Run Alembic check.")

    upgrade_parser = subparsers.add_parser("upgrade", help="Upgrade the database.")
    upgrade_parser.add_argument("revision", nargs="?", default="heads")

    downgrade_parser = subparsers.add_parser("downgrade", help="Downgrade the database.")
    downgrade_parser.add_argument("revision")

    stamp_parser = subparsers.add_parser("stamp", help="Stamp the database revision.")
    stamp_parser.add_argument("revision")

    revision_parser = subparsers.add_parser("revision", help="Create a revision.")
    revision_parser.add_argument("-m", "--message")
    revision_parser.add_argument("--autogenerate", action="store_true")
    revision_parser.add_argument("--head", default="heads")
    revision_parser.add_argument("--splice", action="store_true")
    revision_parser.add_argument("--branch-label")
    revision_parser.add_argument("--rev-id")

    merge_parser = subparsers.add_parser("merge", help="Merge revisions.")
    merge_parser.add_argument("revisions", nargs="+", help='Use "heads" to merge all heads.')
    merge_parser.add_argument("-m", "--message")
    merge_parser.add_argument("--branch-label")
    merge_parser.add_argument("--rev-id")

    args = parser.parse_args()
    cfg = build_config()

    if args.command == "heads":
        command.heads(cfg)
        return 0
    if args.command == "current":
        command.current(cfg)
        return 0
    if args.command == "history":
        command.history(cfg)
        return 0
    if args.command == "check":
        command.check(cfg)
        return 0
    if args.command == "upgrade":
        command.upgrade(cfg, args.revision)
        return 0
    if args.command == "downgrade":
        command.downgrade(cfg, args.revision)
        return 0
    if args.command == "stamp":
        command.stamp(cfg, args.revision)
        return 0
    if args.command == "revision":
        command.revision(
            cfg,
            message=require_message(args),
            autogenerate=args.autogenerate,
            head=args.head,
            splice=args.splice,
            branch_label=args.branch_label,
            rev_id=args.rev_id,
        )
        return 0
    if args.command == "merge":
        command.merge(
            cfg,
            args.revisions,
            message=require_message(args),
            branch_label=args.branch_label,
            rev_id=args.rev_id,
        )
        return 0

    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
