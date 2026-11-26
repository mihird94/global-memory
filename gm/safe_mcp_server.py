"""Scoped MCP server serving SHA-256-verified export bundles and quarantined proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .export import _safe_note_path, resolve_bundle_dir, propose_to_inbox


def _audit_log(bundle_dir: Path, tool: str, status: str, start_ts: float, **meta: object) -> None:
    try:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": tool,
            "status": status,
            "ms": round((time.perf_counter() - start_ts) * 1000.0, 1),
            **{k: v for k, v in meta.items() if v != ""},
        }
        with (bundle_dir / "audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def load_manifest(bundle_dir: Path) -> dict[str, Any]:
    mpath = bundle_dir / "manifest.json"
    if not mpath.exists() or mpath.is_symlink():
        raise FileNotFoundError(f"Export bundle manifest missing or unsafe: {mpath}")
    return json.loads(mpath.read_text(encoding="utf-8"))


def safe_context_impl(bundle_dir: Path) -> str:
    t0 = time.perf_counter()
    manifest = load_manifest(bundle_dir)
    entries = manifest.get("entries", {})
    prof_path = bundle_dir / "safe_profile.md"
    profile_txt = ""
    if prof_path.exists() and not prof_path.is_symlink():
        profile_txt = prof_path.read_text(encoding="utf-8").strip()

    lines = [
        f"# Sanitized Brain Bundle (`{bundle_dir.name}` | manifest v{manifest.get('manifest_version', 1)} | {len(entries)} approved notes)",
    ]
    if profile_txt:
        lines.append("\n" + profile_txt)
    if entries:
        lines.append("\n## Approved Notes")
        for doc_id, meta in sorted(entries.items()):
            proj = f" [{meta['project']}]" if meta.get("project") else ""
            lines.append(f"- **{meta.get('title', doc_id)}** ({meta.get('kind', 'fact')}{proj}) `id:{doc_id}`")
    else:
        lines.append("\n_(No approved notes in this bundle yet.)_")
    _audit_log(bundle_dir, "safe_context", "ok", t0, count=len(entries))
    return "\n".join(lines)


def _fts_tokens(query: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_]+", query) if len(t) >= 1]


def safe_search_impl(bundle_dir: Path, query: str, project: str = "", kind: str = "", limit: int = 8) -> str:
    t0 = time.perf_counter()
    manifest = load_manifest(bundle_dir)
    entries = manifest.get("entries", {})
    if not entries:
        _audit_log(bundle_dir, "safe_search", "empty_bundle", t0, hits=0)
        return "No approved notes in this bundle."

    tokens = _fts_tokens(query)
    if not tokens:
        _audit_log(bundle_dir, "safe_search", "empty_query", t0, hits=0)
        return "Provide search keywords."
    limit = max(1, min(int(limit), 25))

    db_path = bundle_dir / "index.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"Missing bundle index: {db_path}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3.0)
    conn.row_factory = sqlite3.Row
    try:
        where = ["chunks_fts MATCH ?"]
        params: list[Any] = [" ".join(f'"{tok}"' for tok in tokens)]
        if project.strip():
            where.append("lower(d.project) = lower(?)")
            params.append(project.strip())
        if kind.strip():
            where.append("d.kind = ?")
            params.append(kind.strip())

        sql = f"""
            SELECT c.doc_id, c.heading, c.text, d.title, d.kind, d.project, bm25(chunks_fts, 2.5, 1.0) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            JOIN docs d ON d.id = c.doc_id
            WHERE {' AND '.join(where)}
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(sql, [*params, limit * 3]).fetchall()
        if not rows and len(tokens) > 1:
            params[0] = " OR ".join(f'"{tok}"' for tok in tokens)
            rows = conn.execute(sql, [*params, limit * 3]).fetchall()
    finally:
        conn.close()

    # Cross-check live manifest so even a concurrently revoked note cannot surface
    seen_docs: set[str] = set()
    hits = []
    for r in rows:
        did = r["doc_id"]
        if did not in entries or did in seen_docs:
            continue
        seen_docs.add(did)
        hits.append(r)
        if len(hits) >= limit:
            break

    if not hits:
        _audit_log(bundle_dir, "safe_search", "ok", t0, hits=0)
        return "No matching approved notes in this bundle."

    lines = [f"_Sanitized bundle search (`{bundle_dir.name}`): {len(hits)} match(es)_"]
    for h in hits:
        proj = f" [{h['project']}]" if h["project"] else ""
        sec = f" > {h['heading']}" if h["heading"] and h["heading"] != h["title"] else ""
        snip = re.sub(r"\s+", " ", h["text"]).strip()[:240]
        lines.append(f"- **{h['title']}{sec}** ({h['kind']}{proj}) `id:{h['doc_id']}`\n  {snip}")
    _audit_log(bundle_dir, "safe_search", "ok", t0, hits=len(hits))
    return "\n".join(lines)


