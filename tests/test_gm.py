"""Tests for GM v3 core store, FTS5 index, migration, and MCP surface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gm.facts import backfill_headlines
from gm.index import build_context, recall, reindex_all, sync_index
from gm.mcp_server import mcp
from gm.migrate import migrate_v2
from gm.store import (
    ensure_layout,
    forget_memory,
    list_projects,
    read_memory,
    save_memory,
    update_project,
)


def test_save_recall_read_forget_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    item = save_memory(
        root,
        content="Always enable WAL mode and busy_timeout for concurrent SQLite access.",
        title="SQLite concurrency rule",
        kind="decision",
        project="global-memory",
        tags=["sqlite", "concurrency"],
    )
    assert item.path.exists()
    sync_index(root)

    hits = recall(root, "WAL busy_timeout", project="global-memory")
    assert hits
    assert hits[0]["id"] == item.id
    assert hits[0]["kind"] == "decision"

    full_path, body = read_memory(root, item.id)
    assert Path(full_path) == item.path
    assert "busy_timeout" in body

    archived = forget_memory(root, item.id)
    assert (root / "_archive_v3" / archived).exists()
    sync_index(root)
    assert recall(root, "busy_timeout") == []


def test_error_code_and_hyphen_queries(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    save_memory(
        root,
        content="Fixed ERR_CONNECTION_REFUSED by binding uvicorn to 127.0.0.1.",
        title="Uvicorn bind fix",
        kind="lesson",
    )
    sync_index(root)
    hits = recall(root, "ERR_CONNECTION_REFUSED 127.0.0.1")
    assert len(hits) == 1
    assert "uvicorn" in hits[0]["snippet"].lower()


def test_journal_appends_and_project_overwrites(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    j1 = save_memory(root, "First entry", title="Morning", kind="journal")
    j2 = save_memory(root, "Second entry", title="Evening", kind="journal")
    assert j1.path == j2.path
    txt = j2.path.read_text(encoding="utf-8")
    assert "First entry" in txt and "Second entry" in txt

    update_project(root, "alphaos", "Status: v1")
    update_project(root, "alphaos", "Status: v2")
    assert list_projects(root) == ["alphaos"]
    assert "v2" in (root / "projects" / "alphaos.md").read_text(encoding="utf-8")
    assert "v1" not in (root / "projects" / "alphaos.md").read_text(encoding="utf-8")


def test_progressive_disclosure_context_is_compact(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    ensure_layout(root)
    (root / "profile.md").write_text("# Profile\n" + "\n".join(f"- Pref {i}" for i in range(100)), encoding="utf-8")
    update_project(root, "alphaos", "Active trading engine.\n" + "x" * 2000)
    save_memory(root, "Keep MCP tools under 6.", title="MCP budget", kind="decision")

    ctx = build_context(root, project="alphaos", compact=True)
    assert len(ctx) < 2200
    assert "Active Project: alphaos" in ctx
    assert "MCP budget" in ctx


def test_readonly_extra_root(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    wiki = tmp_path / "llm-wiki"
    wiki.mkdir()
    (wiki / "topic.md").write_text("# Quantum Notes\nSuperposition example.", encoding="utf-8")

    ensure_layout(root)
    (root / ".gm" / "config.json").write_text(json.dumps({"extra_roots": [str(wiki)]}), encoding="utf-8")
    reindex_all(root)

    hits = recall(root, "Superposition")
    assert hits and hits[0]["id"].startswith("llm-wiki:")
    with pytest.raises(PermissionError):
        forget_memory(root, hits[0]["id"])


def test_migrate_v2_non_destructive(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "projects" / "demo" / "activeContext.md").write_text("Working on v3.", encoding="utf-8")
    (root / "semantic").mkdir(parents=True)
    (root / "semantic" / "facts.json").write_text(
        json.dumps({"alphaos.mode": "swing", "birthday_sam": "May 1"}), encoding="utf-8"
    )
    (root / "lessons").mkdir(parents=True)
    (root / "lessons" / "global.md").write_text(
        "- Ollama required for GMS.\n- Always run replay validation.\n", encoding="utf-8"
    )
    (root / "episodic" / "history").mkdir(parents=True)
    (root / "episodic" / "history" / "2026-11-21.md").write_text("# Day log\nDone.", encoding="utf-8")
    (root / "preferences.md").write_text("# Prefs\n- Concise.", encoding="utf-8")
    (root / "gms_trust.sqlite").write_bytes(b"fake")

    res = migrate_v2(root, dry_run=False)
    assert res["profile"] is True
    assert "demo" in res["projects"]
    assert res["lessons"] == 1  # Ollama lesson filtered out
    assert res["journals"] == 1
    assert (root / "_archive_v2" / "gms_trust.sqlite").exists()
    assert (root / "profile.md").exists()
    assert recall(root, "replay validation")
    assert recall(root, "May 1")


def test_mcp_exposes_expected_tools() -> None:
    tools = sorted(mcp._tool_manager._tools.keys())
    assert tools == [
        "brain_board",
        "brain_checkpoint_observe",
        "brain_checkpoint_pending",
        "brain_checkpoint_revision",
        "brain_checkpoint_save",
        "brain_checkpoint_skip",
        "brain_context",
        "brain_forget",
        "brain_project",
        "brain_read",
        "brain_search",
        "brain_store",
    ]
    props = mcp._tool_manager._tools["brain_store"].parameters["properties"]
    assert "headline" in props and "ctx" not in props


def test_facts_episodes_buckets_and_hybrid_rerank_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np
    from gm import index as gm_index

    root = tmp_path / "memories"
    save_memory(root, "Use WAL mode for SQLite concurrency.", title="SQLite WAL", kind="fact")
    save_memory(root, "Debugged broken CI pipeline today.", title="CI debug", kind="episode")

    # Deterministic mock embeddings + cross-encoder reranker
    def fake_embed_texts(texts: list[str], timeout: float = 15.0) -> list[np.ndarray]:
        out = []
        for t in texts:
            v = np.array([1.0, 0.0] if "WAL" in t or "database" in t else [0.0, 1.0], dtype=np.float32)
            out.append(v)
        return out

    def fake_embed_query(query: str, timeout: float = 3.0) -> np.ndarray:
        return fake_embed_texts([query])[0]

    def fake_rerank(query: str, docs: list[str], cache_dir: Path) -> list[float]:
        return [0.95 if "WAL" in d else 0.20 for d in docs]

    monkeypatch.setattr(gm_index, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(gm_index, "embed_query", fake_embed_query)
    monkeypatch.setattr(gm_index, "rerank_candidates", fake_rerank)

    res = reindex_all(root)
    assert res["embedded"] == res["chunks"] and res["embedded"] >= 2

    # Semantic-only query ("database" isn't in the text lexically, only matched via vector!)
    hits = recall(root, "database", bucket="fact")
    assert len(hits) == 1
    assert hits[0]["bucket"] == "fact"
    assert hits[0]["title"] == "SQLite WAL"

    ep_hits = recall(root, "CI pipeline", bucket="episode")
    assert len(ep_hits) == 1
    assert ep_hits[0]["bucket"] == "episode"

    # Both candidates -> rerank fires and reports hybrid+rerank
    all_hits = recall(root, "WAL CI")
    assert len(all_hits) == 2
    assert all_hits[0]["mode"] == "hybrid+rerank"
    assert all_hits[0]["title"] == "SQLite WAL"
    assert all_hits[0]["confidence"] == "high"
    assert all_hits[1]["confidence"] == "medium"


def test_chunk_level_indexing_finds_deep_section(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    filler = "Standard operational padding text. " * 120  # > 4000 chars
    body = f"# Long Doc\n\n## Intro\n{filler}\n\n## Deep Secret\nThe hidden Tailscale IP is 198.51.100.77.\n"
    save_memory(root, body, title="Long Doc", kind="fact", headline="Long doc containing hidden Tailscale IP")
    res = reindex_all(root)
    assert res["chunks"] >= 4

    hits = recall(root, "198.51.100.77")
    assert hits
    assert hits[0]["heading"] == "Deep Secret"
    assert "198.51.100.77" in hits[0]["snippet"]


def test_provenance_and_epistemic_validation(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    item = save_memory(
        root,
        "192.0.2.10",
        kind="fact",
        subject="minipc",
        predicate="tailscale_ip",
        source="user",
        epistemic="verified",
        author="antigravity",
    )
    raw = item.path.read_text(encoding="utf-8")
    assert "epistemic: verified" in raw
    assert "source: user" in raw
    assert "author: antigravity" in raw

    with pytest.raises(ValidationError):
        save_memory(root, "Maybe Redis is faster", kind="fact", epistemic="hypothesis")
    with pytest.raises(ValidationError, match="kind='episode'"):
        save_memory(root, "# Open question\n\n[hypothesis] A possible explanation.", kind="fact")


def test_long_fact_requires_a_headline_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    with pytest.raises(ValidationError, match="one-line headline"):
        save_memory(root, "é" * 401, title="Title alone", subject="runner", predicate="settings", headline="   ")
    assert not root.exists()
    assert save_memory(root, "é" * 400, title="At the boundary").headline
    posted = save_memory(root, "é" * 401, title="Lengthy fact", headline="A verified headline")
    assert posted.headline == "A verified headline"


def test_fact_backfill_preserves_original_bytes_and_timestamp(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    ensure_layout(root)
    path = root / "notes" / "facts" / "legacy.md"
    original = b"---\r\nkind: fact\r\ncustom: preserved\r\n---\r\n\r\n# Legacy\r\n\r\nExisting statement.\r\n"
    path.write_bytes(original)
    stamp = path.stat().st_mtime_ns
    assert backfill_headlines(root, dry_run=True)["missing_headlines"] == 1
    assert path.read_bytes() == original
    assert backfill_headlines(root)["backfilled"] == 1
    assert path.read_bytes().replace(b'headline: "Existing statement."\r\n', b"") == original
    assert path.stat().st_mtime_ns == stamp
    assert backfill_headlines(root)["backfilled"] == 0


def test_read_time_lazy_conflict_detection(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    # Two paraphrased notes on the same slot with conflicting IP literals
    save_memory(root, "MiniPC Tailscale IP is 192.0.2.10", title="MiniPC Tailscale IP", kind="fact")
    save_memory(root, "MiniPC Tailscale IP is 192.0.2.99", title="MiniPC Tailscale Address", kind="fact")
    # Unrelated note should not conflict
    save_memory(root, "Python 3.13 with uv is preferred", title="Python Toolchain", kind="fact")

    hits = recall(root, "MiniPC Tailscale IP", limit=5)
    assert len(hits) >= 2
    assert hits[0].get("conflicts_with")
    assert hits[1].get("conflicts_with")

    # Different project scopes should NOT be flagged as conflicting
    root2 = tmp_path / "memories_scoped"
    save_memory(root2, "Max position cap is $1500", title="Position Sizing Cap", kind="fact", project="screener")
    save_memory(root2, "Max position cap is $5000", title="Position Sizing Cap", kind="fact", project="agentic")
    scoped_hits = recall(root2, "Max position cap", limit=5)
    assert len(scoped_hits) == 2
    assert not scoped_hits[0].get("conflicts_with")


def test_project_repo_root_and_slug_normalization(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    repo_dir = tmp_path / "projects" / "office"
    (repo_dir / "src").mkdir(parents=True)

    update_project(root, "forma-office", "Status: active.", repo_root=str(repo_dir))
    update_project(root, "learning-os", "Status: active.")

    # Auto-detects forma-office even from nested subfolder of ~/projects/office
    ctx = build_context(root, cwd=str(repo_dir / "src"))
    assert "Active Project: forma-office" in ctx

    # Underscore vs hyphen project slug normalization works in context & search
    ctx_l = build_context(root, project="learning_os")
    assert "Active Project: learning-os" in ctx_l
    save_memory(root, "Flashcards use SM-2.", title="Spaced repetition", kind="fact", project="learning_os")
    hits = recall(root, "SM-2", project="learning_os")
    assert hits and hits[0]["project"] == "learning-os"


def test_three_part_fact_auto_supersedes(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    f1 = save_memory(root, "192.0.2.10", kind="fact", subject="minipc", predicate="tailscale_ip")
    f2 = save_memory(root, "192.0.2.99", kind="fact", subject="minipc", predicate="tailscale_ip")
    assert f1.path == f2.path
    txt = f2.path.read_text(encoding="utf-8")
    assert "**Value:** 192.0.2.99" in txt
    assert "**Supersedes:** 192.0.2.10" in txt
