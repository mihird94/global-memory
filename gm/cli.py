"""CLI entrypoint for GM v3 (plus lightweight memoryctl compatibility shim)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .board import (
    AGENT_STATES,
    MESSAGE_KINDS,
    PRIORITIES,
    STATES,
    THREAD_KINDS,
    Board,
)
from .export import (
    ALLOWED_EXPORT_KINDS,
    approve_bundle,
    list_inbox_proposals, promote_inbox_proposal, discard_inbox_proposal,
    bundle_status,
    init_bundle,
    resolve_bundle_dir,
    revoke_bundle,
    stage_bundle,
    wire_external_harness,
)
from .facts import backfill_headlines
from .harnesses import doctor, install_harnesses
from .index import build_context, embed_missing, index_single_item, recall, reindex_all, sync_index
from .migrate import migrate_v2
from .store import forget_memory, gm_home, list_projects, read_memory, save_memory, update_project
from .validation import FACT_HEADLINE_THRESHOLD, needs_headline, validation_message


def _parse_json_payload(raw: str) -> dict | None:
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON payload: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise ValueError("Payload JSON must be an object.")
    return parsed


def _board_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="board_cmd", required=True)

    open_p = sub.add_parser("open", help="Open a discussion, request, broadcast, or assignment thread")
    open_p.add_argument("title")
    open_p.add_argument("--by", required=True, help="Initiating harness or session")
    open_p.add_argument("--kind", choices=THREAD_KINDS, default="discussion")
    open_p.add_argument("--to", action="append", default=[], help="Recipient(s) or '*' for broadcast (repeatable or comma-separated)")
    open_p.add_argument("--body", default="", help="Opening message or brief")
    open_p.add_argument("--project", default="")
    open_p.add_argument("--channel", default="")
    open_p.add_argument("--priority", choices=PRIORITIES, default="normal")
    open_p.add_argument("--ref", action="append", dest="refs", default=[], help="Attach memory ID or path reference")
    open_p.add_argument("--payload-json", default="", help="Optional JSON object payload")
    open_p.add_argument("--idempotency-key", default="")

    assign = sub.add_parser("assign", help="Open an assignment with a supervisor, an assignee, and a brief")
    assign.add_argument("title")
    assign.add_argument("--brief", required=True)
    assign.add_argument("--by", required=True, help="Supervisor harness or session")
    assign.add_argument("--to", required=True, help="Implementer harness or session")
    assign.add_argument("--project", default="")
    assign.add_argument("--priority", choices=PRIORITIES, default="normal")

    listing = sub.add_parser("list", help="List threads, optionally scoped to a harness or session")
    listing.add_argument("--for", dest="actor", default="", help="Show threads involving this identity")
    listing.add_argument("--status", choices=STATES, default="")
    listing.add_argument("--kind", choices=THREAD_KINDS, default="")
    listing.add_argument("--channel", default="")
    listing.add_argument("--project", default="")
    listing.add_argument("--since-rev", type=int, default=0)
    listing.add_argument("--include-broadcasts", action="store_true")

    inbox = sub.add_parser("inbox", help="Show unread or attention-needed threads for an agent")
    inbox.add_argument("--for", dest="actor", required=True, help="Agent or session identity")
    inbox.add_argument("--all", dest="show_all", action="store_true", help="Include already-read threads")
    inbox.add_argument("--project", default="")
    inbox.add_argument("--kind", choices=THREAD_KINDS, default="")
    inbox.add_argument("--since-rev", type=int, default=0)

    read = sub.add_parser("read", help="Read messages, participants, and available status changes")
    read.add_argument("id", type=int)
    read.add_argument("--as", dest="actor", default="", help="Reader identity (used with --mark-read)")
    read.add_argument("--mark-read", action="store_true", help="Advance read cursor for --as")
    read.add_argument("--since-post", type=int, default=0, help="Only return messages after this ID")

    post = sub.add_parser("post", help="Post a message or change thread state")
    post.add_argument("id", type=int)
    post.add_argument("message", nargs="?", default="")
    post.add_argument("--by", required=True, help="Posting harness or session")
    post.add_argument("--status", choices=STATES, default="")
    post.add_argument("--kind", choices=MESSAGE_KINDS, default="")
    post.add_argument("--reply-to", type=int, default=None)
    post.add_argument("--to", action="append", default=[], help="Target actor(s) in this message")
    post.add_argument("--ref", action="append", dest="refs", default=[], help="Attach memory ID or path reference")
    post.add_argument("--payload-json", default="", help="Optional JSON object payload")
    post.add_argument("--expected-rev", type=int, default=None)
    post.add_argument("--idempotency-key", default="")

    ack = sub.add_parser("ack", help="Mark a thread read and acknowledged")
    ack.add_argument("id", type=int)
    ack.add_argument("--by", required=True, help="Acknowledging harness or session")
    ack.add_argument("--up-to", type=int, default=None, help="Acknowledge up to specific message ID")
    ack.add_argument("--message", default="", help="Optional acknowledgement message")
    ack.add_argument("--post", action="store_true", help="Also append an ack message to the thread")

    wait_p = sub.add_parser("wait", help="Wait for new messages or thread updates")
    wait_p.add_argument("--for", dest="actor", default="", help="Watch threads involving this identity")
    wait_p.add_argument("--thread", type=int, default=None, help="Watch a specific thread ID")
    wait_p.add_argument("--since-rev", type=int, default=0)
    wait_p.add_argument("--timeout", type=float, default=30.0)

    reg = sub.add_parser("register", help="Register or update local agent presence")
    reg.add_argument("--as", dest="actor", required=True, help="Agent or session identity")
    reg.add_argument("--harness", default="")
    reg.add_argument("--project", default="")
    reg.add_argument("--status", choices=AGENT_STATES, default="active")
    reg.add_argument("--summary", default="")
    reg.add_argument("--capabilities", default="", help="Comma-separated capabilities")

    who = sub.add_parser("who", help="List recently active local agents")
    who.add_argument("--project", default="")
    who.add_argument("--minutes", type=int, default=60)
    who.add_argument("--all", dest="include_offline", action="store_true")

    for command in (open_p, assign, listing, inbox, read, post, ack, wait_p, reg, who):
        command.add_argument("--json", action="store_true", help="Print machine-readable results")


def _board_command(root: Path, args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    board = Board(root)
    try:
        if args.board_cmd == "open":
            payload = _parse_json_payload(args.payload_json)
            result = board.open_thread(
                kind=args.kind,
                title=args.title,
                body=args.body,
                author=args.by,
                to=args.to,
                project=args.project,
                channel=args.channel,
                priority=args.priority,
                refs=args.refs,
                payload=payload,
                idempotency_key=args.idempotency_key,
            )
        elif args.board_cmd == "assign":
            result = board.assign(
                title=args.title,
                brief=args.brief,
                supervisor=args.by,
                assignee=args.to,
                project=args.project,
                priority=args.priority,
            )
        elif args.board_cmd == "list":
            result = board.list(
                actor=args.actor,
                status=args.status,
                project=args.project,
                kind=args.kind,
                channel=args.channel,
                since_rev=args.since_rev,
                include_broadcasts=args.include_broadcasts,
            )
        elif args.board_cmd == "inbox":
            result = board.inbox(
                args.actor,
                project=args.project,
                kind=args.kind,
                unread_only=not args.show_all,
                since_rev=args.since_rev,
            )
        elif args.board_cmd == "read":
            result = board.read(
                args.id,
                actor=args.actor,
                since_post_id=args.since_post,
                mark_read=args.mark_read,
            )
        elif args.board_cmd == "post":
            payload = _parse_json_payload(args.payload_json)
            result = board.post(
                args.id,
                author=args.by,
                message=args.message,
                status=args.status,
                kind=args.kind,
                reply_to=args.reply_to,
                to=args.to,
                refs=args.refs,
                payload=payload,
                expected_revision=args.expected_rev,
                idempotency_key=args.idempotency_key,
            )
        elif args.board_cmd == "ack":
            result = board.ack(
                args.id,
                actor=args.by,
                up_to_post_id=args.up_to,
                message=args.message,
                post_ack=args.post,
            )
        elif args.board_cmd == "wait":
            result = board.wait(
                actor=args.actor,
                thread_id=args.thread,
                since_rev=args.since_rev,
                timeout=args.timeout,
            )
        elif args.board_cmd == "register":
            caps = [c.strip() for c in args.capabilities.split(",") if c.strip()]
            result = board.heartbeat(
                actor=args.actor,
                harness=args.harness,
                project=args.project,
                status=args.status,
                summary=args.summary,
                capabilities=caps,
            )
        else:
            result = board.agents(
                project=args.project,
                active_within_minutes=args.minutes,
                include_offline=args.include_offline,
            )
    except ValidationError as exc:
        parser.error(validation_message(exc))
    except ValueError as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.board_cmd == "list":
        if not result["threads"]:
            print("No threads match.")
        for row in result["threads"]:
            who = f"{row['supervisor']} → {row['assignee']}" if row["kind"] == "assignment" else ", ".join(row["participants"])
            chan = f" #{row['channel']}" if row.get("channel") else ""
            print(f"#{row['id']}  [{row['kind']}/{STATES[row['status']]}]  {row['title']}{chan}  ({who})")
    elif args.board_cmd == "inbox":
        if not result["threads"]:
            print(f"Inbox clear for {result['actor']}.")
        for row in result["threads"]:
            attn = " !" if row["needs_attention"] else ""
            unread = f" ({row['unread_count']} unread)" if row["unread_count"] else ""
            print(f"#{row['id']}  [{row['kind']}/{STATES[row['status']]}]{attn}{unread}  {row['title']}")
    elif args.board_cmd == "read":
        print(f"#{result['id']}  [{result['kind']}]  {result['title']}  ·  {STATES[result['status']]}")
        for post in result["posts"]:
            label = STATES[post["status"]] if post["status"] else MESSAGE_KINDS.get(post["kind"], "Message")
            reply = f"  ↪ #{post['reply_to']}" if post.get("reply_to") else ""
            targets = f"  → {', '.join(post['to'])}" if post.get("to") else ""
            print(f"\n[{post['id']}] {post['created_at']}  {post['author']}  ·  {label}{reply}{targets}")
            if post["message"]:
                print(post["message"])
            if post.get("refs"):
                print(f"Refs: {', '.join(post['refs'])}")
        for action in result["actions"]:
            print(f"\n{action['label']}  --status {action['status']} --by {action['actor']}")
    elif args.board_cmd == "ack":
        print(f"#{result['id']}  acked up to #{result['acked_id']}")
    elif args.board_cmd == "wait":
        if result["timed_out"]:
            print(f"Timed out at revision {result['revision']}.")
        else:
            print(f"Updated to revision {result['revision']} ({len(result['threads'])} thread(s)).")
    elif args.board_cmd == "register":
        print(f"Registered {result['actor']} ({result['status']})")
    elif args.board_cmd == "who":
        if not result["agents"]:
            print("No active agents.")
        for ag in result["agents"]:
            proj = f" [{ag['project']}]" if ag["project"] else ""
            print(f"{ag['actor']}  ({ag['status']}{proj})  seen {ag['last_seen_at']}")
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

    p_checkpoint = sub.add_parser("checkpoint-observe", help="Record an opt-in checkpoint observation")
    for field in ("surface", "harness", "session", "turn", "trigger"):
        p_checkpoint.add_argument("--" + field, required=True)
    p_checkpoint.add_argument("--project", default="")

    p_checkpoint_save = sub.add_parser("checkpoint-save", help="Save a verified checkpoint draft from JSON on stdin")
    p_checkpoint_save.add_argument("checkpoint_id")

    p_checkpoint_pending = sub.add_parser("checkpoint-pending", help="List pending checkpoints for a session")
    p_checkpoint_pending.add_argument("--harness", required=True)
    p_checkpoint_pending.add_argument("--session", required=True)
    p_checkpoint_revision = sub.add_parser("checkpoint-revision", help="Read a note with its revision for a guarded update")
    p_checkpoint_revision.add_argument("memory_id")
    p_checkpoint_skip = sub.add_parser("checkpoint-skip", help="Close a checkpoint with a reason")
    p_checkpoint_skip.add_argument("checkpoint_id")
    p_checkpoint_skip.add_argument("reason", choices=["no_durable_information", "unverified", "user_declined"])
    p_checkpoint_config = sub.add_parser("checkpoint-hook-config", help="Print opt-in client hook configuration")
    p_checkpoint_config.add_argument("--surface", required=True, choices=["codex-cli", "codex-desktop", "antigravity-cli", "antigravity-desktop", "antigravity-ide", "claude-cli", "gemini-cli"])
    p_checkpoint_config.add_argument("--reminder", action="store_true", help="Allow one continuation in Antigravity CLI")

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

    p_exp = sub.add_parser("export", help="Stage, approve, verify, and revoke sanitized external agent bundles")
    exp_sub = p_exp.add_subparsers(dest="export_cmd", required=True)

    exp_init = exp_sub.add_parser("init", help="Initialize an opted-in external export bundle")
    exp_init.add_argument("bundle")
    exp_init.add_argument("--projects", required=True, help="Comma-separated opted-in project slugs")
    exp_init.add_argument("--allow-kinds", default=",".join(ALLOWED_EXPORT_KINDS), help="Allowed kinds subset of project,decision,lesson,fact")
    exp_init.add_argument("--threshold", type=float, default=0.50, help="MiniLM post-scrub block threshold")
    exp_init.add_argument("--denylist", default="", help="Extra comma-separated denylist terms")
    exp_init.add_argument("--allow-sensitive-project", action="store_true")

    exp_init.add_argument("--no-proposals", action="store_true")

    exp_inbox = exp_sub.add_parser("inbox", help="Review quarantined proposals")
    exp_inbox.add_argument("bundle")
    exp_inbox.add_argument("--json", action="store_true")
    exp_promote = exp_sub.add_parser("promote", help="Promote a reviewed proposal")
    exp_promote.add_argument("bundle")
    exp_promote.add_argument("proposal_id")
    exp_promote.add_argument("--use-scrubbed", action="store_true")
    exp_promote.add_argument("--also-export", action="store_true")
    exp_promote.add_argument("--force-blocked", action="store_true")
    exp_promote.add_argument("--project")
    exp_promote.add_argument("--headline")
    exp_discard = exp_sub.add_parser("discard", help="Discard a proposal")
    exp_discard.add_argument("bundle")
    exp_discard.add_argument("proposal_id")

    exp_stage = exp_sub.add_parser("stage", help="Screen opted-in notes into staged.json for human review")
    exp_stage.add_argument("bundle")
    exp_stage.add_argument("--json", action="store_true")

    exp_app = exp_sub.add_parser("approve", help="Approve reviewed staged notes into manifest.json")
    exp_app.add_argument("bundle")
    exp_app.add_argument("doc_ids", nargs="*")
    exp_app.add_argument("--all-clean", action="store_true", help="Approve all ALLOW candidates")
    exp_app.add_argument("--allow-redacted", action="store_true", help="Allow REDACT_AND_REVIEW candidates")
    exp_app.add_argument("--force-blocked", action="store_true", help="Override semantic block after manual inspection")

    exp_st = exp_sub.add_parser("status", help="Inspect bundle manifest, source drift, and export integrity")
    exp_st.add_argument("bundle")
    exp_st.add_argument("--json", action="store_true")

    exp_rev = exp_sub.add_parser("revoke", help="Revoke exported note(s) and rebuild bundle SQLite immediately")
    exp_rev.add_argument("bundle")
    exp_rev.add_argument("doc_ids", nargs="*")
    exp_rev.add_argument("--all", dest="revoke_all", action="store_true")

    exp_wire = exp_sub.add_parser("wire-harness", help="Wire Pi or OpenCode to scoped brain-safe-mcp with optional quarantined proposals")
    exp_wire.add_argument("bundle")
    exp_wire.add_argument("--harness", required=True, choices=["pi", "opencode"])
    exp_wire.add_argument("--disconnect", action="store_true")

    sub.add_parser("install-harnesses", help="Wire GM across Antigravity, Claude Code, Codex, Gemini CLI")
    sub.add_parser("doctor", help="Check multi-harness health and index status")
    sub.add_parser("stats", help="Show MCP tool usage & adherence telemetry")
    sub.add_parser("app", aliases=["ui"], help="Open the Brain desktop workspace")

    args = parser.parse_args(argv)
    root = gm_home(args.home)

    if args.cmd == "checkpoint-observe":
        from .checkpoint import observe
        try:
            print(json.dumps(observe(root, surface=args.surface, harness=args.harness,
                                     session=args.session, turn=args.turn,
                                     trigger=args.trigger, project=args.project)))
        except ValueError as exc:
            p_checkpoint.error(str(exc))
        return 0

    if args.cmd == "checkpoint-save":
        from .checkpoint import save
        try:
            draft = json.load(sys.stdin)
            if not isinstance(draft, dict):
                raise ValueError("expected a JSON object")
            print(json.dumps(save(root, args.checkpoint_id, **draft)))
        except (ValueError, TypeError, FileExistsError) as exc:
            p_checkpoint_save.error(str(exc))
        return 0

    if args.cmd == "checkpoint-pending":
        from .checkpoint import pending
        try:
            print(json.dumps(pending(root, harness=args.harness, session=args.session)))
        except ValueError as exc:
            p_checkpoint_pending.error(str(exc))
        return 0

    if args.cmd == "checkpoint-skip":
        from .checkpoint import skip
        try:
            print(json.dumps(skip(root, args.checkpoint_id, args.reason)))
        except ValueError as exc:
            p_checkpoint_skip.error(str(exc))
        return 0

    if args.cmd == "checkpoint-revision":
        from .checkpoint import revision
        try:
            print(json.dumps(revision(root, args.memory_id)))
        except (ValueError, OSError) as exc:
            p_checkpoint_revision.error(str(exc))
        return 0

    if args.cmd == "checkpoint-hook-config":
        from .checkpoint_hooks import antigravity_config, codex_config, standard_config
        if not args.home:
            p_checkpoint_config.error("specify --home for the isolated pilot store")
        if args.reminder and args.surface != "antigravity-cli":
            p_checkpoint_config.error("the reminder has only been validated on Antigravity CLI")
        options = dict(surface=args.surface, root=root)
        if args.surface.startswith("codex-"):
            config = codex_config(**options)
        elif args.surface.startswith("antigravity-"):
            config = antigravity_config(**options, reminder=args.reminder)
        else:
            config = standard_config(**options)
        print(json.dumps(config, indent=2))
        return 0

    if args.cmd == "board":
        return _board_command(root, args, p_board)

    if args.cmd == "export":
        try:
            bdir = resolve_bundle_dir(args.bundle)
            if args.export_cmd == "init":
                res = init_bundle(
                    bdir,
                    projects=[x.strip() for x in args.projects.split(",") if x.strip()],
                    allow_kinds=tuple(x.strip() for x in args.allow_kinds.split(",") if x.strip()),
                    threshold=args.threshold,
                    extra_denylist=tuple(x.strip() for x in args.denylist.split(",") if x.strip()),
                    allow_sensitive_project=args.allow_sensitive_project,
                    allow_proposals=not args.no_proposals,
                )
                print(json.dumps(res, indent=2))
            elif args.export_cmd == "inbox":
                rows = list_inbox_proposals(root, bdir)
                if args.json:
                    print(json.dumps(rows, indent=2))
                else:
                    for row in rows:
                        print(f"{row['id']}  {row['created_at']}  {row['harness']}  {row['kind']}  {row['project']}  {row['full_screen']['action']}  {row['title']}")
            elif args.export_cmd == "promote":
                print(json.dumps(promote_inbox_proposal(root, bdir, args.proposal_id, use_scrubbed=args.use_scrubbed, also_export=args.also_export, force_blocked=args.force_blocked, project=args.project, headline=args.headline), indent=2))
            elif args.export_cmd == "discard":
                print(json.dumps(discard_inbox_proposal(bdir, args.proposal_id), indent=2))
            elif args.export_cmd == "stage":
                res = stage_bundle(root, bdir)
                if args.json:
                    print(json.dumps(res, indent=2))
                else:
                    print(f"Staged {res['candidates']} candidate(s) (skipped {res['skipped_structural']} structural) -> {bdir}")
                    print(f"Counts: {res['counts']} (rules_hash={res['rules_hash']})")
                    for it in res["items"]:
                        ents = ",".join(it["entity_types"]) or "-"
                        print(f"  [{it['action']:17s}] {it['id']}  ({it['kind']}/{it['project']})  p={it['p_post_scrub']:.2f}  ents={ents}")
            elif args.export_cmd == "approve":
                res = approve_bundle(
                    root,
                    bdir,
                    doc_ids=args.doc_ids,
                    all_clean=args.all_clean,
                    allow_redacted=args.allow_redacted,
                    force_blocked=args.force_blocked,
                )
                print(json.dumps(res, indent=2))
            elif args.export_cmd == "status":
                res = bundle_status(root, bdir)
                print(json.dumps(res, indent=2))
            elif args.export_cmd == "revoke":
                res = revoke_bundle(bdir, doc_ids=args.doc_ids, revoke_all=args.revoke_all)
                print(json.dumps(res, indent=2))
            elif args.export_cmd == "wire-harness":
                print(wire_external_harness(bdir, harness=args.harness, disconnect=args.disconnect))
        except (ValueError, KeyError, FileNotFoundError, RuntimeError, PermissionError) as exc:
            p_exp.error(str(exc))
        return 0

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
