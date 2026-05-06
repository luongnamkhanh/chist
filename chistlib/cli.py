"""chist CLI dispatcher."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

from chistlib import paths, indexer, db


def _cmd_index(args: argparse.Namespace) -> int:
    if args.stats:
        return _print_stats(args)
    res = indexer.index(
        db_path=paths.db_path(),
        projects_root=paths.projects_dir(),
        incremental=args.incremental,
    )
    if not args.quiet:
        print(
            f"indexed {res.sessions_indexed} session(s), "
            f"{res.messages_indexed} message(s), "
            f"skipped {res.sessions_skipped}, "
            f"elapsed {res.elapsed_seconds:.2f}s"
        )
    return 0


def _print_stats(args: argparse.Namespace) -> int:
    dbp = paths.db_path()
    if not dbp.exists():
        print("index not built yet; run 'chist index'")
        return 0
    with db.connect(dbp) as con:
        rows = con.execute(
            "SELECT COUNT(DISTINCT project) AS p, COUNT(*) AS s, "
            "COALESCE(SUM(msg_count),0) AS m FROM sessions"
        ).fetchone()
        meta = {
            r["key"]: r["value"]
            for r in con.execute("SELECT key, value FROM index_meta")
        }
    size_kb = dbp.stat().st_size // 1024
    print(f"projects: {rows['p']}")
    print(f"sessions: {rows['s']}")
    print(f"messages: {rows['m']}")
    print(f"db size: {size_kb} KB")
    print(f"last incremental: {meta.get('last_incremental_at', 'never')}")
    print(f"last full: {meta.get('last_full_index_at', 'never')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chist", description="Claude Code history manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="build or refresh the index")
    pi.add_argument("--incremental", action="store_true", help="only re-index changed files")
    pi.add_argument("--quiet", action="store_true", help="suppress normal output")
    pi.add_argument("--stats", action="store_true", help="print index statistics and exit")
    pi.set_defaults(func=_cmd_index)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
