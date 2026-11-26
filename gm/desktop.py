"""Local stdio bridge from the Brain desktop window to the Markdown store."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import traceback
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import __version__
from .board import Board
from .export import (
    ALLOWED_EXPORT_KINDS,
    add_bundle_candidates,
    promote_inbox_proposal, discard_inbox_proposal, _pending_inbox_count,
    approve_bundle,
    discover_bundle_candidates,
    exports_root,
    external_harness_status,
    init_bundle,
    list_bundles,
    read_bundle_detail,
    resolve_bundle_dir,
    revoke_bundle,
    save_safe_profile,
    stage_bundle,
    store_scope_inventory,
    update_bundle_config,
    wire_external_harness,
)
from .index import _connect, _doc_filters, build_context, index_single_item, index_stats, recall, sync_index
from .screening import PrivacyScreener
from .store import (
    atomic_fact_value,
    atomic_write_text,
    bucket_for_kind,
    forget_memory,
    gm_home,
    infer_fact_headline,
    list_projects,
    load_config,
    load_item,
    markdown_revision,
    memory_write_lock,
    parse_frontmatter,
    save_memory,
    with_fact_headline,
    with_markdown_body,
)
from .validation import FACT_HEADLINE_THRESHOLD, MemoryDraft, SearchFilters, normalize_project_slug, validation_message

PAGE_SIZE = 30
SEARCH_LIMIT = 30
LIVE_REFRESH_SECONDS = 5
TOOLS = ("context", "search", "read", "store", "project", "forget", "board")


def field(params: dict[str, Any], name: str, limit: int = 500) -> str:
    value = params.get(name, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name.capitalize()} must be text of at most {limit:,} characters.")
    return value.strip()


def filters(params: dict[str, Any]) -> dict[str, str]:
    return SearchFilters(**{name: field(params, name) for name in SearchFilters.model_fields}).model_dump()


def catalog_revision(conn: sqlite3.Connection) -> str:
    rows = conn.execute("SELECT id, mtime, headline FROM docs ORDER BY id")
    return markdown_revision(json.dumps([tuple(row) for row in rows]))


def catalog_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = {
        row["bucket"]: row["total"]
        for row in conn.execute("SELECT bucket, count(*) AS total FROM docs GROUP BY bucket")
    }
    counts["all"] = sum(counts.values())
    projects = [dict(row) for row in conn.execute(
        """SELECT project AS name, count(*) AS total FROM docs
           WHERE project <> '' GROUP BY lower(project) ORDER BY lower(project)"""
    )]
    return {"counts": counts, "projects": projects, "catalog_revision": catalog_revision(conn),
            "fact_headline_threshold": FACT_HEADLINE_THRESHOLD}


class Desktop:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.board = Board(root)
        self._screeners: dict[tuple[float, tuple[str, ...]], PrivacyScreener] = {}

    def _screener_for(self, bundle_dir: Path) -> PrivacyScreener:
        cfg = json.loads((bundle_dir / "bundle_config.json").read_text(encoding="utf-8"))
        threshold = float(cfg.get("threshold", 0.50))
        extra = tuple(str(x).strip() for x in cfg.get("extra_denylist", ()) if str(x).strip())
        key = (threshold, extra)
        sc = self._screeners.get(key)
        if sc is None:
            det_only = os.environ.get("BRAIN_SCREEN_DETERMINISTIC", "") == "1"
            sc = PrivacyScreener(threshold=threshold, extra_denylist=extra, strict=not det_only, deterministic_only=det_only)
            self._screeners[key] = sc
        return sc

    def browse(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = filters(params)
        offset = params.get("offset", 0)
        limit = params.get("limit", PAGE_SIZE)
        if type(offset) is not int or offset < 0 or offset > 1_000_000:
            raise ValueError("Invalid library offset.")
        if type(limit) is not int or not 1 <= limit <= 1_000_000:
            raise ValueError("Invalid library page size.")
        if params.get("refresh") is True:
            sync_index(self.root)
        where, values = _doc_filters(**scope)
        predicate = " AND ".join(where) or "1"
        with closing(_connect(self.root)) as conn:
            conn.execute("BEGIN")
            total = conn.execute(f"SELECT count(*) FROM docs d WHERE {predicate}", values).fetchone()[0]
            rows = conn.execute(
                f"""SELECT id, title, headline, kind, bucket, project, updated_at, rel_path, substr(body, 1, 650) AS excerpt
                    FROM docs d WHERE {predicate}
                    ORDER BY updated_at DESC, mtime DESC, id LIMIT ? OFFSET ?""",
                [*values, limit, offset],
            ).fetchall()
            summary = catalog_summary(conn)
        return {"items": [dict(row) for row in rows], "total": total, **summary}

    def changes(self, _params: dict[str, Any]) -> dict[str, str]:
        sync_index(self.root, max_age_seconds=LIVE_REFRESH_SECONDS)
        with closing(_connect(self.root)) as conn:
            return {"catalog_revision": catalog_revision(conn)}

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = filters(params)
        query = field(params, "query", 1000)
        if not query:
            raise ValueError("Enter a search query.")
        if params.get("refresh") is True:
            sync_index(self.root)
        # Capture the revision before searching so a concurrent write still triggers a refresh.
        with closing(_connect(self.root)) as conn:
            conn.execute("BEGIN")
            summary = catalog_summary(conn)
        hits = recall(self.root, query, limit=SEARCH_LIMIT, project_filter=scope.pop("project"), **scope)
        mode = hits[0]["mode"] if hits else ""
        score = hits[0]["score"] if hits else None
        if "rerank" in mode:
            hits = [hit for hit in hits if hit["score"] >= 0.08]
        return {"items": hits, "mode": mode, "verify": "rerank" in mode and score < 0.25, **summary}

    def locate(self, memory_id: str) -> tuple[Path, Path, str, bool]:
        with closing(_connect(self.root)) as conn:
            row = conn.execute("SELECT rel_path FROM docs WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise FileNotFoundError()
        rel_path = row["rel_path"]
        prefix, separator, relative = rel_path.partition(":")
        candidates = [(self.root, rel_path, "")]
        if separator:
            for entry in load_config(self.root).get("extra_roots", []):
                base = Path(entry).expanduser().resolve()
                if base.name == prefix:
                    candidates.insert(0, (base, relative, prefix))
        for base, relative, source in candidates:
            path = base / relative
            resolved = path.resolve()
            if resolved.is_relative_to(base) and resolved.suffix == ".md" and resolved.is_file():
                return path, base, source, bool(source) or resolved != path
        raise FileNotFoundError()

    def read(self, params: dict[str, Any]) -> dict[str, Any]:
        memory_id = field(params, "id", 4096)
        known_revision = field(params, "if_revision")
        try:
            path, base, source, readonly = self.locate(memory_id)
            raw = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            if known_revision:
                return {"missing": True}
            raise
        revision = markdown_revision(raw)
        if revision == known_revision:
            return {"unchanged": True}
        item = load_item(path, base, readonly=readonly, prefix=source, raw=raw)
        meta, body = parse_frontmatter(raw)
        subject = str(meta.get("subject", ""))
        predicate = str(meta.get("predicate", ""))
        return {
            "id": memory_id, "title": item.title, "headline": item.headline, "kind": item.kind, "project": item.project,
            "tags": item.tags, "updated_at": item.updated_at, "rel_path": item.rel_path,
            "readonly": readonly, "source": source, "markdown": body.strip(), "raw": raw,
            "revision": revision, "subject": subject, "predicate": predicate,
            "epistemic": str(meta.get("epistemic", "")),
            "author": str(meta.get("author", "")),
            "provenance": str(meta.get("source", "")),
            "value": atomic_fact_value(body) if subject and predicate else "",
        }

    def create(self, params: dict[str, Any]) -> dict[str, str]:
        kind = field(params, "kind")
        subject = field(params, "subject")
        predicate = field(params, "predicate")
        title = field(params, "title")
        if kind == "atomic":
            if not subject or not predicate:
                raise ValueError("Enter both a subject and a predicate.")
            kind = "fact"
        elif kind != "journal" and not title:
            raise ValueError("Enter a title.")
        else:
            subject = predicate = ""
        item = save_memory(
            self.root, field(params, "content", 250_000), title=title, kind=kind,
            project=field(params, "project") if kind != "project" else "",
            tags=field(params, "tags", 3000).split(","), subject=subject, predicate=predicate,
            headline=field(params, "headline", 500),
            source="desktop", author="desktop",
            replace=False,
        )
        index_single_item(self.root, item)
        return {"id": item.id}

    def edit(self, params: dict[str, Any]) -> dict[str, str]:
        memory_id = field(params, "id", 4096)
        revision = field(params, "revision")
        content = field(params, "content", 250_000)
        if not content:
            raise ValueError("Enter some content.")
        path, _, _, readonly = self.locate(memory_id)
        if readonly:
            raise PermissionError("This source is read-only.")
        raw = path.read_text(encoding="utf-8", errors="replace")
        item = load_item(path, self.root, raw=raw)
        if item.kind in ("journal", "episode"):
            raise ValueError("Add a new journal entry from the capture form.")
        meta, _ = parse_frontmatter(raw)
        subject, predicate = str(meta.get("subject", "")), str(meta.get("predicate", ""))
        headline = field(params, "headline", 500)
        if item.kind == "fact" and subject and predicate:
            item = save_memory(
                self.root, content, title=item.title, kind=item.kind, project=item.project, tags=item.tags,
                subject=subject, predicate=predicate, expected_revision=revision,
                headline=headline,
                source=str(meta.get("source", "")), epistemic=str(meta.get("epistemic", "")),
                author=str(meta.get("author", "")),
            )
        else:
            if item.kind != "profile":
                draft = MemoryDraft(content=content, kind=item.kind, title=item.title, project=item.project,
                                    headline=headline, subject=subject, predicate=predicate)
                headline = draft.headline
            durable = bucket_for_kind(item.kind) == "fact"
            if durable and not headline:
                headline = infer_fact_headline(content, item.title)
            with memory_write_lock(self.root):
                raw = path.read_text(encoding="utf-8", errors="replace")
                if markdown_revision(raw) != revision:
                    raise FileExistsError("This memory changed on disk. Reopen it before editing.")
                updated = with_markdown_body(raw, content)
                if durable:
                    updated = with_fact_headline(updated, headline)
                atomic_write_text(path, updated)
                item = load_item(path, self.root)
        index_single_item(self.root, item)
        return {"id": item.id}

    def archive(self, params: dict[str, Any]) -> dict[str, str]:
        path, _, _, readonly = self.locate(field(params, "id", 4096))
        if readonly:
            raise PermissionError("This source is read-only.")
        archived = forget_memory(self.root, str(path), expected_revision=field(params, "revision"))
        sync_index(self.root)
        return {"archived": archived}

    def context(self, params: dict[str, Any]) -> dict[str, str]:
        name = normalize_project_slug(field(params, "project")) if field(params, "project") else ""
        projects = {project.lower(): project for project in list_projects(self.root)}
        return {"markdown": build_context(self.root, project=projects.get(name.lower(), ""), cwd=str(self.root))}

    def status(self, _params: dict[str, Any]) -> dict[str, Any]:
        calls: Counter[str] = Counter()
        last = ""
        try:
            with (self.root / ".gm" / "usage.jsonl").open(encoding="utf-8", errors="replace") as log:
                for line in log:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    tool = str(entry.get("tool", "")).removeprefix("gm_").removeprefix("brain_")
                    tool = {"recall": "search", "remember": "store"}.get(tool, tool)
                    if tool in TOOLS:
                        calls[tool] += 1
                        last = str(entry.get("ts", "")) or last
        except FileNotFoundError:
            pass
        return {
            "version": __version__, "root": str(self.root), "index": index_stats(self.root), "last_call": last,
            "usage": {f"brain_{tool}": calls[tool] for tool in TOOLS},
        }

    def request(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        actions = {
            "browse": self.browse, "changes": self.changes, "search": self.search, "read": self.read, "create": self.create,
            "edit": self.edit, "archive": self.archive, "context": self.context, "status": self.status,
            "board_list": self.board_list, "board_read": self.board_read,
            "board_open": self.board_open, "board_assign": self.board_assign,
            "board_post": self.board_post, "board_inbox": self.board_inbox,
            "board_ack": self.board_ack, "board_agents": self.board_agents,
            "export_list": self.export_list, "export_read": self.export_read, "export_init": self.export_init,
            "export_stage": self.export_stage, "export_approve": self.export_approve, "export_revoke": self.export_revoke,
            "export_wire": self.export_wire, "export_save_profile": self.export_save_profile,
            "export_inventory": self.export_inventory, "export_update_config": self.export_update_config,
            "export_inbox_promote": self.export_inbox_promote, "export_inbox_discard": self.export_inbox_discard,
            "export_discover": self.export_discover, "export_add_candidates": self.export_add_candidates,
        }
        handler = actions.get(action)
        if handler is None or not isinstance(params, dict):
            raise ValueError("Unknown desktop request.")
        return handler(params)

    def board_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.list(
            actor=field(params, "actor"),
            status=field(params, "status"),
            project=field(params, "project"),
            kind=field(params, "kind"),
            channel=field(params, "channel"),
            include_broadcasts=bool(params.get("include_broadcasts", False)),
        )

    def board_read(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.read(
            params.get("id"),
            actor=field(params, "actor"),
            mark_read=bool(params.get("mark_read", False)),
        )

    def board_open(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_to = params.get("to")
        to_val = raw_to if isinstance(raw_to, list) else field(params, "to", 2000)
        raw_refs = params.get("refs")
        refs_val = raw_refs if isinstance(raw_refs, list) else [r.strip() for r in field(params, "refs", 2000).split(",") if r.strip()]
        payload_val = params.get("payload") if isinstance(params.get("payload"), dict) else None
        return self.board.open_thread(
            kind=field(params, "kind") or "discussion",
            title=field(params, "title"),
            body=field(params, "body", 250_000),
            author=field(params, "author"),
            to=to_val,
            supervisor=field(params, "supervisor"),
            assignee=field(params, "assignee"),
            project=field(params, "project"),
            channel=field(params, "channel"),
            priority=field(params, "priority") or "normal",
            refs=refs_val,
            payload=payload_val,
        )

    def board_assign(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.assign(
            title=field(params, "title"),
            brief=field(params, "brief", 250_000),
            supervisor=field(params, "supervisor"),
            assignee=field(params, "assignee"),
            project=field(params, "project"),
            priority=field(params, "priority") or "normal",
        )

    def board_post(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_to = params.get("to")
        to_val = raw_to if isinstance(raw_to, list) else field(params, "to", 2000)
        raw_refs = params.get("refs")
        refs_val = raw_refs if isinstance(raw_refs, list) else [r.strip() for r in field(params, "refs", 2000).split(",") if r.strip()]
        payload_val = params.get("payload") if isinstance(params.get("payload"), dict) else None
        raw_reply = params.get("reply_to")
        if isinstance(raw_reply, bool):
            raise ValueError("reply_to must be a valid message ID.")
        reply_to = int(raw_reply) if raw_reply not in (None, "") else None
        return self.board.post(
            params.get("id"),
            author=field(params, "author"),
            message=field(params, "message", 250_000),
            status=field(params, "status"),
            kind=field(params, "kind"),
            reply_to=reply_to,
            to=to_val,
            refs=refs_val,
            payload=payload_val,
        )

    def board_inbox(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.inbox(
            field(params, "actor"),
            project=field(params, "project"),
            kind=field(params, "kind"),
            unread_only=bool(params.get("unread_only", True)),
        )

    def board_ack(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.ack(
            params.get("id"),
            actor=field(params, "author") or field(params, "actor"),
            message=field(params, "message", 250_000),
            post_ack=bool(params.get("post_ack", False)),
        )

    def board_agents(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.agents(
            project=field(params, "project"),
            include_offline=bool(params.get("include_offline", False)),
        )

    def export_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "bundles": list_bundles(),
            "harnesses": external_harness_status(),
            "exports_root": str(exports_root()),
        }

    def _export_detail(self, bdir: Path) -> dict[str, Any]:
        return read_bundle_detail(self.root, bdir, screener=self._screener_for(bdir) if _pending_inbox_count(bdir) else None)

    def export_inbox_promote(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        edits = {k: params[k] for k in ("title", "headline", "project", "content", "tags") if k in params}
        promote_inbox_proposal(self.root, bdir, field(params, "proposal_id"), use_scrubbed=bool(params.get("use_scrubbed")), also_export=bool(params.get("also_export")), force_blocked=bool(params.get("force_blocked")), screener=self._screener_for(bdir), **edits)
        return self._export_detail(bdir)

    def export_inbox_discard(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        discard_inbox_proposal(bdir, field(params, "proposal_id"))
        return self._export_detail(bdir)

    def export_read(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        return self._export_detail(bdir)

    def _parse_export_scope(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_proj = params.get("projects")
        if raw_proj is None:
            projects: list[str] | None = None
        elif isinstance(raw_proj, list):
            projects = [str(p).strip() for p in raw_proj if str(p).strip()]
        else:
            projects = [p.strip() for p in field(params, "projects", 2000).split(",") if p.strip()]

        raw_kinds = params.get("allow_kinds")
        if raw_kinds is None:
            allow_kinds: tuple[str, ...] | None = None
        elif isinstance(raw_kinds, list):
            allow_kinds = tuple(str(k).strip() for k in raw_kinds if str(k).strip())
        elif isinstance(raw_kinds, str) and raw_kinds.strip():
            allow_kinds = tuple(k.strip() for k in raw_kinds.split(",") if k.strip())
        else:
            allow_kinds = ()

        denylist_raw = params.get("denylist")
        extra_deny: tuple[str, ...] | None = None
        if isinstance(denylist_raw, str):
            extra_deny = tuple(x.strip() for x in denylist_raw.split(",") if x.strip())
        elif isinstance(denylist_raw, list):
            extra_deny = tuple(str(x).strip() for x in denylist_raw if str(x).strip())

        return {
            "allow_proposals": bool(params["allow_proposals"]) if "allow_proposals" in params else None,
            "projects": projects,
            "allow_kinds": allow_kinds,
            "threshold": float(params["threshold"]) if "threshold" in params and params["threshold"] is not None else None,
            "extra_denylist": extra_deny,
            "allow_sensitive_project": bool(params["allow_sensitive_project"])
            if "allow_sensitive_project" in params
            else None,
            "include_unprojected": bool(params["include_unprojected"]) if "include_unprojected" in params else None,
            "include_readonly_roots": bool(params["include_readonly_roots"]) if "include_readonly_roots" in params else None,
        }

    def export_inventory(self, params: dict[str, Any]) -> dict[str, Any]:
        bundle_name = field(params, "bundle")
        bdir = resolve_bundle_dir(bundle_name) if bundle_name else None
        return store_scope_inventory(self.root, bdir)

    def export_init(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "name"))
        parsed = self._parse_export_scope(params)
        init_bundle(
            bdir,
            allow_proposals=parsed["allow_proposals"] if parsed["allow_proposals"] is not None else True,
            projects=parsed["projects"] or [],
            allow_kinds=parsed["allow_kinds"] if parsed["allow_kinds"] is not None else ALLOWED_EXPORT_KINDS,
            threshold=0.50 if parsed["threshold"] is None else parsed["threshold"],
            extra_denylist=parsed["extra_denylist"] or (),
            allow_sensitive_project=bool(parsed["allow_sensitive_project"]),
            include_unprojected=bool(parsed["include_unprojected"]),
            include_readonly_roots=bool(parsed["include_readonly_roots"]),
        )
        return self._export_detail(bdir)

    def export_update_config(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        parsed = self._parse_export_scope(params)
        update_bundle_config(
            bdir,
            allow_proposals=parsed["allow_proposals"],
            projects=parsed["projects"],
            allow_kinds=parsed["allow_kinds"] if parsed["allow_kinds"] is not None else None,
            threshold=parsed["threshold"],
            extra_denylist=parsed["extra_denylist"],
            allow_sensitive_project=parsed["allow_sensitive_project"],
            include_unprojected=parsed["include_unprojected"],
            include_readonly_roots=parsed["include_readonly_roots"],
        )
        if params.get("restage", True):
            stage_bundle(self.root, bdir, screener=self._screener_for(bdir))
        return self._export_detail(bdir)

    def export_stage(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        stage_bundle(self.root, bdir, screener=self._screener_for(bdir))
        return self._export_detail(bdir)

    def export_discover(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        discover_bundle_candidates(
            self.root,
            bdir,
            include_readonly=bool(params.get("include_readonly", False)),
            screener=self._screener_for(bdir),
        )
        return self._export_detail(bdir)

    def export_add_candidates(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        raw_ids = params.get("doc_ids") or []
        doc_ids = [str(x).strip() for x in raw_ids if str(x).strip()] if isinstance(raw_ids, list) else []
        add_bundle_candidates(
            self.root,
            bdir,
            doc_ids=doc_ids,
            approve_if_clean=bool(params.get("approve_if_clean", False)),
            screener=self._screener_for(bdir),
        )
        return self._export_detail(bdir)

    def export_approve(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        raw_ids = params.get("doc_ids") or []
        doc_ids = [str(x).strip() for x in raw_ids if str(x).strip()] if isinstance(raw_ids, list) else []
        approve_bundle(
            self.root,
            bdir,
            doc_ids=doc_ids,
            all_clean=bool(params.get("all_clean", False)),
            allow_redacted=bool(params.get("allow_redacted", False)),
            force_blocked=bool(params.get("force_blocked", False)),
            screener=self._screener_for(bdir),
        )
        return self._export_detail(bdir)

    def export_revoke(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        raw_ids = params.get("doc_ids") or []
        doc_ids = [str(x).strip() for x in raw_ids if str(x).strip()] if isinstance(raw_ids, list) else []
        revoke_bundle(bdir, doc_ids=doc_ids, revoke_all=bool(params.get("revoke_all", False)))
        return self._export_detail(bdir)

    def export_wire(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        msg = wire_external_harness(bdir, harness=field(params, "harness"), disconnect=bool(params.get("disconnect", False)))
        return {"message": msg, "detail": self._export_detail(bdir)}

    def export_save_profile(self, params: dict[str, Any]) -> dict[str, Any]:
        bdir = resolve_bundle_dir(field(params, "bundle"))
        save_safe_profile(bdir, field(params, "content", 50_000))
        return self._export_detail(bdir)


def launch(root: Path) -> int:
    desktop = Path(__file__).resolve().parents[1] / "desktop"
    electron = desktop / "node_modules" / ".bin" / "electron"
    if not electron.exists():
        print("Brain desktop requires a checkout with its desktop dependencies installed. Run `npm ci --prefix desktop`.", file=sys.stderr)
        return 1
    env = dict(os.environ, GM_HOME=str(root), BRAIN_PYTHON=sys.executable)
    os.execve(electron, [str(electron), str(desktop)], env)
    return 1


def main() -> None:
    service = Desktop(gm_home())
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            response = {"result": service.request(request["action"], request.get("params", {}))}
        except FileNotFoundError as exc:
            response = {"error": str(exc) or "This memory is missing. Refresh the library to update the list."}
        except FileExistsError as exc:
            response = {"error": str(exc) if exc.filename is None else "A memory with this identity already exists. Open it to make changes."}
        except ValidationError as exc:
            response = {"error": validation_message(exc)}
        except (ValueError, PermissionError, KeyError, RuntimeError) as exc:
            msg = str(exc).strip("'") if isinstance(exc, KeyError) else str(exc)
            response = {"error": msg}
        except Exception:
            traceback.print_exc(file=sys.stderr)
            response = {"error": "Brain couldn’t complete this request. Refresh the library and try again."}
        print(json.dumps({"id": request_id, **response}), flush=True)


if __name__ == "__main__":
    main()
