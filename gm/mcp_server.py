"""Minimal 6-tool stdio MCP server (`brain`) for GM v3.2."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from mcp import types
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from pydantic import Field, ValidationError

from .index import build_context, index_single_item, recall, sync_index
from .store import ensure_layout, forget_memory, gm_home, list_projects, read_memory, save_memory, update_project
from .validation import HEADLINE_REQUIRED, HeadlineAnswer, needs_headline, validation_message

mcp = MCPServer("brain")
FORM_ELICITATION = types.ClientCapabilities(elicitation=types.ElicitationCapability(form=types.FormElicitationCapability()))


def _log_usage(tool: str, start_ts: float, **meta: object) -> None:
    try:
        root = gm_home()
        ensure_layout(root)
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tool": tool,
            "ms": round((time.perf_counter() - start_ts) * 1000.0, 1),
            **{k: v for k, v in meta.items() if v != ""},
        }
        with (root / ".gm" / "usage.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


@mcp.tool()
def brain_context(project: str = "", cwd: str = "") -> str:
    """Load the durable profile, active project state, and recent memory titles at session start.

    Call once if a session hook has not supplied context. Pass a project slug or the working
    directory for project detection. Follow up with brain_search about a specific claim or decision.
    """
    t0 = time.perf_counter()
    project = project.strip()
    if project and (Path(project).name != project or project in (".", "..") or "\0" in project):
        raise ToolError("Pass a project name in project or a working directory in cwd.")
    res = build_context(gm_home(), project=project, cwd=cwd.strip(), compact=True)
    _log_usage("brain_context", t0, project=project)
    return res


@mcp.tool()
def brain_search(
    query: str,
    project: str = "",
    kind: str = "",
    bucket: str = "",
    since: str = "",
    until: str = "",
    limit: int = 8,
) -> str:
    """Find matching memory excerpts before relying on a prior decision, fact, or preference.

    Verify weak matches against the full Markdown or another primary source. Use brain_read with
    a shortlisted ID when the excerpt leaves a material question open.

    Args:
        query: A topic, distinctive name, error code, or symbol from the task.
        project: A project slug to boost matching notes in that project.
        kind: Optional profile, project, decision, lesson, fact, episode, or journal.
        bucket: Use fact for durable knowledge (facts, decisions, lessons, projects, profiles) or episode for daily logs.
        since: Inclusive start date in YYYY-MM-DD.
        until: Inclusive end date in YYYY-MM-DD.
        limit: Positive maximum result count (default 8).
    """
    t0 = time.perf_counter()
    try:
        hits = recall(gm_home(), query=query, project=project, kind=kind, bucket=bucket,
                      since=since, until=until, limit=limit)
    except ValidationError as exc:
        raise ToolError(validation_message(exc)) from None
    if not hits:
        _log_usage("brain_search", t0, project=project, bucket=bucket, hits=0)
        return "No matching memories. Try a more distinctive term or broaden the filters. Verify directly if the answer matters."
    mode = hits[0].get("mode", "fts")
    reranked = "rerank" in mode
    if reranked:
        filtered = [h for h in hits if h["score"] >= 0.08]
        if not filtered:
            _log_usage("brain_search", t0, project=project, bucket=bucket, hits=0, mode=mode, top_score=hits[0]["score"])
            return f"_Retrieval: {mode} | Confidence: low (top score {hits[0]['score']}). Check a primary source before relying on memory._"
        hits = filtered

    top_conf = hits[0].get("confidence", "medium")
    _log_usage("brain_search", t0, project=project, bucket=bucket, hits=len(hits), mode=mode, top_conf=top_conf)
    header = f"_Retrieval: {mode} | Top confidence: {top_conf}_"
    if reranked and (hits[0]["score"] < 0.25 or top_conf != "high"):
        header += "\n_Check the full source or verify directly before acting on this result._"
    elif not reranked:
        header += "\n_Open the source with brain_read to verify a match before relying on it._"

    lines = [header]
    for h in hits:
        proj = f" [{h['project']}]" if h["project"] else ""
        sec = f" > {h['heading']}" if h["heading"] and h["heading"] != h["title"] else ""
        lines.append(f"- **{h['title']}{sec}** ({h['bucket']}/{h['kind']}{proj}, {h['updated_at']}, {h['confidence']}) `id:{h['id']}`")
        if h["headline"] and h["headline"] != h["title"]:
            lines.append(f"  Headline · {h['headline']}")
        if h.get("conflicts_with"):
            peers = ", ".join(f"`{c['id']}` ({c['updated_at']})" for c in h["conflicts_with"][:2])
            lines.append(f"  Conflict · differs from {peers} — verify newer/scoped truth and supersede or brain_forget stale note")
        lines.append(f"  {h['snippet']}")
    return "\n".join(lines)


@mcp.tool()
def brain_read(id_or_path: str) -> str:
    """Read a shortlisted memory's full Markdown and provenance. Use the exact ID from brain_search or a Markdown path in a configured memory root."""
    t0 = time.perf_counter()
    try:
        path, content = read_memory(gm_home(), id_or_path)
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        raise ToolError(str(exc)) from None
    _log_usage("brain_read", t0, target=id_or_path)
    return f"<!-- {path} -->\n{content}"