def safe_read_impl(bundle_dir: Path, doc_id: str) -> str:
    t0 = time.perf_counter()
    manifest = load_manifest(bundle_dir)
    entries = manifest.get("entries", {})
    if doc_id not in entries:
        _audit_log(bundle_dir, "safe_read", "denied_not_in_manifest", t0, doc_id=doc_id)
        raise PermissionError(f"Document is not in the approved manifest: {doc_id!r}")

    note_path = _safe_note_path(bundle_dir, doc_id)
    if not note_path.exists():
        _audit_log(bundle_dir, "safe_read", "missing_file", t0, doc_id=doc_id)
        raise FileNotFoundError(f"Approved note missing on disk: {doc_id!r}")

    raw_bytes = note_path.read_bytes()
    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    expected_sha = entries[doc_id].get("exported_sha256", "")
    if actual_sha != expected_sha:
        _audit_log(bundle_dir, "safe_read", "integrity_error", t0, doc_id=doc_id, actual=actual_sha, expected=expected_sha)
        raise PermissionError(f"SHA-256 mismatch on approved note {doc_id!r}; failing closed.")

    _audit_log(bundle_dir, "safe_read", "ok", t0, doc_id=doc_id, sha256=actual_sha[:16])
    return raw_bytes.decode("utf-8")


def safe_propose_impl(bundle_dir: Path, *, title: str, content: str, kind: str = "lesson", project: str = "", headline: str = "", tags: str = "", harness: str = "") -> str:
    t0 = time.perf_counter()
    try:
        result = propose_to_inbox(bundle_dir, title=title, content=content, kind=kind, project=project, headline=headline, tags=tags, harness=harness)
    except (PermissionError, ValueError) as exc:
        _audit_log(bundle_dir, "safe_propose", "denied" if isinstance(exc, PermissionError) else "rejected", t0)
        raise
    _audit_log(bundle_dir, "safe_propose", "ok", t0, doc_id=result["proposal_id"], kind=kind, l1=result["l1_action"])
    return f"Queued proposal {result['proposal_id']} in bundle {bundle_dir.name!r}; human approval is required. L1 status: {result['l1_action']}. Entity types: {', '.join(result['l1_entity_types']) or 'none'}."


def create_safe_mcp(bundle_dir: Path) -> MCPServer:
    bundle_dir = bundle_dir.resolve()
    load_manifest(bundle_dir)  # Fail closed on startup if bundle manifest doesn't exist
    server = MCPServer("brain-safe")

    @server.tool()
    def safe_context() -> str:
        """Read-only sanitized profile and approved note index for this external workspace bundle."""
        try:
            return safe_context_impl(bundle_dir)
        except Exception as exc:
            raise ToolError(str(exc)) from None

    @server.tool()
    def safe_search(query: str, project: str = "", kind: str = "", limit: int = 8) -> str:
        """Search only human-approved, sanitized notes inside the exported bundle."""
        try:
            return safe_search_impl(bundle_dir, query=query, project=project, kind=kind, limit=limit)
        except Exception as exc:
            raise ToolError(str(exc)) from None

    @server.tool()
    def safe_read(doc_id: str) -> str:
        """Read one SHA-256-verified note from the approved export manifest."""
        try:
            return safe_read_impl(bundle_dir, doc_id=doc_id)
        except Exception as exc:
            raise ToolError(str(exc)) from None

    @server.tool()
    def safe_propose(title: str, content: str, kind: str = "lesson", project: str = "", headline: str = "", tags: str = "", harness: str = "") -> str:
        """Submit a quarantined candidate for human review; never writes directly to Brain."""
        try:
            return safe_propose_impl(bundle_dir, title=title, content=content, kind=kind, project=project, headline=headline, tags=tags, harness=harness)
        except Exception as exc:
            raise ToolError(str(exc)) from None

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="brain-safe-mcp", description="Scoped fail-closed Brain export MCP server with quarantined proposals")
    parser.add_argument("--bundle", default=os.environ.get("BRAIN_SAFE_BUNDLE", ""), help="Bundle name or path")
    args = parser.parse_args(argv)
    if not args.bundle.strip():
        raise SystemExit("Error: pass --bundle <name_or_path> or set BRAIN_SAFE_BUNDLE.")
    bundle_dir = resolve_bundle_dir(args.bundle)
    server = create_safe_mcp(bundle_dir)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
