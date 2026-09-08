"""
harvest.py — Automated Post-Session Memory Harvesting ("Agentic Sleep")
========================================================================
Performs micro-consolidation at the end of an agent session or workflow milestone:
  1. Inspects recent episodic log entries and session summary.
  2. Extracts candidate semantic facts and structured configurations.
  3. Validates candidates against namespaced schema contracts (tools/schemas.py).
  4. Persists valid facts through the trust gateway (conflict checks & claim ledger).
  5. Extracts knowledge graph triples with bi-temporal validity.
  6. Incrementally embeds new text chunks directly into gms_trust.sqlite (gms_embeddings).
  7. Rewards the completing agent's trust reputation (+0.5 alpha).

Works cross-platform (macOS and Linux x86_64) without external dependencies.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import memory_mcp_server
from schemas import validate_fact, parse_payload


def _extract_candidate_facts(text: str) -> list[tuple[str, Any, str]]:
    """
    Extract (key, value, kind) candidate facts from text using regex and heuristics.
    """
    candidates = []
    if not text:
        return candidates

    # 1. Look for explicit JSON blocks or key-value structures
    # E.g. [FACT:infra.minipc] {"host": "minipc", "ip": "100.85.120.45", ...}
    explicit_matches = re.finditer(
        r"\[(?:FACT|CLAIM|MEMORY):([a-zA-Z0-9_\.\-]+)\]\s*(\{.*?\}|\[.*?\]|[^\n]+)",
        text,
        re.DOTALL
    )
    for m in explicit_matches:
        k = m.group(1).strip()
        raw_val = m.group(2).strip()
        candidates.append((k, parse_payload(raw_val), "semantic"))

    # 2. Key-value lines: "key: value" or "key = value"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        # Strip bullet points
        if line.startswith("- ") or line.startswith("* "):
            line = line[2:].strip()

        kv_match = re.match(r"^([a-zA-Z0-9_\.\-]{3,40})\s*[:=]\s*(.+)$", line)
        if kv_match:
            k = kv_match.group(1).strip()
            v = kv_match.group(2).strip()
            # Filter out common conversational false positives
            if k.lower() in ("note", "summary", "task", "status", "http", "https", "error", "warning", "info"):
                continue
            candidates.append((k, parse_payload(v), "semantic"))

    return candidates


def harvest_session(
    agent: str,
    summary: str,
    text: str | None = None,
    incremental_index: bool = True,
    mem_root: Path | None = None,
) -> dict[str, Any]:
    """
    Execute post-session micro-consolidation.
    """
    root = mem_root or memory_mcp_server.MEM_ROOT
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # 1. Gather text to harvest from
    harvest_text_parts = [f"Session End Summary ({agent}): {summary}"]
    if text:
        harvest_text_parts.append(text)
    else:
        daily_file = root / "episodic" / "history" / f"{today}.md"
        if daily_file.exists():
            try:
                recent_content = daily_file.read_text(errors="replace")
                # Take last 3000 chars of today's notes
                harvest_text_parts.append(recent_content[-3000:])
            except Exception:
                pass

    combined_text = "\n\n".join(harvest_text_parts)

    saved_facts = []
    rejected_facts = []
    triples_recorded = 0
    vectors_indexed = 0

    memory_mcp_server.init_db()

    # 2. Extract and validate candidate facts
    candidates = _extract_candidate_facts(combined_text)
    for key, val, kind in candidates:
        is_valid, norm_val, err_msg = validate_fact(key, val)
        if is_valid:
            # Route through memory_mcp_server trust gateway
            val_str = json.dumps(norm_val) if isinstance(norm_val, (dict, list)) else str(norm_val)
            res = memory_mcp_server.tool_mem_save_typed({
                "key": key,
                "value": val_str,
                "kind": kind,
                "agent": agent,
            })
            if "Fact saved" in res or "unchanged" in res:
                saved_facts.append({"key": key, "value": norm_val, "status": "saved"})
            else:
                saved_facts.append({"key": key, "value": norm_val, "status": res})
        else:
            rejected_facts.append({"key": key, "error": err_msg})

    # 3. Extract knowledge graph triples with temporal validity
    triples = memory_mcp_server.extract_graph_triples(combined_text)
    for sub, pred, obj in triples:
        try:
            rel_id = memory_mcp_server.record_graph_relationship(
                sub, pred, obj,
                valid_from=now.isoformat()
            )
            if rel_id > 0:
                triples_recorded += 1
        except Exception:
            pass

    # 4. Incremental vector indexing into SQLite gms_embeddings
    if incremental_index:
        try:
            chunks = []
            # Split summary and text into chunks
            for paragraph in combined_text.split("\n\n"):
                paragraph = paragraph.strip()
                if len(paragraph) >= 40:
                    chunks.append(paragraph)

            items_to_store = []
            for i, chunk in enumerate(chunks[:10]):  # Limit to top 10 chunks per session
                emb = memory_mcp_server._embed(chunk)
                if emb:
                    items_to_store.append({
                        "source": f"session:{today}:{agent}",
                        "chunk": i,
                        "text": chunk,
                        "embedding": emb,
                    })

            if items_to_store:
                vectors_indexed = memory_mcp_server.store_sqlite_embeddings(
                    items_to_store,
                    model=memory_mcp_server.EMBED_MODEL,
                )
        except Exception:
            pass

    # 5. Reward agent reputation (+0.5 alpha)
    try:
        memory_mcp_server.increment_agent_alpha(agent, 0.5)
    except Exception:
        pass

    return {
        "status": "success",
        "agent": agent,
        "summary": summary,
        "facts_saved": saved_facts,
        "facts_rejected": rejected_facts,
        "triples_recorded": triples_recorded,
        "vectors_indexed": vectors_indexed,
        "timestamp": now.isoformat(),
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Harvest memory facts and graph edges from a session.")
    parser.add_argument("--agent", default="Antigravity", help="Agent name")
    parser.add_argument("--summary", required=True, help="Session summary")
    parser.add_argument("--text", default=None, help="Optional text context")
    parser.add_argument("--no-index", action="store_true", help="Skip incremental vector indexing")
    args = parser.parse_args()

    report = harvest_session(
        agent=args.agent,
        summary=args.summary,
        text=args.text,
        incremental_index=not args.no_index,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
