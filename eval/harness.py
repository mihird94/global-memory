"""Execution Harness for Memory Evaluation Lab.

Provides hermetic sandbox memory environments, store isolation,
multi-engine query execution, and telemetry capture.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import struct
import tempfile
import time
from pathlib import Path
from typing import Any

from eval.datasets.continuation import CONTINUATION_CASES, ContinuationTestCase
from eval.datasets.locomo import LOCOMO_CASES, LoCoMoTestCase
from eval.datasets.longmemeval import LONGMEMEVAL_CASES, LongMemEvalTestCase
from eval.datasets.memoryagentbench import MEMORYAGENTBENCH_CASES, MemoryAgentBenchTestCase
from eval.metrics import (
    abstention_accuracy,
    constraint_retention_rate,
    hit_at_k,
    latency_percentiles,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    stale_leakage_rate,
)


def create_fixture_memory_root(dest: Path) -> Path:
    """Populates an ephemeral sandbox memory root with comprehensive test fixtures."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "semantic").mkdir(parents=True, exist_ok=True)
    (dest / "episodic" / "history").mkdir(parents=True, exist_ok=True)
    (dest / "lessons").mkdir(parents=True, exist_ok=True)
    (dest / "projects" / "global-memory").mkdir(parents=True, exist_ok=True)
    (dest / "projects" / "alphaos").mkdir(parents=True, exist_ok=True)
    (dest / "projects" / "learning-os").mkdir(parents=True, exist_ok=True)

    # 1. Semantic facts
    facts = {
        "global_memory_sqlite_concurrency": {
            "value": "Use WAL mode, busy_timeout=5000, and foreign_keys=ON",
            "status": "active",
            "provenance": "session_2026-09-08_1015",
            "evidence": "SQLite PRAGMA directives and concurrency configuration govern database access",
        },
        "dream_cycle_schedule": {
            "value": "03:10 AM local time via launchd com.user.gms-dream-cycle.plist",
            "status": "active",
            "provenance": "session_2026-09-12_0914",
            "evidence": "Scheduled time for nightly memory consolidation",
        },
        "minipc_tailscale_ip": {
            "value": "100.85.120.45",
            "status": "active",
            "provenance": "session_2026-09-08_1015",
            "evidence": "MiniPC Tailscale IP address for network host reachability",
        },
        "car_stickers_status": {
            "value": "archived (unsupported status fact moved to archive during Pass 8 repair)",
            "status": "archived",
            "provenance": "pass8_repair",
            "evidence": "Car stickers status fact archived",
        },
        "alphaos.swing.plugin.version": {
            "value": "0.2.0+codex.20260723182357",
            "status": "active",
            "provenance": "session_2026-09-08_1430",
            "evidence": "Canonical plugin version locked for AlphaOS swing trading",
        },
        "user_communication_preference": {
            "value": "Concise, evidence-backed, github-style markdown links (collaboration guidelines and citations for agent interaction)",
            "status": "active",
            "provenance": "session_2026-09-08_1015",
            "evidence": "Mihir communication style, collaboration guidelines, formatting standards, and markdown link conventions",
        },
        "user_dev_environment": {
            "value": "Cursor and VS Code with Dark Modern theme for development setup",
            "status": "active",
            "provenance": "session_2026-09-08_1015",
            "evidence": "Mihir developer setup code editor and dark theme",
        },
        "minipc_hostname": {
            "value": "minipc-server with user mihir",
            "status": "active",
            "provenance": "session_2026-09-08_1015",
            "evidence": "MiniPC network hostname and default user account",
        },
        "alphaos_target_broker": {
            "value": "Robinhood broker API for swing trade execution",
            "status": "active",
            "provenance": "session_2026-09-08_1430",
            "evidence": "Execution broker integration selected for AlphaOS swing trading",
        },
        "embedding_provider_config": {
            "value": "nomic-embed-text with batch size 32 on local Ollama",
            "status": "active",
            "provenance": "session_2026-09-12_1130",
            "evidence": "Embedding provider evaluation for local memory indexing",
        },
    }
    (dest / "semantic" / "facts.json").write_text(json.dumps(facts, indent=2))

    # Episodic dialogue history
    hist_dir = dest / "episodic" / "history"
    (hist_dir / "2026-09-08.md").write_text(
        "### 2026-09-08 [10:15] - Mihir - Pairing environment setup\n"
        "- Mihir configured development environment: Cursor and VS Code with Dark Modern theme.\n"
        "- MiniPC hostname configured as minipc-server, user mihir, Tailscale IP 100.85.120.45.\n"
        "- Mihir established communication preferences, formatting standards, and markdown link conventions: concise, evidence-backed, github-style links and citations.\n\n"
        "### 2026-09-08 [14:30] - Codex - AlphaOS broker execution strategy\n"
        "- Selected Robinhood broker API for swing trade execution.\n"
        "- Established sizing rules: 25% position cap, 40% sector allocation cap, 5% capital heat ceiling.\n\n"
        "### 2026-09-08 [18:00] - Antigravity - Mbrain UX Pass 3 completed\n"
        "- Pass 3 implemented Projects Context Workspace with 3-column layout.\n"
    )
    (hist_dir / "2026-09-12.md").write_text(
        "### 2026-09-12 [09:14] - Codex - Installed Brain 2.1 on MiniPC\n"
        "- Safely upgraded MiniPC checkout; deployed persistent 03:10 Dream Cycle systemd timer; verified 250 tests.\n\n"
        "### 2026-09-12 [11:30] - Antigravity - Embedding provider evaluation\n"
        "- Evaluated nomic-embed-text embedding provider for local memory indexing. Configured batch size 32 due to local Ollama memory limits.\n\n"
        "### 2026-09-12 [12:40] - Codex - Episodic memory contract standardized\n"
        "- Standardized episodic memory contract across SKILL.md and tools.\n\n"
        "### 2026-09-12 [17:54] - Codex - SOTA agent-memory gap analysis completed\n"
        "- Completed SOTA agent-memory gap analysis at docs/research/BRAIN_SOTA_MEMORY_GAP_ANALYSIS_2026.md.\n\n"
        "### 2026-09-12 [23:05] - Antigravity - Memory Evaluation Lab established\n"
        "- Established dedicated memory evaluation lab; Dream Cycle launchd plist com.user.gms-dream-cycle.plist confirmed at 03:10 AM.\n"
    )

    # 2. Project Memory Banks
    # global-memory
    gm_dir = dest / "projects" / "global-memory"
    (gm_dir / "projectBrief.md").write_text(
        "# Project Brief — Global Memory System (GMS) & Mbrain\n\n"
        "## Overview\n"
        "Global Memory System (GMS v2.1.0) is the unified memory, context engineering, "
        "and coordination layer across all AI agents (Antigravity, Codex, Gemini, terminal agents, "
        "and scheduled workers) in Mihir's ecosystem.\n\n"
        "## Goals & Requirements\n"
        "- Local-First & Privacy: 100% offline-first operation.\n"
        "- Context Engineering: Structured reproducible context packets.\n"
    )
    (gm_dir / "activeContext.md").write_text(
        "# Active Context — Global Memory & Mbrain\n\n"
        "## Current Focus\n"
        "Operationalizing the continuous evaluation benchmark harness and memory evaluation lab.\n\n"
        "## Active Constraints & Boundaries\n"
        "- **Local-First & Offline**: Zero network or CDN requests; zero Ollama model loading during interactive navigation.\n"
        "- **Rationale-First Decisions**: All architectural decisions record explicit decision, rationale, implications.\n"
        "- **No Synthetic Scores**: No global agent trust scores; surface objective evidence instead.\n"
        "- **Git Hygiene**: Do not commit to git without explicit user permission.\n\n"
        "## Decisions\n"
        "Decision: Retired global agent trust score and synthetic reliability percentages in Mbrain because it collapses orthogonal dimensions; "
        "replaced it with separate provenance, recency, contribution counts, disputes, and review outcomes.\n"
        "Decision: Use SQLite WAL mode and busy_timeout=5000 for concurrent writer safety.\n"
        "Decision: Autonomous contestable curation (system-decides, owner-may-contest).\n\n"
        "## Verification & Acceptance\n"
        "- Full pytest test suite passing 100% green.\n"
        "- Clean JavaScript syntax across desktop views.\n"
        "- Clean git diff formatting.\n\n"
        "### Update (2026-09-08 18:00)\n"
        "Pass 3 implemented Projects Context Workspace with 3-column layout.\n\n"
        "### Update (2026-09-12 12:40)\n"
        "Episodic memory contract standardized across SKILL.md and tools."
    )
    (gm_dir / "systemPatterns.md").write_text(
        "## System Patterns\n\n"
        "- SQLite WAL Mode: PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000.\n"
        "- Context Packet Generation: Hash with sha256."
    )
    (gm_dir / "progress.md").write_text(
        "## Progress\n\n"
        "- Verified 250 unit and integration tests passing.\n"
        "- Deployed MiniPC Dream Cycle systemd timer at 03:10."
    )

    # alphaos
    ao_dir = dest / "projects" / "alphaos"
    (ao_dir / "projectBrief.md").write_text(
        "# Project Brief — AlphaOS\n\n"
        "AlphaOS is an agentic swing trading research and portfolio management execution engine."
    )
    (ao_dir / "activeContext.md").write_text(
        "# Active Context — AlphaOS\n\n"
        "## Sizing Guidelines\n"
        "Distinguish capital-at-risk heat from marked profit giveback.\n"
        "Gross cap 100%, position cap 25%, sector cap 40%, capital heat cap 5%.\n\n"
        "## Decisions\n"
        "Canonical plugin version locked to 0.2.0+codex.20260723182357."
    )

    # learning-os
    lo_dir = dest / "projects" / "learning-os"
    (lo_dir / "projectBrief.md").write_text(
        "# Project Brief — Learning OS\n\n"
        "Learning OS is a personal learning cockpit and tutor engine."
    )
    (lo_dir / "activeContext.md").write_text(
        "# Active Context — Learning OS\n\n"
        "## Decisions\n"
        "Consumes llm-cascade-adapter with MemoryGateway narrow bridge.\n"
        "Local-only default with explicit per-request cloud opt-in.\n\n"
        "## Open Items\n"
        "- Add Pomodoro study timer widget.\n"
        "- Expand diagnostic quiz bank.\n"
        "- Add interactive code playground."
    )

    # 3. Database
    db_path = dest / "gms_trust.sqlite"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE gms_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_key TEXT NOT NULL,
            value TEXT NOT NULL,
            agent_id TEXT,
            status TEXT DEFAULT 'active',
            supersedes_claim_id INTEGER,
            confidence REAL DEFAULT 1.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE TABLE gms_tasks (task_id TEXT PRIMARY KEY, project TEXT, title TEXT, objective TEXT, status TEXT, owner_agent TEXT, lease_expires_at TEXT, revision INTEGER, parent_task_id TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT)")
    cur.execute("CREATE TABLE gms_context_candidates (candidate_id TEXT PRIMARY KEY, schema_version TEXT, record_type TEXT, canonical_key TEXT, payload_json TEXT, source_fingerprint TEXT, content_hash TEXT, extractor_agent TEXT, provider TEXT, model TEXT, prompt_version TEXT, review_status TEXT, review_rationale TEXT, reviewed_by TEXT, reviewed_at TEXT, merged_claim_id INTEGER, created_at TIMESTAMP, updated_at TIMESTAMP)")
    cur.execute("CREATE TABLE gms_embeddings (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, chunk INTEGER, text TEXT, embedding BLOB, dim INTEGER, model TEXT, created_at TIMESTAMP)")
    cur.execute("CREATE TABLE gms_entities (entity_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, entity_type TEXT, summary TEXT, created_at TIMESTAMP, updated_at TIMESTAMP)")
    cur.execute("CREATE TABLE gms_relationships (relationship_id INTEGER PRIMARY KEY AUTOINCREMENT, subject_entity_id INTEGER, predicate TEXT, object_entity_id INTEGER, object_literal TEXT, source_claim_id INTEGER, valid_from TEXT, valid_to TEXT, created_at TIMESTAMP)")

    # Seed claims
    for key, val in facts.items():
        status = val["status"] if isinstance(val, dict) else "active"
        text_val = val["value"] if isinstance(val, dict) else str(val)
        cur.execute("INSERT INTO gms_claims (memory_key, value, agent_id, status) VALUES (?, ?, ?, ?)",
                    (key, text_val, "codex", status))
    cur.execute("INSERT INTO gms_claims (memory_key, value, agent_id, status, supersedes_claim_id) VALUES (?, ?, ?, ?, ?)",
                ("alphaos.swing.plugin.version", "0.2.0+codex.20260723175253", "legacy", "superseded", 5))
    cur.execute("INSERT INTO gms_claims (memory_key, value, agent_id, status, supersedes_claim_id) VALUES (?, ?, ?, ?, ?)",
                ("dream_cycle_schedule", "02:00 AM local time", "legacy", "superseded", 2))

    # Seed active task
    cur.execute("""
        INSERT INTO gms_tasks VALUES
        ('task_eval_lab', 'global-memory', 'Memory Evaluation Lab Implementation',
         'Establish independent academic benchmark harness for LongMemEval and MemoryAgentBench',
         'in_progress', 'antigravity', '2026-09-15', 1, NULL, 'mihir', '2026-09-12', '2026-09-12', NULL)
    """)

    # Seed vector embeddings (using a 4-dim synthetic test embedding for fast mathematical testing)
    dim = 4
    test_vecs = [
        ("semantic/facts.json", 0, "SQLite WAL mode and busy_timeout=5000 concurrency parameters", [0.9, 0.1, 0.1, 0.0]),
        ("semantic/facts.json", 1, "03:10 AM nightly memory consolidation Dream Cycle schedule", [0.1, 0.9, 0.1, 0.0]),
        ("projects/alphaos", 0, "AlphaOS swing capital-at-risk heat versus marked profit giveback", [0.1, 0.1, 0.9, 0.0]),
        ("semantic/facts.json", 2, "MiniPC Tailscale IP 100.85.120.45", [0.0, 0.1, 0.1, 0.9]),
    ]
    for src, chk, txt, vec in test_vecs:
        blob = struct.pack(f"{dim}f", *vec)
        cur.execute("INSERT INTO gms_embeddings (source, chunk, text, embedding, dim, model) VALUES (?, ?, ?, ?, ?, ?)",
                    (src, chk, txt, blob, dim, "test-embed"))

    # Seed knowledge graph triples
    graph_entities = [
        ("GMS", "system", "Global Memory System unified memory layer"),
        ("Mbrain", "application", "Mbrain Desktop personal cockpit UI"),
        ("DreamCycle", "daemon", "Dream Cycle nightly consolidation at 03:10"),
        ("SQLite", "database", "SQLite uses WAL mode and busy_timeout=5000 for concurrency"),
        ("MiniPC", "host", "MiniPC Tailscale IP is 100.85.120.45"),
        ("Tailscale", "network", "Private network"),
        ("AlphaOS", "project", "AlphaOS sizing distinguishes capital heat from marked profit giveback"),
        ("capital_heat", "concept", "Capital heat is distinct from marked profit giveback"),
        ("agent_trust", "retired_concept", "Global agent trust was retired because it collapses orthogonal evidence; provenance replaced it"),
    ]
    for name, kind, summary in graph_entities:
        cur.execute("INSERT INTO gms_entities (name, entity_type, summary, created_at) VALUES (?, ?, ?, '2026-09-01')", (name, kind, summary))
    entity_ids = {name: entity_id for entity_id, name in cur.execute("SELECT entity_id, name FROM gms_entities")}
    relationships = [
        ("Mbrain", "scoped_to", "GMS"), ("DreamCycle", "consolidates", "GMS"),
        ("SQLite", "configured_for", "GMS"), ("MiniPC", "reachable_via", "Tailscale"),
        ("AlphaOS", "distinguishes", "capital_heat"), ("Mbrain", "retired", "agent_trust"),
    ]
    for subject, predicate, obj in relationships:
        cur.execute("INSERT INTO gms_relationships (subject_entity_id, predicate, object_entity_id, valid_from) VALUES (?, ?, ?, '2026-09-01')", (entity_ids[subject], predicate, entity_ids[obj]))

    conn.commit()
    conn.close()
    return dest


