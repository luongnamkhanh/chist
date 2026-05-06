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


def _cmd_search(args: argparse.Namespace) -> int:
    from chistlib import search as searchmod
    stale = searchmod.is_index_stale(paths.db_path(), paths.projects_dir())
    if stale > 0:
        print(
            f"[chist] index stale by {stale} file(s); run 'chist index --incremental'",
            file=sys.stderr,
        )
    hits = searchmod.search(
        db_path=paths.db_path(),
        query=args.query,
        project=args.project,
        since=args.since,
        until=args.until,
        role=args.role,
        limit=args.limit,
    )
    if args.format == "json":
        print(searchmod.format_json(hits))
    else:
        print(searchmod.format_human(hits))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    from chistlib import list_show
    rows = list_show.list_sessions(
        paths.db_path(), project=args.project, since=args.since, limit=args.limit
    )
    if args.format == "json":
        import json as _json
        print(_json.dumps(rows, ensure_ascii=False))
    else:
        print(list_show.format_list_human(rows))
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    from chistlib import list_show
    try:
        out = list_show.show_session(
            paths.db_path(), args.prefix, head=args.head, tail=args.tail
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(out)
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from chistlib import export as exportmod
    try:
        text = exportmod.export_session(
            paths.db_path(), args.prefix, since_message=args.since_message
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    from chistlib import resume as resumemod
    try:
        text = resumemod.resume(
            paths.db_path(),
            prefix=args.prefix,
            last=args.last,
            project=args.project,
            full=args.full,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(text)
    return 0


def _cmd_banner(args: argparse.Namespace) -> int:
    from chistlib import banner as bannermod
    project = args.project
    if args.cwd_project or project is None:
        project = paths.cwd_project_name()
    text = bannermod.render(paths.db_path(), project)
    if text:
        print(text)
    return 0


def _parse_duration(s: str) -> int:
    s = s.strip().lower()
    units = {"d": 1, "w": 7, "y": 365}
    if not s or s[-1] not in units:
        raise ValueError(f"invalid duration '{s}'; use Nd, Nw, or Ny")
    n = int(s[:-1])
    return n * units[s[-1]]


def _cmd_prune(args: argparse.Namespace) -> int:
    from chistlib import archive as archivemod
    days = _parse_duration(args.older_than)
    res = archivemod.prune(
        db_path=paths.db_path(),
        archive_root=paths.archive_dir(),
        projects_root=paths.projects_dir(),
        older_than_days=days,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"would archive {res.would_archive} session(s)")
    else:
        print(f"archived {res.archived} session(s), freed {res.bytes_freed} bytes")
    return 0


def _cmd_vacuum(args: argparse.Namespace) -> int:
    from chistlib import archive as archivemod
    archivemod.vacuum(paths.db_path())
    print("vacuum complete")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chist", description="Claude Code history manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="build or refresh the index")
    pi.add_argument("--incremental", action="store_true", help="only re-index changed files")
    pi.add_argument("--quiet", action="store_true", help="suppress normal output")
    pi.add_argument("--stats", action="store_true", help="print index statistics and exit")
    pi.set_defaults(func=_cmd_index)

    ps = sub.add_parser("search", help="search past sessions")
    ps.add_argument("query", help="search terms")
    ps.add_argument("--project", default=None, help="filter by project")
    ps.add_argument("--since", default=None, help="ISO date or datetime")
    ps.add_argument("--until", default=None, help="ISO date or datetime")
    ps.add_argument("--role", choices=["user", "assistant", "tool_use", "tool_result"], default=None)
    ps.add_argument("--limit", type=int, default=20)
    ps.add_argument("--format", choices=["human", "json"], default="human")
    ps.set_defaults(func=_cmd_search)

    pl = sub.add_parser("list", help="list sessions")
    pl.add_argument("--project", default=None)
    pl.add_argument("--since", default=None)
    pl.add_argument("--limit", type=int, default=50)
    pl.add_argument("--format", choices=["human", "json"], default="human")
    pl.set_defaults(func=_cmd_list)

    psh = sub.add_parser("show", help="show a session by id or prefix")
    psh.add_argument("prefix")
    psh.add_argument("--head", type=int, default=None)
    psh.add_argument("--tail", type=int, default=None)
    psh.set_defaults(func=_cmd_show)

    pe = sub.add_parser("export", help="export a session to Markdown")
    pe.add_argument("prefix")
    pe.add_argument("-o", "--output", default=None)
    pe.add_argument("--since-message", type=int, default=None)
    pe.set_defaults(func=_cmd_export)

    pr = sub.add_parser("resume", help="resume a session (distilled by default)")
    pr.add_argument("prefix", nargs="?", default=None)
    pr.add_argument("--last", action="store_true")
    pr.add_argument("--project", default=None)
    pr.add_argument("--full", action="store_true")
    pr.set_defaults(func=_cmd_resume)

    pb = sub.add_parser("banner", help="print one-line cwd-project banner")
    pb.add_argument("--project", default=None)
    pb.add_argument("--cwd-project", action="store_true")
    pb.set_defaults(func=_cmd_banner)

    pp = sub.add_parser("prune", help="archive old JSONL files (gzip)")
    pp.add_argument("--older-than", required=True, help="duration like 180d, 12w, 1y")
    pp.add_argument("--dry-run", action="store_true")
    pp.set_defaults(func=_cmd_prune)

    pv = sub.add_parser("vacuum", help="rebuild FTS5 index and VACUUM the db")
    pv.set_defaults(func=_cmd_vacuum)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
