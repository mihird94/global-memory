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
from .index import _connect, _doc_filters, build_context, index_single_item, index_stats, recall, sync_index
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
TOOLS = ("context", "search", "read", "store", "project", "forget")


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
            "board_assign": self.board_assign, "board_post": self.board_post,
        }
        handler = actions.get(action)
        if handler is None or not isinstance(params, dict):
            raise ValueError("Unknown desktop request.")
        return handler(params)

    def board_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.list(actor=field(params, "actor"), status=field(params, "status"), project=field(params, "project"))

    def board_read(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.read(params.get("id"))

    def board_assign(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.assign(title=field(params, "title"), brief=field(params, "brief", 250_000),
                                 supervisor=field(params, "supervisor"), assignee=field(params, "assignee"),
                                 project=field(params, "project"))

    def board_post(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.board.post(params.get("id"), author=field(params, "author"),
                               message=field(params, "message", 250_000), status=field(params, "status"))


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
        except FileNotFoundError:
            response = {"error": "This memory is missing. Refresh the library to update the list."}
        except FileExistsError as exc:
            response = {"error": str(exc) if exc.filename is None else "A memory with this identity already exists. Open it to make changes."}
        except ValidationError as exc:
            response = {"error": validation_message(exc)}
        except (ValueError, PermissionError) as exc:
            response = {"error": str(exc)}
        except Exception:
            traceback.print_exc(file=sys.stderr)
            response = {"error": "Brain couldn’t complete this request. Refresh the library and try again."}
        print(json.dumps({"id": request_id, **response}), flush=True)


if __name__ == "__main__":
    main()