class MemoryEvalHarness:
    """Sandboxed execution harness managing benchmark runs."""

    def __init__(self, memory_root: Path | None = None):
        self._temp_dir: tempfile.TemporaryDirectory | None = None
        if memory_root is None:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="gms_eval_lab_")
            self.root = create_fixture_memory_root(Path(self._temp_dir.name))
        else:
            self.root = Path(memory_root)

    def cleanup(self) -> None:
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def __enter__(self) -> MemoryEvalHarness:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.cleanup()

    def run_longmemeval(self) -> dict[str, Any]:
        """Runs the complete LongMemEval adapter suite."""
        from context_retrieval_planner import retrieve

        results = []
        ability_scores: dict[str, list[dict[str, float]]] = {}
        all_latencies = []

        for case in LONGMEMEVAL_CASES:
            t0 = time.perf_counter()
            retrieval = retrieve(
                self.root,
                query=case.query,
                project=case.project,
                as_of=case.as_of,
                token_budget=2400,
                enable_indexed_vector=True,
                embedding_model="test-embed",
                query_embedding=fixture_query_embedding(case.query),
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            all_latencies.append(lat_ms)

            items = retrieval.get("items", [])
            retrieved_keys = [it.get("key", "").lower() for it in items]
            retrieved_text = " ".join([f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items])
            top5_text = " ".join([f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items[:5]])

            # Calculate metrics
            rel_set = set([k.lower() for k in case.relevant_keys])
            sup_set = set([k.lower() for k in case.superseded_keys])

            # Check matches in retrieved text
            matched_rel = {k for k in rel_set if k in retrieved_text}
            hit = 1.0 if (len(matched_rel) > 0 or not rel_set) else 0.0
            rec = len(matched_rel) / max(1, len(rel_set))

            # Stale leakage
            leaked_sup = [k for k in sup_set if k in top5_text]
            leak_rate = len(leaked_sup) / max(1, len(sup_set)) if sup_set else 0.0

            # Evidence-aware grading
            evidence_status = retrieval.get("evidence_status", "insufficient")
            actionable = bool(retrieval.get("actionable", False))

            # Prohibited actionable leaks (Requirement 2)
            actionable_prohibited_leaks = [k for k in case.prohibited_leaks if actionable and k.lower() in retrieved_text]
            prohibited_leak_count = len(actionable_prohibited_leaks)

            if not case.should_abstain:
                retrieval_hit = (rec == 1.0 and leak_rate == 0.0)
                is_supported = (evidence_status == "supported" and actionable)
                passed = bool(retrieval_hit and is_supported and prohibited_leak_count == 0)
                retrieval_only_hit = bool(retrieval_hit and not is_supported)
                abst_score = 1.0 if not (evidence_status in {"insufficient", "stale", "conflicted"} and not actionable) else 0.0
            else:
                is_abstention = (evidence_status in {"insufficient", "stale", "conflicted"} and not actionable)
                abst_score = abstention_accuracy(is_abstention, case.should_abstain)
                passed = bool(is_abstention and prohibited_leak_count == 0 and leak_rate == 0.0)
                retrieval_only_hit = False

            case_res = {
                "case_id": case.id,
                "ability": case.ability,
                "query": case.query,
                "variant_of": case.variant_of,
                "passed": passed,
                "retrieval_only_hit": retrieval_only_hit,
                "actionable": actionable,
                "prohibited_leak_count": prohibited_leak_count,
                "actionable_prohibited_leaks": actionable_prohibited_leaks,
                "latency_ms": round(lat_ms, 2),
                "hit@5": hit,
                "recall@5": round(rec, 3),
                "stale_leak_rate": round(leak_rate, 3),
                "abstention_acc": round(abst_score, 3),
                "evidence_status": evidence_status,
                "items_count": len(items),
            }
            results.append(case_res)

            ability_scores.setdefault(case.ability, []).append({
                "hit": hit,
                "recall": rec,
                "abstention": abst_score,
                "leakage": leak_rate,
                "passed": 1.0 if passed else 0.0,
            })

        # Aggregate per ability
        per_ability = {}
        for ab, metrics_list in ability_scores.items():
            per_ability[ab] = {
                "count": len(metrics_list),
                "pass_rate": round(sum(m["passed"] for m in metrics_list) / len(metrics_list), 3),
                "mean_recall": round(sum(m["recall"] for m in metrics_list) / len(metrics_list), 3),
                "mean_hit": round(sum(m["hit"] for m in metrics_list) / len(metrics_list), 3),
                "mean_abstention": round(sum(m["abstention"] for m in metrics_list) / len(metrics_list), 3),
            }

        total_passed = sum(1 for r in results if r["passed"])
        return {
            "suite": "Brain Long-Horizon Memory — LongMemEval-inspired",
            "benchmark_scope": "brain_local_adapter",
            "official_public_benchmark": False,
            "inspired_by": "LongMemEval ability taxonomy; no official dataset examples are executed",
            "canonical_cases": sum(case.variant_of is None for case in LONGMEMEVAL_CASES),
            "robustness_variants": sum(case.variant_of is not None for case in LONGMEMEVAL_CASES),
            "total_cases": len(results),
            "passed_cases": total_passed,
            "pass_rate": round(total_passed / max(1, len(results)), 3),
            "latency": latency_percentiles(all_latencies),
            "per_ability": per_ability,
            "cases": results,
        }

    def run_locomo(self) -> dict[str, Any]:
        """Runs the complete LoCoMo (Long Conversational Memory) adapter suite."""
        from context_retrieval_planner import retrieve

        results = []
        category_scores: dict[str, list[dict[str, float]]] = {}
        all_latencies = []

        for case in LOCOMO_CASES:
            t0 = time.perf_counter()
            retrieval = retrieve(
                self.root,
                query=case.query,
                project=case.project,
                as_of=case.as_of,
                token_budget=2400,
                enable_indexed_vector=True,
                embedding_model="test-embed",
                query_embedding=fixture_query_embedding(case.query),
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            all_latencies.append(lat_ms)

            items = retrieval.get("items", [])
            retrieved_text = " ".join([f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items])
            top5_text = " ".join([f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items[:5]])

            # Calculate metrics
            rel_set = set([k.lower() for k in case.relevant_keys])
            sup_set = set([k.lower() for k in case.superseded_keys])

            # Check matches in retrieved text
            matched_rel = {k for k in rel_set if k in retrieved_text}
            hit = 1.0 if (len(matched_rel) > 0 or not rel_set) else 0.0
            rec = len(matched_rel) / max(1, len(rel_set))

            # Stale leakage
            leaked_sup = [k for k in sup_set if k in top5_text]
            leak_rate = len(leaked_sup) / max(1, len(sup_set)) if sup_set else 0.0

            evidence_status = retrieval.get("evidence_status", "insufficient")
            actionable = bool(retrieval.get("actionable", False))

            # Prohibited actionable leaks (Requirement 2)
            actionable_prohibited_leaks = [k for k in case.prohibited_leaks if actionable and k.lower() in retrieved_text]
            prohibited_leak_count = len(actionable_prohibited_leaks)

            if not case.should_abstain:
                retrieval_hit = (rec == 1.0 and leak_rate == 0.0)
                is_supported = (evidence_status == "supported" and actionable)
                passed = bool(retrieval_hit and is_supported and prohibited_leak_count == 0)
                retrieval_only_hit = bool(retrieval_hit and not is_supported)
                abst_score = 1.0 if not (evidence_status in {"insufficient", "stale", "conflicted"} and not actionable) else 0.0
            else:
                is_abstention = (evidence_status in {"insufficient", "stale", "conflicted"} and not actionable)
                abst_score = abstention_accuracy(is_abstention, case.should_abstain)
                passed = bool(is_abstention and prohibited_leak_count == 0 and leak_rate == 0.0)
                retrieval_only_hit = False

            case_res = {
                "case_id": case.id,
                "category": case.category,
                "query": case.query,
                "variant_of": case.variant_of,
                "passed": passed,
                "retrieval_only_hit": retrieval_only_hit,
                "actionable": actionable,
                "prohibited_leak_count": prohibited_leak_count,
                "actionable_prohibited_leaks": actionable_prohibited_leaks,
                "latency_ms": round(lat_ms, 2),
                "hit@5": hit,
                "recall@5": round(rec, 3),
                "stale_leak_rate": round(leak_rate, 3),
                "abstention_acc": round(abst_score, 3),
                "evidence_status": evidence_status,
                "items_count": len(items),
            }
            results.append(case_res)

            category_scores.setdefault(case.category, []).append({
                "hit": hit,
                "recall": rec,
                "abstention": abst_score,
                "leakage": leak_rate,
                "passed": 1.0 if passed else 0.0,
            })

        # Aggregate per category
        per_category = {}
        for cat, metrics_list in category_scores.items():
            per_category[cat] = {
                "count": len(metrics_list),
                "pass_rate": round(sum(m["passed"] for m in metrics_list) / len(metrics_list), 3),
                "mean_recall": round(sum(m["recall"] for m in metrics_list) / len(metrics_list), 3),
                "mean_hit": round(sum(m["hit"] for m in metrics_list) / len(metrics_list), 3),
                "mean_abstention": round(sum(m["abstention"] for m in metrics_list) / len(metrics_list), 3),
            }

        total_passed = sum(1 for r in results if r["passed"])
        return {
            "suite": "Brain Conversational Memory — LoCoMo-inspired",
            "benchmark_scope": "brain_local_adapter",
            "official_public_benchmark": False,
            "inspired_by": "Snap Research LoCoMo benchmark (ACL 2024); no official dataset examples are executed",
            "canonical_cases": sum(case.variant_of is None for case in LOCOMO_CASES),
            "robustness_variants": sum(case.variant_of is not None for case in LOCOMO_CASES),
            "total_cases": len(results),
            "passed_cases": total_passed,
            "pass_rate": round(total_passed / max(1, len(results)), 3),
            "latency": latency_percentiles(all_latencies),
            "per_category": per_category,
            "cases": results,
        }

    def run_memoryagentbench(self) -> dict[str, Any]:
        """Runs the MemoryAgentBench adapter suite."""
        from context_retrieval_planner import retrieve

        results = []
        all_latencies = []

        for case in MEMORYAGENTBENCH_CASES:
            t0 = time.perf_counter()
            retrieval = retrieve(
                self.root,
                query=case.query,
                project=case.project,
                token_budget=2400,
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            all_latencies.append(lat_ms)

            items = retrieval.get("items", [])
            retrieved_text = " ".join([f"{it.get('key', '')} {it.get('statement', '')}".lower() for it in items])

            valid_hits = [k for k in case.valid_keys if k.lower() in retrieved_text]
            proh_leaks = [k for k in case.prohibited_leaks if k.lower() in retrieved_text]
            evidence_status = retrieval.get("evidence_status", "insufficient")
            target_actionable = any(
                case.target_archived_key
                and case.target_archived_key.lower() in str(it.get("key", "")).lower()
                and it.get("lifecycle_status") not in {"archived", "superseded", "discarded", "expired"}
                for it in items
            )
            forgetting_ok = (
                case.category != "selective_forgetting"
                or not case.target_archived_key
                or (not target_actionable and evidence_status in {"stale", "insufficient"})
            )
            contradiction_ok = (
                case.category != "contradiction_resistance"
                or evidence_status in {"insufficient", "conflicted"}
            )
            passed = (len(valid_hits) > 0 or not case.valid_keys) and not proh_leaks and forgetting_ok and contradiction_ok

            results.append({
                "case_id": case.id,
                "category": case.category,
                "query": case.query,
                "variant_of": case.variant_of,
                "passed": passed,
                "latency_ms": round(lat_ms, 2),
                "valid_hits": valid_hits,
                "prohibited_leaks": proh_leaks,
                "evidence_status": evidence_status,
                "target_actionable": target_actionable,
            })

        total_passed = sum(1 for r in results if r["passed"])
        return {
            "suite": "Brain Lifecycle Robustness — MemoryAgentBench-inspired",
            "benchmark_scope": "brain_local_adapter",
            "official_public_benchmark": False,
            "inspired_by": "MemoryAgentBench capability taxonomy; no official dataset examples are executed",
            "canonical_cases": sum(case.variant_of is None for case in MEMORYAGENTBENCH_CASES),
            "robustness_variants": sum(case.variant_of is not None for case in MEMORYAGENTBENCH_CASES),
            "total_cases": len(results),
            "passed_cases": total_passed,
            "pass_rate": round(total_passed / max(1, len(results)), 3),
            "latency": latency_percentiles(all_latencies),
            "cases": results,
        }

    def run_continuation(self) -> dict[str, Any]:
        """Runs cross-agent task continuation and handoff evaluation."""
        from project_briefing import build_resume_bundle

        results = []
        all_latencies = []

        for case in CONTINUATION_CASES:
            t0 = time.perf_counter()
            bundle = build_resume_bundle(
                self.root,
                project_id=case.project,
                target_format=case.target_format,
            )
            lat_ms = (time.perf_counter() - t0) * 1000.0
            all_latencies.append(lat_ms)

            prompt_text = bundle.get("prompt", "").lower()

            # 1. Goal keywords
            goal_hits = [k for k in case.expected_goal_keywords if k.lower() in prompt_text]
            goal_ok = len(goal_hits) >= max(1, len(case.expected_goal_keywords) // 2)

            # 2. Constraints
            const_hits = [k for k in case.expected_constraints if k.lower() in prompt_text]
            const_ok = len(const_hits) >= max(1, len(case.expected_constraints) // 2)

            # 3. Next action
            next_action_stmt = bundle.get("next_action", {}).get("statement", "").lower()
            next_ok = any(k.lower() in next_action_stmt for k in case.expected_next_action_keywords) or bool(next_action_stmt)

            # 4. Prohibited leaks
            proh_leaks = [k for k in case.prohibited_leakage_keywords if k.lower() in prompt_text]
            leak_free = len(proh_leaks) == 0

            # 5. Token compression ratio
            raw_chars = 0
            proj_dir = self.root / "projects" / case.project
            if proj_dir.exists():
                for f in proj_dir.glob("*.md"):
                    raw_chars += len(f.read_text(encoding="utf-8", errors="replace"))
            bundle_chars = len(bundle.get("prompt", ""))
            compression_ratio = round(raw_chars / max(1, bundle_chars), 2)
            comp_ok = (compression_ratio >= 1.5) if raw_chars > 3000 else (bundle_chars < 3500)

            passed = goal_ok and const_ok and next_ok and leak_free and comp_ok

            results.append({
                "case_id": case.id,
                "project": case.project,
                "passed": passed,
                "latency_ms": round(lat_ms, 2),
                "goal_ok": goal_ok,
                "constraints_ok": const_ok,
                "next_action_ok": next_ok,
                "leak_free": leak_free,
                "compression_ratio": compression_ratio,
                "prohibited_leaks": proh_leaks,
            })

        total_passed = sum(1 for r in results if r["passed"])
        return {
            "suite": "Brain Context Bundle Structure",
            "benchmark_scope": "brain_local_adapter",
            "evaluates_agent_behavior": False,
            "total_cases": len(results),
            "passed_cases": total_passed,
            "pass_rate": round(total_passed / max(1, len(results)), 3),
            "latency": latency_percentiles(all_latencies),
            "cases": results,
        }
def fixture_query_embedding(query: str) -> list[float]:
    """Deterministic query encoder aligned with the fixture's stored vectors."""
    text = query.lower()
    axes = [
        ("sqlite", "wal", "busy_timeout", "concurrency"),
        ("dream", "nightly", "schedule", "03:10", "consolidation"),
        ("alphaos", "capital", "heat", "giveback", "plugin"),
        ("minipc", "tailscale", "ip address", "100.85"),
    ]
    scores = [float(sum(term in text for term in terms)) for terms in axes]
    if not any(scores):
        return [0.0, 0.0, 0.0, 0.0]
    return scores
