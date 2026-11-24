"""CLI entrypoint for GM v3 (plus lightweight memoryctl compatibility shim)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .board import STATES, Board
from .facts import backfill_headlines
from .harnesses import doctor, install_harnesses
from .index import build_context, embed_missing, index_single_item, recall, reindex_all, sync_index
from .migrate import migrate_v2
from .store import forget_memory, gm_home, list_projects, read_memory, save_memory, update_project
from .validation import FACT_HEADLINE_THRESHOLD, needs_headline, validation_message


def _board_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="board_cmd", required=True)
    assign = sub.add_parser("assign", help="Open an assignment with a supervisor, an assignee, and a brief")
    assign.add_argument("title")
    assign.add_argument("--brief", required=True)
    assign.add_argument("--by", required=True, help="Supervisor harness or session")
    assign.add_argument("--to", required=True, help="Implementer harness or session")
    assign.add_argument("--project", default="")
    listing = sub.add_parser("list", help="List assignments, optionally scoped to a harness or session")
    listing.add_argument("--for", dest="actor", default="", help="Show assignments to or supervised by this identity")
    listing.add_argument("--status", choices=STATES, default="")
    listing.add_argument("--project", default="")
    read = sub.add_parser("read", help="Read the brief, updates, and available status changes")
    read.add_argument("id", type=int)
    post = sub.add_parser("post", help="Reply to an assignment or change its state")
    post.add_argument("id", type=int)
    post.add_argument("message", nargs="?", default="")
    post.add_argument("--by", required=True, help="Posting harness or session")
    post.add_argument("--status", choices=STATES, default="")
    for command in (assign, listing, read, post):
        command.add_argument("--json", action="store_true", help="Print machine-readable results")


def _board_command(root: Path, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    board = Board(root)
    try:
        if args.board_cmd == "assign":
            result = board.assign(title=args.title, brief=args.brief, supervisor=args.by, assignee=args.to, project=args.project)
        elif args.board_cmd == "list":
            result = board.list(actor=args.actor, status=args.status, project=args.project)
        elif args.board_cmd == "read":
            result = board.read(args.id)
        else:
            result = board.post(args.id, author=args.by, message=args.message, status=args.status)
    except ValidationError as exc:
        parser.error(validation_message(exc))
    except ValueError as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.board_cmd == "list":
        if not result["assignments"]:
            print("No assignments match.")
        for row in result["assignments"]:
            print(f"#{row['id']}  {STATES[row['status']]}  {row['title']}  ({row['supervisor']} → {row['assignee']})")
    elif args.board_cmd == "read":
        print(f"#{result['id']}  {result['title']}  ·  {STATES[result['status']]}")
        for post in result["posts"]:
            label = STATES.get(post["status"], "Reply")
            print(f"\n{post['created_at']}  {post['author']}  ·  {label}")
            if post["message"]:
                print(post["message"])
        for action in result["actions"]:
            print(f"\n{action['label']}  --status {action['status']} --by {action['actor']}")
    else:
        print(f"#{result['id']}  {STATES[result['status']]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brain", description="Brain v3.2 — multi-harness local memory")
    parser.add_argument("--home", help="Override GM_HOME directory (default: ~/memories)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ctx = sub.add_parser("context", help="Print L1 compact session context")
    p_ctx.add_argument("project", nargs="?", default="", help="Optional project name")
    p_ctx.add_argument("--full", action="store_true", help="Include full profile instead of summary")
    p_ctx.add_argument("--hook", choices=["claude"], help="Format output for a harness hook")

    p_rec = sub.add_parser("search", aliases=["recall"], help="Hybrid search (FTS5 + Ollama embeddings + ONNX rerank)")
    p_rec.add_argument("query", nargs="+", help="Search query")
    p_rec.add_argument("--project", default="")
    p_rec.add_argument("--kind", default="")
    p_rec.add_argument("--bucket", default="", choices=["", "fact", "episode"])
    p_rec.add_argument("--since", default="", help="Inclusive start date (YYYY-MM-DD)")
    p_rec.add_argument("--until", default="", help="Inclusive end date (YYYY-MM-DD)")
    p_rec.add_argument("--no-rerank", action="store_true")
    p_rec.add_argument("--limit", type=int, default=8)
    p_rec.add_argument("--json", action="store_true")

    p_read = sub.add_parser("read", help="Read full memory by ID or path (L3)")
    p_read.add_argument("id_or_path")

    p_rem = sub.add_parser("store", aliases=["remember"], help="Save one verified fact, decision, lesson, or milestone")
    p_rem.add_argument("content", help="Markdown body (or value when using --subject/--predicate)")
    p_rem.add_argument("--title", default="")
    p_rem.add_argument("--headline", default="", help=f"One-line summary required for facts over {FACT_HEADLINE_THRESHOLD} characters")
    p_rem.add_argument("--kind", default="fact", choices=["fact", "episode", "decision", "lesson", "journal", "project"])
    p_rem.add_argument("--project", default="")
    p_rem.add_argument("--tags", default="", help="Comma-separated tags")
    p_rem.add_argument("--subject", default="", help="Optional 3-part fact subject (auto-supersedes)")
    p_rem.add_argument("--predicate", default="", help="Optional 3-part fact predicate (auto-supersedes)")
    p_rem.add_argument("--source", default="", help="Optional provenance (user, file path, commit, URL)")
    p_rem.add_argument("--epistemic", default="", choices=["", "verified", "decision", "lesson", "hypothesis"])
    p_rem.add_argument("--author", default="", help="Optional harness/author label")

    p_flush = sub.add_parser("flush-prompt", help="Emit curated PreCompact flush nudge for harness hooks")
    p_flush.add_argument("--hook", choices=["claude"], default="claude")

    p_proj = sub.add_parser("project", help="List, read, or update project state")
    p_proj.add_argument("name", nargs="?", default="")
    p_proj.add_argument("--update", default="")
    p_proj.add_argument("--repo-root", default="", help="Bind local repository root path for auto-detection")

    p_fgt = sub.add_parser("forget", help="Archive/remove a memory")
    p_fgt.add_argument("id_or_path")

    sub.add_parser("reindex", help="Rebuild SQLite chunk FTS5 + Ollama embeddings from Markdown")
    sub.add_parser("embed-missing", help="Embed any unembedded chunks via Ollama (lock-guarded background worker)")

    p_mig = sub.add_parser("migrate", help="Non-destructive v2 -> v3 migration")
    p_mig.add_argument("--dry-run", action="store_true")
    p_headline = sub.add_parser("backfill-headlines", help="Fill missing headlines across the Facts view")
    p_headline.add_argument("--dry-run", action="store_true", help="Report missing headlines without changing the library")
    p_board = sub.add_parser("board", help="Assign work and post updates across local agent sessions")
    _board_arguments(p_board)

    sub.add_parser("install-harnesses", help="Wire GM across Antigravity, Claude Code, Codex, Gemini CLI, OpenCode")
    sub.add_parser("doctor", help="Check multi-harness health and index status")
    sub.add_parser("stats", help="Show MCP tool usage & adherence telemetry")
    sub.add_parser("app", aliases=["ui"], help="Open the Brain desktop workspace")

    args = parser.parse_args(argv)
    root = gm_home(args.home)

    if args.cmd == "board":
        return _board_command(root, args, p_board)

    if args.cmd in ("app", "ui"):
        from .desktop import launch

        return launch(root)

    if args.cmd == "context":
        ctx = build_context(root, project=args.project, compact=not args.full)
        if args.hook == "claude":
            payload = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": ctx,
                }
            }
            print(json.dumps(payload))
        else:
            print(ctx)
        return 0

    if args.cmd in ("recall", "search"):
        q = " ".join(args.query)
        try:
            hits = recall(root, query=q, project=args.project, kind=args.kind, bucket=args.bucket,
                          since=args.since, until=args.until, limit=args.limit, use_rerank=not args.no_rerank)
        except ValidationError as exc:
            p_rec.error(validation_message(exc))
        if args.json:
            print(json.dumps(hits, indent=2))
            return 0
        if not hits:
            print("No matching memories. Try a distinctive term or broaden the filters.")
            return 0
        print(f"[mode: {hits[0].get('mode', 'fts')}, top_conf: {hits[0].get('confidence', 'medium')}]")
        for h in hits:
            proj = f" [{h['project']}]" if h["project"] else ""
            sec = f" > {h['heading']}" if h.get("heading") and h["heading"] != h["title"] else ""
            print(f"- {h['title']}{sec} ({h['bucket']}/{h['kind']}{proj}, {h['updated_at']}, score={h['score']}, {h['confidence']})  id:{h['id']}")
            if h["headline"] and h["headline"] != h["title"]:
                print(f"  Headline · {h['headline']}")
            if h.get("conflicts_with"):
                peers = ", ".join(f"{c['id']} ({c['updated_at']})" for c in h["conflicts_with"][:2])
                print(f"  Conflict · differs from {peers}")
            print(f"  {h['snippet']}")
        return 0

    if args.cmd == "read":
        try:
            path, content = read_memory(root, args.id_or_path)
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            p_read.error(str(exc))
        print(f"# Path: {path}\n")
        print(content)
        return 0

    if args.cmd in ("store", "remember"):
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        fields = dict(content=args.content, title=args.title, kind=args.kind, project=args.project,
                      tags=tags, subject=args.subject, predicate=args.predicate,
                      source=args.source, epistemic=args.epistemic, author=args.author)
        headline = args.headline
        while True:
            try:
                item = save_memory(root, **fields, headline=headline)
                break
            except ValidationError as exc:
                if not needs_headline(exc):
                    p_rem.error(validation_message(exc))
                if not sys.stdin.isatty():
                    p_rem.error(f"{validation_message(exc)} Supply --headline and retry.")
                try:
                    headline = input("One-line headline for this fact: ").strip()
                except (EOFError, KeyboardInterrupt):
                    p_rem.error("Supply --headline to save this fact.")
                if not headline:
                    p_rem.error(f"{validation_message(exc)} Supply --headline and retry.")
        index_single_item(root, item, background_embed=True)
        print(f"Stored [{item.kind}] {item.id} -> {item.path}")
        return 0

    if args.cmd == "flush-prompt":
        msg = (
            "Before context compacts, store 1-3 durable facts, architectural decisions, or root-cause lessons "
            "from this session via `brain_store`. Pass `subject` and `predicate` for a mutable fact, and a one-line "
            "`headline` for a fact over 400 characters. Keep only verified takeaways and worthwhile milestones."
        )
        if args.hook == "claude":
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreCompact",
                            "additionalContext": msg,
                        }
                    }
                )
            )
        else:
            print(msg)
        return 0

    if args.cmd == "project":
        if not args.name:
            if args.update.strip() or args.repo_root.strip():
                p_proj.error("Provide the project name along with its updated Markdown.")
            for p in list_projects(root):
                print(p)
            return 0
        try:
            item = update_project(root, name=args.name, update=args.update, repo_root=args.repo_root)
        except FileNotFoundError:
            p_proj.error("Project not found. Run `brain project` to list project names.")
        if args.update.strip() or args.repo_root.strip():
            index_single_item(root, item)
            print(f"Updated project: {item.path}")
        else:
            print(item.body)
        return 0

    if args.cmd == "forget":
        try:
            archived = forget_memory(root, args.id_or_path)
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            p_fgt.error(str(exc))
        sync_index(root)
        print(f"Archived: {archived}")
        return 0

    if args.cmd == "reindex":
        res = reindex_all(root)
        print(json.dumps(res))
        return 0

    if args.cmd == "embed-missing":
        res = embed_missing(root)
        print(json.dumps(res))
        return 0

    if args.cmd == "migrate":
        res = migrate_v2(root, dry_run=args.dry_run)
        print(json.dumps(res, indent=2))
        return 0

    if args.cmd == "backfill-headlines":
        print(json.dumps(backfill_headlines(root, dry_run=args.dry_run), indent=2))
        return 0

    if args.cmd == "install-harnesses":
        for line in install_harnesses():
            print(line)
        return 0

    if args.cmd == "doctor":
        checks = doctor(root)
        for k, v in checks.items():
            print(f"{k:22s} {v}")
        return 0

    if args.cmd == "stats":
        from collections import Counter

        log_path = root / ".gm" / "usage.jsonl"
        if not log_path.exists():
            print("No MCP usage logged yet. Use brain_* tools from a connected harness to populate stats.")
            return 0
        counts: Counter[str] = Counter()
        total = 0
        last_ts = ""
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                counts[rec.get("tool", "unknown")] += 1
                total += 1
                last_ts = rec.get("ts", last_ts)
            except Exception:
                continue
        print(f"Total MCP calls: {total} (last: {last_ts or 'n/a'})")
        for tool, n in counts.most_common():
            print(f"  {tool:16s} {n}")
        return 0

    return 1


def compat_main(argv: list[str] | None = None) -> int:
    """Backward-compatible shim for legacy `memoryctl` invocations."""
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        return main(["context"])
    cmd, rest = raw[0], raw[1:]
    if cmd == "start-context":
        return main(["context", *rest])
    if cmd == "index-query":
        q = [a for a in rest if not a.startswith("--")]
        return main(["recall", *(q or ["recent"])])
    if cmd == "index-build":
        return main(["reindex"])
    if cmd == "log":
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--title", default="")
        p.add_argument("--note", default="")
        ns, extra = p.parse_known_args(rest)
        body = ns.note or " ".join(extra)
        return main(["remember", body or ns.title, "--title", ns.title, "--kind", "journal"])
    if cmd == "fact-set":
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--key", required=True)
        p.add_argument("--value", required=True)
        p.add_argument("--headline", default="")
        ns, _ = p.parse_known_args(rest)
        return main(["remember", f"{ns.key}: {ns.value}", "--title", ns.key, "--kind", "fact", "--headline", ns.headline])
    return main(raw)


if __name__ == "__main__":
    raise SystemExit(main())
