#!/usr/bin/env python3
"""
tools/migrate_flat_records.py — Idempotent migration of legacy flat facts to typed context records.

Reads the 6 verified flat string facts from semantic/facts.json, links them to their
authoritative source passages in episodic history, converts them into schema-valid
gms-context-record-v1 candidates, and stages them in gms_context_candidates for review.

Supports:
  --dry-run: (default) Previews structured envelopes and diffs without modifying database.
  --apply: Stages the candidates idempotently into gms_context_candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import memory_mcp_server
import schemas

DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")).expanduser()

LEGACY_TARGET_KEYS = [
    "gms_durable_policy_format",
    "mbrain_agent_trust_architecture",
    "mbrain_context_packet_engine",
    "global_memory_sqlite_concurrency",
    "retrieval_benchmark_bm25_performance",
    "retrieval_benchmark_harness_path",
]


def _hash_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def build_migrated_candidates(mem_root: Path | None = None) -> list[dict[str, Any]]:
    """Construct typed gms-context-record-v1 envelopes for the 6 flat records."""
    root = Path(mem_root).expanduser() if mem_root else DEFAULT_MEM_ROOT
    history_file = root / "episodic" / "history" / "2026-09-08.md"
    history_text = history_file.read_text(encoding="utf-8") if history_file.exists() else ""
    # Temporary construction value; every candidate is replaced below with
    # the hash of its exact cited line range before validation or staging.
    history_hash = _hash_text(history_text) if history_text else "sha256:0000000000000000"
    history_lines = history_text.splitlines()

    # These locators point to passages that actually exist in the canonical
    # 2026-09-08 history.  Hash the cited excerpt, never the entire document.
    evidence_lines = {
        "gms.durable_policy_format": (19, 20),
        "mbrain.agent_trust_architecture": (16, 17),
        "mbrain.context_packet_engine": (35, 35),
        "global_memory.sqlite_concurrency": (44, 44),
        "retrieval_benchmark.bm25_performance": (57, 57),
        "retrieval_benchmark.harness_path": (53, 53),
    }

    candidates: list[dict[str, Any]] = []

    # 1. gms_durable_policy_format -> policy
    p1 = {
        "schema_version": "gms-context-record-v1",
        "record_type": "policy",
        "key": "gms.durable_policy_format",
        "statement": "Durable policies in GMS must be structured decision records containing rationale, implications, scope, provenance, and review conditions rather than standalone status flags.",
        "rationale": "A flat status flag or string lacks enough context for another agent to understand the constraint, why it was chosen, and what tradeoffs or boundaries apply.",
        "implications": [
            "All durable policies require statement, rationale, scope, provenance, and behavioral implications.",
            "Policies cannot be auto-promoted without explicit human review.",
            "A decision or policy must be understandable when retrieved in isolation without parent session context."
        ],
        "scope": {
            "level": "system",
            "project": "global-memory",
            "workstream": "context-engineering",
            "applies_to": ["dream-cycle", "schemas", "memoryctl", "desktop-ui"]
        },
        "provenance": {
            "observed_agents": ["Codex", "Mihir"],
            "extractor": "migration-pass5",
            "source_refs": ["episodic/history/2026-09-08.md#sec-rationale-first"],
            "source_hashes": [history_hash],
            "extracted_at": "2026-09-08T18:30:00Z",
            "prompt_version": "migration-v1",
            "provider": "system",
            "model": "deterministic-migrator"
        },
        "evidence": [
            {
                "type": "source_document",
                "ref": "episodic/history/2026-09-08.md#sec-rationale-first",
                "excerpt_hash": history_hash
            }
        ],
        "freshness": {
            "effective_at": "2026-09-08T08:59:00Z",
            "review_after": None,
            "status": "fresh",
            "supersedes": ["gms_durable_policy_format"]
        },
        "review": {
            "status": "proposed",
            "requires_human": True,
            "reasons": ["migrated from legacy flat record; requires review before replacing active memory"]
        },
        "authority": "source_document",
        "verification": "verified"
    }
    candidates.append(p1)

    # 2. mbrain_agent_trust_architecture -> decision
    p2 = {
        "schema_version": "gms-context-record-v1",
        "record_type": "decision",
        "key": "mbrain.agent_trust_architecture",
        "statement": "Global agent trust and reliability percentage tiers are retired in Mbrain UX in favor of Provenance & Activity tracking.",
        "rationale": "A single score collapses task domain, evidence quality, provenance, recency, review history, and failure severity into false certainty; one accepted observation can misleadingly appear equivalent to a long audited record.",
        "implications": [
            "Show provenance, recency, contribution counts, active claims, disputes, and review outcomes as separate dimensions.",
            "Make accept or reject decisions at the claim or task level.",
            "Do not reintroduce trust through proxy labels such as reliability, reputation, confidence, quality, or health."
        ],
        "scope": {
            "level": "project",
            "project": "global-memory",
            "workstream": "mbrain",
            "applies_to": ["desktop-ui", "dream-cycle", "context-packets"]
        },
        "provenance": {
            "observed_agents": ["Codex", "Mihir"],
            "extractor": "migration-pass5",
            "source_refs": ["episodic/history/2026-09-08.md#sec-trust-retired"],
            "source_hashes": [history_hash],
            "extracted_at": "2026-09-08T18:30:00Z",
            "prompt_version": "migration-v1",
            "provider": "system",
            "model": "deterministic-migrator"
        },
        "evidence": [
            {
                "type": "user_instruction",
                "ref": "episodic/history/2026-09-08.md#sec-trust-retired",
                "excerpt_hash": history_hash
            }
        ],
        "freshness": {
            "effective_at": "2026-09-08T08:42:00Z",
            "review_after": None,
            "status": "fresh",
            "supersedes": ["mbrain_agent_trust_architecture"]
        },
        "review": {
            "status": "proposed",
            "requires_human": True,
            "reasons": ["migrated from legacy flat record; architectural decision requiring explicit review"]
        },
        "authority": "user_instruction",
        "verification": "verified"
    }
    candidates.append(p2)

    # 3. mbrain_context_packet_engine -> decision
    p3 = {
        "schema_version": "gms-context-record-v1",
        "record_type": "decision",
        "key": "mbrain.context_packet_engine",
        "statement": "Deterministic Context Packet engine supports Small, Standard, and Deep tiers with SHA-256 hash verification and secret masking.",
        "rationale": "Cross-agent handoffs require bounded, budget-aware context reconstruction that avoids token explosion while guaranteeing deterministic repeatability and privacy boundaries.",
        "implications": [
            "All context packets must be deterministically hashable with SHA-256.",
            "Support small (~2k tokens), standard (~6k tokens), and deep (~15k tokens) budget profiles.",
            "All passwords, tokens, keys, and credentials must be masked with [REDACTED_*] before hashing or exporting."
        ],
        "scope": {
            "level": "project",
            "project": "global-memory",
            "workstream": "mbrain",
            "applies_to": ["desktop-ui", "context-packets", "task-handoffs"]
        },
        "provenance": {
            "observed_agents": ["Antigravity", "Codex"],
            "extractor": "migration-pass5",
            "source_refs": ["episodic/history/2026-09-08.md#sec-context-packets"],
            "source_hashes": [history_hash],
            "extracted_at": "2026-09-08T18:30:00Z",
            "prompt_version": "migration-v1",
            "provider": "system",
            "model": "deterministic-migrator"
        },
        "evidence": [
            {
                "type": "source_document",
                "ref": "episodic/history/2026-09-08.md#sec-context-packets",
                "excerpt_hash": history_hash
            }
        ],
        "freshness": {
            "effective_at": "2026-09-08T09:17:00Z",
            "review_after": None,
            "status": "fresh",
            "supersedes": ["mbrain_context_packet_engine"]
        },
        "review": {
            "status": "proposed",
            "requires_human": True,
            "reasons": ["migrated from legacy flat record; requires review before replacing active memory"]
        },
        "authority": "verified_system_output",
        "verification": "verified"
    }
    candidates.append(p3)

    # 4. global_memory_sqlite_concurrency -> decision
    p4 = {
        "schema_version": "gms-context-record-v1",
        "record_type": "decision",
        "key": "global_memory.sqlite_concurrency",
        "statement": "SQLite database connections in global-memory use WAL mode and get_db_connection with busy_timeout=5000 to handle concurrency.",
        "rationale": "Multiple concurrent processes (nightly launchd daemon, interactive desktop app, CLI invocations, and MCP servers) require non-blocking reads and serialized writes with a 5000ms lock acquisition retry.",
        "implications": [
            "All SQLite accesses must use get_db_connection or set PRAGMA journal_mode=WAL and PRAGMA busy_timeout=5000.",
            "Avoid bare sqlite3.connect without timeout to prevent database locked errors under agent concurrency."
        ],
        "scope": {
            "level": "system",
            "project": "global-memory",
            "workstream": "storage",
            "applies_to": ["tools", "memory_mcp_server", "gms_desktop_api", "dream_cycle"]
        },
        "provenance": {
            "observed_agents": ["Antigravity", "Codex"],
            "extractor": "migration-pass5",
            "source_refs": ["episodic/history/2026-09-08.md#sec-wal-concurrency"],
            "source_hashes": [history_hash],
            "extracted_at": "2026-09-08T18:30:00Z",
            "prompt_version": "migration-v1",
            "provider": "system",
            "model": "deterministic-migrator"
        },
        "evidence": [
            {
                "type": "source_document",
                "ref": "episodic/history/2026-09-08.md#sec-wal-concurrency",
                "excerpt_hash": history_hash
            }
        ],
        "freshness": {
            "effective_at": "2026-09-08T10:15:00Z",
            "review_after": None,
            "status": "fresh",
            "supersedes": ["global_memory_sqlite_concurrency"]
        },
        "review": {
            "status": "proposed",
            "requires_human": True,
            "reasons": ["migrated from legacy flat record; system architecture decision requiring explicit review"]
        },
        "authority": "verified_system_output",
        "verification": "verified"
    }
    candidates.append(p4)

    # 5. retrieval_benchmark_bm25_performance -> fact
    p5 = {
        "schema_version": "gms-context-record-v1",
        "record_type": "fact",
        "key": "retrieval_benchmark.bm25_performance",
        "statement": "Synthetic retrieval benchmark shows lexical BM25 outperforming hybrid and reranked retrieval on short exact queries.",
        "scope": {
            "level": "project",
            "project": "global-memory",
            "workstream": "retrieval",
            "applies_to": ["retrieval-benchmark", "eval_retrieval_benchmark"]
        },
        "provenance": {
            "observed_agents": ["Codex", "Antigravity"],
            "extractor": "migration-pass5",
            "source_refs": ["episodic/history/2026-09-08.md#sec-benchmark-bm25"],
            "source_hashes": [history_hash],
            "extracted_at": "2026-09-08T18:30:00Z",
            "prompt_version": "migration-v1",
            "provider": "system",
            "model": "deterministic-migrator"
        },
        "evidence": [
            {
                "type": "source_document",
                "ref": "episodic/history/2026-09-08.md#sec-benchmark-bm25",
                "excerpt_hash": history_hash
            }
        ],
        "freshness": {
            "effective_at": "2026-09-08T18:01:00Z",
            "review_after": None,
            "status": "fresh",
            "supersedes": ["retrieval_benchmark_bm25_performance"]
        },
        "review": {
            "status": "proposed",
            "requires_human": False,
            "reasons": ["technical benchmark result"]
        },
        "authority": "verified_system_output",
        "verification": "verified"
    }
    candidates.append(p5)

    # 6. retrieval_benchmark_harness_path -> fact
    p6 = {
        "schema_version": "gms-context-record-v1",
        "record_type": "fact",
        "key": "retrieval_benchmark.harness_path",
        "statement": "tools/eval_retrieval_benchmark.py serves as the continuous retrieval benchmark evaluation harness for GMS.",
        "scope": {
            "level": "project",
            "project": "global-memory",
            "workstream": "retrieval",
            "applies_to": ["retrieval-benchmark", "tests"]
        },
        "provenance": {
            "observed_agents": ["Antigravity", "Codex"],
            "extractor": "migration-pass5",
            "source_refs": ["episodic/history/2026-09-08.md#sec-benchmark-harness"],
            "source_hashes": [history_hash],
            "extracted_at": "2026-09-08T18:30:00Z",
            "prompt_version": "migration-v1",
            "provider": "system",
            "model": "deterministic-migrator"
        },
        "evidence": [
            {
                "type": "source_document",
                "ref": "episodic/history/2026-09-08.md#sec-benchmark-harness",
                "excerpt_hash": history_hash
            }
        ],
        "freshness": {
            "effective_at": "2026-09-08T10:20:00Z",
            "review_after": None,
            "status": "fresh",
            "supersedes": ["retrieval_benchmark_harness_path"]
        },
        "review": {
            "status": "proposed",
            "requires_human": False,
            "reasons": ["deterministic harness filepath reference"]
        },
        "authority": "source_document",
        "verification": "verified"
    }
    candidates.append(p6)

    for candidate in candidates:
        start, end = evidence_lines[candidate["key"]]
        if len(history_lines) < end:
            # Missing evidence must remain visibly unverified; migration must
            # not fabricate an anchor, excerpt, or verified status.
            candidate["evidence"] = []
            candidate["provenance"]["source_refs"] = []
            candidate["provenance"]["source_hashes"] = []
            candidate["verification"] = "unverified"
            candidate["review"]["reasons"].append("authoritative source excerpt is unavailable")
            continue
        excerpt = "\n".join(history_lines[start - 1:end])
        source_ref = f"episodic/history/2026-09-08.md#L{start}-L{end}"
        excerpt_hash = _hash_text(excerpt)
        candidate["evidence"] = [{
            "type": candidate["evidence"][0]["type"],
            "ref": source_ref,
            "excerpt_hash": excerpt_hash,
        }]
        candidate["provenance"]["source_refs"] = [source_ref]
        candidate["provenance"]["source_hashes"] = [excerpt_hash]

    return candidates


def run_migration(apply: bool = False, mem_root: Path | None = None) -> dict[str, Any]:
    """
    Run migration on legacy flat records.
    Validates candidates, checks diffs, and if apply=True, stages them in gms_context_candidates.
    """
    root = Path(mem_root).expanduser() if mem_root else DEFAULT_MEM_ROOT
    db_path = root / "gms_trust.sqlite"
    facts_path = root / "semantic" / "facts.json"

    active_facts: dict = {}
    if facts_path.exists():
        try:
            active_facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception:
            active_facts = {}

    candidates = build_migrated_candidates(root)
    results = []
    staged_count = 0
    valid_count = 0
    repaired_candidates: list[str] = []

    for cand in candidates:
        is_valid, norm_payload, err = schemas.validate_context_candidate(cand)
        if not is_valid or norm_payload is None:
            results.append({
                "key": cand.get("key"),
                "status": "validation_failed",
                "error": err,
                "candidate": cand
            })
            continue

        valid_count += 1
        key = norm_payload["key"]
        supersedes_list = norm_payload.get("freshness", {}).get("supersedes", [])
        legacy_key = supersedes_list[0] if supersedes_list else key
        legacy_value = active_facts.get(legacy_key) or active_facts.get(key)

        diff_info = memory_mcp_server.get_candidate_diff(key, norm_payload, db_path=db_path)

        record_summary = {
            "canonical_key": key,
            "record_type": norm_payload["record_type"],
            "statement": norm_payload["statement"],
            "legacy_key": legacy_key,
            "legacy_value": legacy_value,
            "has_existing": diff_info.get("has_existing", False),
            "suggested_action": diff_info.get("suggested_action", "create"),
            "valid": True,
        }

        if apply:
            stage_res = memory_mcp_server.stage_context_candidate(
                candidate=norm_payload,
                extractor_agent="migration-pass5",
                provider="system",
                model="deterministic-migrator",
                prompt_version="migration-v1",
                source_fingerprint=schemas.compute_source_fingerprint(
                    norm_payload.get("provenance", {}).get("source_refs", [])
                ),
                db_path=db_path,
            )
            record_summary["staging_result"] = stage_res
            if stage_res.get("status") in ("staged", "duplicate"):
                staged_count += 1
                # Replace only obsolete, still-unreviewed outputs from this
                # deterministic migrator. Preserve accepted/rejected history.
                current_id = stage_res.get("candidate_id")
                conn = memory_mcp_server.get_db_connection(db_path)
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT candidate_id, content_hash FROM gms_context_candidates
                    WHERE canonical_key = ? AND extractor_agent = 'migration-pass5'
                      AND review_status = 'proposed' AND candidate_id <> ?
                    """,
                    (key, current_id),
                )
                obsolete = cursor.fetchall()
                for old_id, old_hash in obsolete:
                    cursor.execute("DELETE FROM gms_context_candidates WHERE candidate_id = ?", (old_id,))
                    cursor.execute(
                        """
                        INSERT INTO gms_review_audit (
                            candidate_id, canonical_key, action, reviewer_id, review_rationale,
                            original_content_hash, accepted_content_hash, supersedes_claim_id,
                            resulting_claim_id, reviewed_at
                        ) VALUES (?, ?, 'migration_repair', 'migration-pass6', ?, ?, ?, NULL, NULL, ?)
                        """,
                        (
                            old_id, key,
                            "Replaced unreviewed migration candidate whose source locator or excerpt hash was invalid.",
                            old_hash or "unknown", norm_payload.get("content_hash"),
                            datetime.now(timezone.utc).isoformat(),
                        ),
                    )
                    repaired_candidates.append(old_id)
                conn.commit()
                conn.close()

        results.append(record_summary)

    return {
        "status": "success",
        "dry_run": not apply,
        "total_targets": len(LEGACY_TARGET_KEYS),
        "valid_candidates": valid_count,
        "staged_candidates": staged_count if apply else 0,
        "repaired_candidates": repaired_candidates,
        "records": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy flat facts to typed context records.")
    parser.add_argument("--apply", action="store_true", help="Stage candidates in SQLite database.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview candidates without staging (default).")
    parser.add_argument("--root", default=None, help="Custom memory root directory.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    apply = args.apply
    res = run_migration(apply=apply, mem_root=Path(args.root) if args.root else None)

    if args.json or not sys.stdout.isatty():
        print(json.dumps(res, indent=2))
    else:
        mode = "APPLY" if apply else "DRY-RUN PREVIEW"
        print(f"=== Legacy Flat Facts Migration [{mode}] ===")
        print(f"Targets: {res['total_targets']} | Valid: {res['valid_candidates']} | Staged: {res['staged_candidates']}")
        print()
        for r in res["records"]:
            st = r.get("staging_result", {}).get("status", "preview")
            print(f"• [{r['record_type'].upper()}] {r['canonical_key']}")
            print(f"  Statement: {r['statement']}")
            print(f"  Legacy Key: {r['legacy_key']} -> Action: {r['suggested_action']} ({st})")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