@mcp.tool()
async def brain_store(
    content: str,
    title: str = "",
    kind: str = "fact",
    project: str = "",
    tags: list[str] | None = None,
    subject: str = "",
    predicate: str = "",
    headline: Annotated[str, Field(description=HEADLINE_REQUIRED)] = "",
    source: str = "",
    epistemic: str = "",
    author: str = "",
    ctx: Context | None = None,
) -> str:
    """Save a verified fact, confirmed decision, root-cause lesson, or concise session milestone.

    Select one enduring takeaway. For a decision, state the choice and tradeoff. For a lesson,
    state the observed failure and verified fix. Save an unresolved claim worth keeping as an
    episode with a [hypothesis] prefix. Use brain_project for a project's complete living state.
    Pass both subject and predicate to update a mutable fact and retain the prior value as superseded.
    Supply a one-line headline for a fact over 400 characters. Brain derives a headline for other records in the Facts view when omitted.
    The search index updates as part of the save.

    Args:
        content: Concise Markdown body, or the value of a mutable fact.
        title: Stable descriptive label used to generate the memory ID.
        kind: fact, decision, lesson, project, journal, or episode.
        project: Optional project slug.
        tags: Optional list of short tags.
        subject: Entity in a mutable fact identity.
        predicate: Attribute in a mutable fact identity.
        headline: One line summarizing the verified fact. Required when fact content exceeds 400 characters.
        source: Optional provenance (e.g. 'user', file path, commit hash, or URL).
        epistemic: Optional epistemic class: verified, decision, lesson, or hypothesis (episode only).
        author: Optional harness/author label (e.g. 'antigravity', 'codex', 'claude-code').
    """
    t0 = time.perf_counter()
    root = gm_home()
    fields = dict(content=content, title=title, kind=kind, project=project, tags=tags,
                  subject=subject, predicate=predicate, source=source, epistemic=epistemic, author=author)
    try:
        item = save_memory(root, **fields, headline=headline)
    except ValidationError as exc:
        if not needs_headline(exc):
            raise ToolError(validation_message(exc)) from None
        retry = f"{HEADLINE_REQUIRED} Retry brain_store with headline filled in."
        if ctx is None or not ctx.session.check_client_capability(FORM_ELICITATION):
            raise ToolError(retry) from None
        try:
            answer = await ctx.elicit(HEADLINE_REQUIRED, schema=HeadlineAnswer)
        except (MCPError, ValueError):
            raise ToolError(retry) from None
        if answer.action != "accept" or answer.data is None:
            raise ToolError(retry) from None
        item = save_memory(root, **fields, headline=answer.data.headline)
    index_single_item(root, item, background_embed=True)
    _log_usage("brain_store", t0, kind=item.kind, project=project, saved=item.id)
    result = {"stored": item.id, "path": str(item.path), "kind": item.kind}
    if item.headline:
        result["headline"] = item.headline
    return json.dumps(result)


@mcp.tool()
def brain_project(name: str = "", update: str = "", repo_root: str = "") -> str:
    """List projects with no arguments. Pass a name to read its living state. To update, provide the complete current Markdown with status, decisions, and next steps (and optional `repo_root` path for auto-detection)."""
    t0 = time.perf_counter()
    root = gm_home()
    if not name.strip():
        if update.strip() or repo_root.strip():
            raise ToolError("Provide the project name along with its updated Markdown.")
        projs = list_projects(root)
        _log_usage("brain_project", t0, action="list")
        return "Projects: " + (", ".join(projs) if projs else "(none)")
    try:
        item = update_project(root, name=name, update=update, repo_root=repo_root)
    except FileNotFoundError:
        raise ToolError("Project not found. Call brain_project without arguments to list project names.") from None
    if update.strip() or repo_root.strip():
        index_single_item(root, item, background_embed=True)
        _log_usage("brain_project", t0, action="update", project=name)
        return json.dumps({"updated": item.id, "path": str(item.path)})
    _log_usage("brain_project", t0, action="read", project=name)
    return item.body


@mcp.tool()
def brain_forget(id_or_path: str) -> str:
    """Reversibly archive a stale, incorrect, or superseded memory. Verify the exact ID with brain_search and brain_read first. The Markdown moves to the archive and drops out of search."""
    t0 = time.perf_counter()
    root = gm_home()
    try:
        archived = forget_memory(root, id_or_path)
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        raise ToolError(str(exc)) from None
    sync_index(root, with_embeddings=False, background_embed=False)
    _log_usage("brain_forget", t0, archived=archived)
    return json.dumps({"archived": archived})


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
