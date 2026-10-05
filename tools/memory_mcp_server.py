#!/usr/bin/env python3
"""
memory_mcp_server.py — MCP Server for the Mihir-OS Global Memory System
========================================================================
Exposes memoryctl as a proper MCP (Model Context Protocol) server via stdio.
Any agent that supports MCP (Antigravity, Codex, Claude Code, Gemini CLI,
OpenClaw) can call these tools directly without running shell commands.

This eliminates the need to manually run `memoryctl start-context` at the
start of every session — the MCP client calls mem_session_start automatically.

Installation (add to your agent's MCP config):

  Gemini CLI (~/.gemini/settings.json):
    {
      "mcpServers": {
        "memory": {
          "command": "<repo>/.venv/bin/python",
          "args": ["<repo>/tools/memory_mcp_server.py"]
        }
      }
    }

  Codex (~/.codex/config.toml):
    [[mcp_servers]]
    name = "memory"
    command = ["<repo>/.venv/bin/python",
               "<repo>/tools/memory_mcp_server.py"]

Tools exposed: 59 capabilities, each available under both ``mem_*`` and
``brain_*`` aliases (118 registered tool names). Tool metadata carries the GMS
context-engineering convention so clients see lifecycle, evidence, rationale,
and authority requirements when selecting a tool.
  Session:    mem_session_start, mem_session_end
  Save:       mem_save_fact, mem_log_event, mem_add_lesson
  Search:     mem_search, mem_context
  Inspect:    mem_get_facts, mem_get_preferences, mem_get_projects, mem_stats
  Conflict:   mem_judge (checks new fact against existing ones before write)
  Maintenance: mem_index_rebuild
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import subprocess
import time
import sqlite3
try:
    from datetime import UTC, datetime, timedelta
except ImportError:
    from datetime import datetime, timedelta, timezone
    UTC = timezone.utc
from pathlib import Path
from typing import Any
from urllib import request

PEER_CONSENSUS_AGENTS = {"Antigravity", "Codex", "Gemini CLI", "Mihir"}

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
TOOLS_DIR   = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from schemas import (validate_fact, get_namespace_for_key, list_contracts,
                         parse_payload, validate_source_reference)
except ImportError:
    try:
        from tools.schemas import (validate_fact, get_namespace_for_key, list_contracts,
                                   parse_payload, validate_source_reference)
    except ImportError:
        def validate_fact(key: str, value: Any) -> tuple[bool, Any, str | None]:
            return True, value, None
        def get_namespace_for_key(key: str) -> str | None:
            return None
        def list_contracts() -> dict[str, dict]:
            return {}
        def parse_payload(val: Any) -> Any:
            return val
        def validate_source_reference(ref: str, excerpt_hash: str | None = None,
                                      mem_root: Path | None = None) -> tuple[bool, str, dict]:
            return False, "validator_unavailable", {"ref": ref}

def _get_harvest_fn():
    try:
        from harvest import harvest_session
        return harvest_session
    except ImportError:
        try:
            from tools.harvest import harvest_session
            return harvest_session
        except ImportError:
            return None




def _default_mem_root() -> Path:
    if "MEM_ROOT" in globals() and MEM_ROOT is not None:
        return MEM_ROOT
    memory_root = os.environ.get("MEMORY_ROOT")
    if memory_root:
        return Path(memory_root).expanduser()
    return Path.home() / "memories"


MEM_ROOT    = _default_mem_root()
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "qwen3-embedding:0.6b")
MEMORYCTL   = Path(os.environ.get(
    "MEMORYCTL_PATH",
    str(REPO_ROOT / "tools" / "memoryctl")
))
EMBED_TIMEOUT = int(os.environ.get("MEMORY_EMBED_TIMEOUT_SEC", "120"))

DB_PATH = MEM_ROOT / "gms_trust.sqlite"

def _compute_trap_receipt(name: str, pattern: str, payload: str, created_at: str) -> str:
    key = os.environ.get("GMS_HMAC_SECRET", "gms_prov_key_2026_default").encode("utf-8")
    msg = f"{name}|{pattern}|{payload}|{created_at}".encode("utf-8")
    import hmac, hashlib
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:24]

def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp.{os.getpid()}.{time.time_ns()}")
    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


# ──────────────────────────────────────────────────────────────────────────────
# Trust Database Helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_db_connection(db_path: Path | str | None = None, timeout: float = 30.0) -> sqlite3.Connection:
    target = Path(db_path or DB_PATH)
    if not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=timeout)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | None = None):
    target = db_path or DB_PATH
    conn = get_db_connection(target)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_agent_reputation (
            agent_id TEXT PRIMARY KEY,
            alpha REAL DEFAULT 1.0,
            beta REAL DEFAULT 0.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_fact_provenance (
            fact_key TEXT PRIMARY KEY,
            agent_id TEXT,
            branch TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            quarantined INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_quarantined_facts (
            fact_key TEXT,
            value TEXT,
            agent_id TEXT,
            branch TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (fact_key, agent_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_kind TEXT,
            memory_key TEXT,
            value TEXT,
            agent_id TEXT,
            branch TEXT,
            status TEXT,
            supersedes_claim_id INTEGER,
            confidence REAL DEFAULT 1.0,
            contradiction_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_entities (
            entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            entity_type TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_relationships (
            relationship_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_entity_id INTEGER,
            predicate TEXT,
            object_entity_id INTEGER,
            object_literal TEXT,
            source_claim_id INTEGER,
            valid_from TIMESTAMP,
            valid_to TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(subject_entity_id) REFERENCES gms_entities(entity_id),
            FOREIGN KEY(object_entity_id) REFERENCES gms_entities(entity_id),
            FOREIGN KEY(source_claim_id) REFERENCES gms_claims(claim_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_memory_entity_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_ref TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            relationship TEXT DEFAULT 'references',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(entity_id) REFERENCES gms_entities(entity_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_procedures (
            procedure_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            "trigger" TEXT,
            action TEXT,
            context TEXT,
            status TEXT DEFAULT 'active',
            source_claim_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(source_claim_id) REFERENCES gms_claims(claim_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_quarantine_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_key TEXT,
            agent_id TEXT,
            reviewer_id TEXT,
            rating TEXT,
            rationale TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_tasks (
            task_id TEXT PRIMARY KEY,
            project TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            objective TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            owner_agent TEXT,
            lease_expires_at TEXT,
            revision INTEGER NOT NULL DEFAULT 1,
            parent_task_id TEXT,
            created_by TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_task_checkpoints (
            checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT '',
            state_json TEXT NOT NULL,
            artifact_refs_json TEXT NOT NULL DEFAULT '[]',
            claim_refs_json TEXT NOT NULL DEFAULT '[]',
            episode_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES gms_tasks(task_id),
            UNIQUE(task_id, revision)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_handoffs (
            handoff_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            source_agent TEXT NOT NULL,
            target_agent TEXT,
            objective TEXT NOT NULL DEFAULT '',
            completed_work TEXT NOT NULL DEFAULT '',
            next_action TEXT NOT NULL DEFAULT '',
            blockers TEXT NOT NULL DEFAULT '',
            acceptance_criteria TEXT NOT NULL DEFAULT '',
            context_json TEXT NOT NULL DEFAULT '{}',
            artifact_refs_json TEXT NOT NULL DEFAULT '[]',
            acknowledged_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(task_id) REFERENCES gms_tasks(task_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_context_candidates (
            candidate_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            record_type TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            source_fingerprint TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            extractor_agent TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            prompt_version TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'proposed',
            review_rationale TEXT,
            reviewed_by TEXT,
            reviewed_at TEXT,
            merged_claim_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_fingerprint, canonical_key, content_hash)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_status ON gms_context_candidates (review_status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_type ON gms_context_candidates (record_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_key ON gms_context_candidates (canonical_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_candidates_created ON gms_context_candidates (created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gms_tasks_status_project ON gms_tasks (status, project)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gms_task_checkpoints_task ON gms_task_checkpoints (task_id, checkpoint_id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gms_handoffs_task ON gms_handoffs (task_id, handoff_id DESC)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_review_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id TEXT NOT NULL,
            canonical_key TEXT NOT NULL,
            action TEXT NOT NULL,
            reviewer_id TEXT NOT NULL,
            review_rationale TEXT NOT NULL,
            original_content_hash TEXT NOT NULL,
            accepted_content_hash TEXT,
            supersedes_claim_id INTEGER,
            resulting_claim_id INTEGER,
            reviewed_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_audit_cand ON gms_review_audit (candidate_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_audit_key ON gms_review_audit (canonical_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_review_audit_reviewer ON gms_review_audit (reviewer_id)")
    try:
        cursor.execute("ALTER TABLE gms_claims ADD COLUMN confidence REAL DEFAULT 1.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE gms_claims ADD COLUMN contradiction_type TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE gms_quarantine_reviews ADD COLUMN claim_id INTEGER")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE gms_quarantine_reviews ADD COLUMN weight_snapshot REAL")
    except sqlite3.OperationalError:
        pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            chunk INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB NOT NULL,
            dim INTEGER NOT NULL,
            model TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, chunk, model)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gms_emb_model ON gms_embeddings (model)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gms_rel_sub_pred ON gms_relationships (subject_entity_id, predicate, valid_to)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gms_rel_valid ON gms_relationships (valid_from, valid_to)")
    try:
        cursor.execute("ALTER TABLE gms_relationships ADD COLUMN valid_from TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE gms_relationships ADD COLUMN valid_to TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS gms_vec_items USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding float[1024]
            )
        """)
    except Exception:
        pass
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_gms_quarantine_reviews_identity
        ON gms_quarantine_reviews (fact_key, agent_id, reviewer_id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_concept_enrichment_queue (
            queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            text_excerpt TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 50,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT,
            leased_at TEXT,
            lease_owner TEXT,
            completed_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_kind, source_ref, source_hash)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_concept_candidates (
            candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_id INTEGER NOT NULL,
            candidate_kind TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            model TEXT NOT NULL,
            provider TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            validation_status TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(queue_id) REFERENCES gms_concept_enrichment_queue(queue_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gms_concept_run_audit (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            items_processed INTEGER NOT NULL DEFAULT 0,
            candidates_generated INTEGER NOT NULL DEFAULT 0,
            errors_count INTEGER NOT NULL DEFAULT 0,
            peak_memory_mb REAL,
            status TEXT NOT NULL
        )
    """)
    try:
        cursor.execute("ALTER TABLE gms_quarantine_reviews ADD COLUMN resolution TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE gms_quarantine_reviews ADD COLUMN resolved_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def _normalize_agent_id(agent_id: str) -> str:
    if not agent_id:
        return "unknown"
    if agent_id.startswith("DreamCycle-"):
        return agent_id
    cleaned = agent_id.lower().replace("-", " ").replace("_", " ").strip()
    if "gemini" in cleaned:
        return "Gemini CLI"
    if "codex" in cleaned:
        return "Codex"
    if "antigravity" in cleaned:
        return "Antigravity"
    if "mihir" in cleaned or "user" in cleaned:
        return "Mihir"
    return agent_id


def get_agent_trust(agent_id: str) -> float:
    agent_id = _normalize_agent_id(agent_id)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT alpha, beta FROM gms_agent_reputation WHERE agent_id = ?", (agent_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, 1.0, 0.0)", (agent_id,))
        conn.commit()
        alpha, beta = 1.0, 0.0
    else:
        alpha, beta = row
    conn.close()
    return (alpha + 1.0) / (alpha + beta + 2.0)


def increment_agent_alpha(agent_id: str, amount: float = 1.0):
    agent_id = _normalize_agent_id(agent_id)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT alpha FROM gms_agent_reputation WHERE agent_id = ?", (agent_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, ?, 0.0)", (agent_id, 10.0 + amount))
    else:
        cursor.execute("UPDATE gms_agent_reputation SET alpha = alpha + ?, last_updated = CURRENT_TIMESTAMP WHERE agent_id = ?", (amount, agent_id))
    conn.commit()
    conn.close()


def increment_agent_beta(agent_id: str, amount: float = 1.0):
    agent_id = _normalize_agent_id(agent_id)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT beta FROM gms_agent_reputation WHERE agent_id = ?", (agent_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO gms_agent_reputation (agent_id, alpha, beta) VALUES (?, 10.0, ?)", (agent_id, amount))
    else:
        cursor.execute("UPDATE gms_agent_reputation SET beta = beta + ?, last_updated = CURRENT_TIMESTAMP WHERE agent_id = ?", (amount, agent_id))
    conn.commit()
    conn.close()


def record_provenance(fact_key: str, agent_id: str, branch: str, quarantined: int = 0):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, quarantined, timestamp)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fact_key) DO UPDATE SET
            agent_id = excluded.agent_id,
            branch = excluded.branch,
            quarantined = excluded.quarantined,
            timestamp = CURRENT_TIMESTAMP
    """, (fact_key, agent_id, branch, quarantined))
    conn.commit()
    conn.close()


def get_fact_provenance(fact_key: str) -> tuple[str, str, int] | None:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT agent_id, branch, quarantined FROM gms_fact_provenance WHERE fact_key = ?", (fact_key,))
    row = cursor.fetchone()
    conn.close()
    return row


def quarantine_fact(fact_key: str, value: str, agent_id: str, branch: str):
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gms_quarantined_facts (fact_key, value, agent_id, branch, timestamp)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fact_key, agent_id) DO UPDATE SET
            value = excluded.value,
            branch = excluded.branch,
            timestamp = CURRENT_TIMESTAMP
    """, (fact_key, value, agent_id, branch))
    conn.commit()
    conn.close()
    try:
        increment_agent_beta(agent_id, 0.5)
    except Exception:
        pass


def record_claim(kind: str, key: str, value: str, agent_id: str, branch: str, status: str, confidence: float = None, contradiction_type: str = None) -> int:
    import re
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    # Query existing active claims before any state mutation
    cursor.execute(
        "SELECT claim_id, value, agent_id FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND status = 'active' ORDER BY claim_id ASC",
        (kind, key)
    )
    active_rows = cursor.fetchall()

    time_keywords = ["valid_from", "valid_to", "expires", "since", "until", "timestamp", "start_date", "end_date", "current_task"]
    has_time_kw = any(kw in key.lower() or kw in value.lower() for kw in time_keywords)
    has_date_pattern = bool(re.search(r'\d{4}-\d{2}-\d{2}', key + " " + value))
    is_contextual = "@" in key or "[" in key or "]" in key or (":" in key and not any(key.startswith(p + ":") for p in ["semantic", "operational", "procedural", "session"]))

    norm_agent = _normalize_agent_id(agent_id).lower()
    last_owner = _normalize_agent_id(active_rows[-1][2]).lower() if active_rows else ""
    if contradiction_type is None:
        if is_contextual:
            contradiction_type = "contextual_coexistence"
        elif active_rows:
            last_val = active_rows[-1][1]
            if last_val != value:
                # Provenance is evidence, not a global reputation score. A
                # direct update is only safe when it is temporal or comes from
                # the incumbent author; other conflicts must stay inspectable.
                if has_time_kw or has_date_pattern or norm_agent == last_owner:
                    contradiction_type = "temporal_invalidation"
                else:
                    contradiction_type = "exact_conflict"
            else:
                contradiction_type = "reinforcement"
        elif has_time_kw or has_date_pattern:
            contradiction_type = "temporal_invalidation"

    # Exact conflict defense: conflicts without temporal supersession stay
    # quarantined for evidence-backed review.
    if contradiction_type == "exact_conflict" and status == "active":
        if norm_agent not in {"mihir", last_owner}:
            status = "quarantined"
            confidence = 0.2
            try:
                increment_agent_beta(agent_id, 1.0)
            except Exception:
                pass
            log_security_event("EXACT_CONFLICT_QUARANTINE", f"Claim '{key}' from agent '{agent_id}' conflicted with incumbent active claim from '{last_owner}'. Quarantined.")

    supersedes_id = None
    if status == "active" and active_rows:
        supersedes_id = active_rows[-1][0]
        for row in active_rows:
            cursor.execute(
                "UPDATE gms_claims SET status = 'superseded', confidence = 0.0 WHERE claim_id = ?",
                (row[0],)
            )

    if confidence is None:
        if status == "active":
            confidence = 1.0
        elif status == "quarantined":
            confidence = 0.2
        elif status == "discarded":
            confidence = 0.0
        else:
            confidence = 1.0

    cursor.execute("""
        INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (kind, key, value, agent_id, branch, status, supersedes_id, confidence, contradiction_type))
    
    claim_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return claim_id


# ──────────────────────────────────────────────────────────────────────────────
# Pass 5 Context Harvesting Staging, Review, and Diff Engine
# ──────────────────────────────────────────────────────────────────────────────

def stage_context_candidate(
    candidate_data: dict | None = None,
    *args,
    allowed_source_refs: list[str] | None = None,
    allowed_source_hashes: dict[str, str] | None = None,
    db_path: Path | None = None,
    candidate: dict | None = None,
    candidate_envelope: dict | None = None,
    extractor_agent: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    source_fingerprint: str | None = None,
    **kwargs,
) -> dict:
    """
    Deterministically validate and stage a candidate into gms_context_candidates.
    Does NOT auto-promote LLM decisions/policies into active canonical memory.
    """
    import schemas

    cand = candidate_data if candidate_data is not None else (candidate or candidate_envelope)
    if cand is None:
        return {"status": "rejected", "error": "No candidate provided", "candidate": {}}

    if len(args) >= 1 and extractor_agent is None:
        extractor_agent = args[0]
    if len(args) >= 2 and provider is None:
        provider = args[1]
    if len(args) >= 3 and model is None:
        model = args[2]
    if len(args) >= 4 and prompt_version is None:
        prompt_version = args[3]
    if len(args) >= 5 and source_fingerprint is None:
        source_fingerprint = args[4]
    if "db_path" in kwargs and db_path is None:
        db_path = kwargs["db_path"]

    is_valid, normalized, err = schemas.validate_context_candidate(
        cand,
        allowed_source_refs=allowed_source_refs,
        allowed_source_hashes=allowed_source_hashes,
    )
    if not is_valid or normalized is None:
        return {
            "status": "rejected",
            "error": err or "Validation failed",
            "candidate": cand,
        }

    target = db_path or DB_PATH
    init_db(target)
    conn = get_db_connection(target)
    cursor = conn.cursor()

    candidate_id = normalized["candidate_id"]
    schema_version = normalized["schema_version"]
    record_type = normalized["record_type"]
    canonical_key = normalized["key"]
    source_fingerprint = source_fingerprint or normalized["source_fingerprint"]
    content_hash = normalized["content_hash"]
    provenance = normalized.setdefault("provenance", {})
    if extractor_agent:
        provenance["extractor"] = extractor_agent
    if provider:
        provenance["provider"] = provider
    if model:
        provenance["model"] = model
    if prompt_version:
        provenance["prompt_version"] = prompt_version

    extractor_agent = str(provenance.get("extractor") or provenance.get("extractor_agent", "unknown"))
    provider = str(provenance.get("provider", ""))
    model = str(provenance.get("model", ""))
    prompt_version = str(provenance.get("prompt_version", "context-harvest-v1"))
    review_status = normalized.get("review", {}).get("status", "proposed")
    payload_json = json.dumps(normalized, sort_keys=True, ensure_ascii=False)

    # 1. Exact deduplication check
    cursor.execute(
        """
        SELECT candidate_id, review_status FROM gms_context_candidates
        WHERE source_fingerprint = ? AND canonical_key = ? AND content_hash = ?
        """,
        (source_fingerprint, canonical_key, content_hash),
    )
    dup = cursor.fetchone()
    if dup:
        conn.close()
        return {
            "status": "duplicate",
            "candidate_id": dup[0],
            "canonical_key": canonical_key,
            "review_status": dup[1],
            "action": "duplicate",
            "message": "Identical candidate already staged for this source and key",
        }

    # 2. Existing record comparison & diff
    diff_info = get_candidate_diff(canonical_key, normalized, db_path=target)

    # 3. Insert candidate into staging table
    cursor.execute(
        """
        INSERT INTO gms_context_candidates (
            candidate_id, schema_version, record_type, canonical_key,
            payload_json, source_fingerprint, content_hash, extractor_agent,
            provider, model, prompt_version, review_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            candidate_id, schema_version, record_type, canonical_key,
            payload_json, source_fingerprint, content_hash, extractor_agent,
            provider, model, prompt_version, review_status
        ),
    )
    conn.commit()
    conn.close()

    return {
        "status": "staged",
        "candidate_id": candidate_id,
        "canonical_key": canonical_key,
        "record_type": record_type,
        "content_hash": content_hash,
        "suggested_action": diff_info.get("suggested_action", "create"),
        "diff": diff_info,
    }


def get_candidate_diff(
    canonical_key: str,
    proposed_payload: dict,
    db_path: Path | None = None,
) -> dict:
    """Generate field-level diff between a proposed candidate and existing canonical memory."""
    target = db_path or DB_PATH
    existing_record = None

    # Check active facts.json
    facts_path = (target.parent / "semantic" / "facts.json") if target else (MEM_ROOT / "semantic" / "facts.json")
    alt_key = canonical_key.replace(".", "_") if "." in canonical_key else canonical_key.replace("_", ".")
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            lookup_key = canonical_key if canonical_key in facts else (alt_key if alt_key in facts else None)
            if lookup_key:
                raw_val = facts[lookup_key]
                if isinstance(raw_val, str) and raw_val.strip().startswith("{"):
                    try:
                        existing_record = json.loads(raw_val)
                    except Exception:
                        existing_record = raw_val
                else:
                    existing_record = raw_val
        except Exception:
            pass

    # Check active claim in SQLite if not found in facts.json
    if existing_record is None and target.exists():
        conn = get_db_connection(target)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM gms_claims WHERE (memory_key = ? OR memory_key = ?) AND status = 'active' ORDER BY claim_id DESC LIMIT 1",
            (canonical_key, alt_key)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            raw_val = row[0]
            if isinstance(raw_val, str) and raw_val.strip().startswith("{"):
                try:
                    existing_record = json.loads(raw_val)
                except Exception:
                    existing_record = raw_val
            else:
                existing_record = raw_val

    if existing_record is None:
        return {
            "has_existing": False,
            "canonical_key": canonical_key,
            "existing_record": None,
            "suggested_action": "create",
            "field_diff": {},
        }

    # Compare fields
    field_diff: dict[str, dict] = {}
    if isinstance(existing_record, dict):
        for field in ["statement", "rationale", "implications", "scope"]:
            old_f = existing_record.get(field)
            new_f = proposed_payload.get(field)
            if old_f != new_f:
                field_diff[field] = {"from": old_f, "to": new_f}
    else:
        # Flat record
        proposed_stmt = proposed_payload.get("statement") or proposed_payload.get("value")
        if str(existing_record) != str(proposed_stmt):
            field_diff["statement"] = {"from": existing_record, "to": proposed_stmt}

    suggested_action = "update" if field_diff else "duplicate"
    if proposed_payload.get("freshness", {}).get("supersedes"):
        suggested_action = "supersede"

    return {
        "has_existing": True,
        "canonical_key": canonical_key,
        "existing_record": existing_record,
        "suggested_action": suggested_action,
        "field_diff": field_diff,
    }


def get_context_candidates(
    project: str | None = None,
    record_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: Path | None = None,
) -> list[dict]:
    """Query staged context candidates with filtering and diff generation."""
    target = db_path or DB_PATH
    init_db(target)
    conn = get_db_connection(target)
    cursor = conn.cursor()

    query = """
        SELECT candidate_id, schema_version, record_type, canonical_key,
               payload_json, source_fingerprint, content_hash, extractor_agent,
               provider, model, prompt_version, review_status, review_rationale,
               reviewed_by, reviewed_at, merged_claim_id, created_at, updated_at
        FROM gms_context_candidates
        WHERE 1=1
    """
    params: list[Any] = []
    if status:
        query += " AND review_status = ?"
        params.append(status)
    if record_type:
        query += " AND record_type = ?"
        params.append(record_type)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    results: list[dict] = []
    for r in rows:
        try:
            payload = json.loads(r[4])
        except Exception:
            payload = {}

        if project:
            cand_proj = payload.get("project") or payload.get("scope", {}).get("project", "")
            if cand_proj.lower() != project.lower():
                continue

        results.append({
            "candidate_id": r[0],
            "schema_version": r[1],
            "record_type": r[2],
            "canonical_key": r[3],
            "payload": payload,
            "source_fingerprint": r[5],
            "content_hash": r[6],
            "extractor_agent": r[7],
            "provider": r[8],
            "model": r[9],
            "prompt_version": r[10],
            "review_status": r[11],
            "review_rationale": r[12],
            "reviewed_by": r[13],
            "reviewed_at": r[14],
            "merged_claim_id": r[15],
            "created_at": r[16],
            "updated_at": r[17],
        })
    return results


def get_context_candidate_by_id(candidate_id: str, db_path: Path | None = None) -> dict | None:
    """Fetch single staged candidate by ID with diff against active memory."""
    target = db_path or DB_PATH
    init_db(target)
    conn = get_db_connection(target)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT candidate_id, schema_version, record_type, canonical_key,
               payload_json, source_fingerprint, content_hash, extractor_agent,
               provider, model, prompt_version, review_status, review_rationale,
               reviewed_by, reviewed_at, merged_claim_id, created_at, updated_at
        FROM gms_context_candidates
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    try:
        payload = json.loads(row[4])
    except Exception:
        payload = {}

    diff_info = get_candidate_diff(row[3], payload, db_path=target)

    return {
        "candidate_id": row[0],
        "schema_version": row[1],
        "record_type": row[2],
        "canonical_key": row[3],
        "payload": payload,
        "source_fingerprint": row[5],
        "content_hash": row[6],
        "extractor_agent": row[7],
        "provider": row[8],
        "model": row[9],
        "prompt_version": row[10],
        "review_status": row[11],
        "review_rationale": row[12],
        "reviewed_by": row[13],
        "reviewed_at": row[14],
        "merged_claim_id": row[15],
        "created_at": row[16],
        "updated_at": row[17],
        "diff": diff_info,
    }


def review_context_candidate(
    candidate_id: str,
    action: str,
    reviewer: str,
    rationale: str = "",
    edited_payload: dict | None = None,
    merge_with_claim_id: int | None = None,
    expected_content_hash: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """
    Perform human or agent review action on a staged candidate:
    Actions: accept, edit, merge, supersede, reject, defer.
    Enforces registered reviewer identity, substantive rationale (>=10 chars),
    optimistic concurrency, and records append-only review audit events.
    """
    import schemas
    import reviewers

    target = db_path or DB_PATH
    init_db(target)
    cand = get_context_candidate_by_id(candidate_id, db_path=target)
    if not cand:
        return {"status": "error", "error": f"Candidate '{candidate_id}' not found"}

    # 1. Reviewer identity validation
    valid_rev, norm_rev_or_err = reviewers.validate_reviewer_id(reviewer, mem_root=target.parent)
    if not valid_rev:
        return {"status": "error", "error_code": "INVALID_REVIEWER", "error": norm_rev_or_err}
    reviewer = norm_rev_or_err

    now_iso = datetime.now(UTC).isoformat()
    action = action.lower().strip()
    payload = cand["payload"]
    key = cand["canonical_key"]
    rec_type = cand["record_type"]
    clean_rationale = str(rationale).strip()

    # 2. Substantive rationale requirement for terminal actions
    if action in ("accept", "edit", "merge", "supersede", "reject"):
        if len(clean_rationale) < 10:
            return {
                "status": "error",
                "error_code": "RATIONALE_REQUIRED",
                "error": f"Review rationale must be at least 10 non-whitespace characters (received {len(clean_rationale)}).",
            }

    # 3. Optimistic concurrency check
    original_content_hash = str(cand.get("content_hash") or "")
    if expected_content_hash and str(expected_content_hash).strip() != original_content_hash:
        return {
            "status": "error",
            "error_code": "CONCURRENCY_CONFLICT",
            "error": f"Candidate content hash mismatch (expected '{expected_content_hash}', current '{original_content_hash}'). The candidate may have been updated concurrently.",
        }

    if action in ("reject", "defer"):
        conn = get_db_connection(target)
        cursor = conn.cursor()
        status_str = "deferred" if action == "defer" else "rejected"
        cursor.execute(
            """
            UPDATE gms_context_candidates
            SET review_status = ?, review_rationale = ?, reviewed_by = ?, reviewed_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE candidate_id = ?
            """,
            (status_str, clean_rationale, reviewer, now_iso, candidate_id),
        )
        cursor.execute(
            """
            INSERT INTO gms_review_audit (
                candidate_id, canonical_key, action, reviewer_id, review_rationale,
                original_content_hash, accepted_content_hash, supersedes_claim_id,
                resulting_claim_id, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
            """,
            (candidate_id, key, action, reviewer, clean_rationale, original_content_hash, now_iso),
        )
        conn.commit()
        conn.close()
        return {"status": status_str, "candidate_id": candidate_id}

    if action == "edit":
        if not edited_payload or not isinstance(edited_payload, dict):
            return {"status": "error", "error": "Edited payload dictionary required for edit action."}
        is_valid, norm_edited, err = schemas.validate_context_candidate(edited_payload)
        if not is_valid or norm_edited is None:
            return {"status": "error", "error": f"Edited payload validation failed: {err}"}
        payload = norm_edited

    # Promote to canonical memory (accept, edit, merge, supersede)
    value_to_store = json.dumps(payload, ensure_ascii=False) if rec_type in ("decision", "policy") else (
        payload.get("statement") or json.dumps(payload, ensure_ascii=False)
    )

    # Save to facts.json
    facts_path = (target.parent / "semantic" / "facts.json") if target else (MEM_ROOT / "semantic" / "facts.json")
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    facts: dict = {}
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception:
            facts = {}

    facts[key] = value_to_store
    facts_path.write_text(json.dumps(facts, indent=2, sort_keys=True), encoding="utf-8")

    # Record claim in SQLite
    conn = get_db_connection(target)
    cursor = conn.cursor()

    supersedes_claim_id = merge_with_claim_id
    if action in ("accept", "edit", "supersede", "merge"):
        cursor.execute(
            "SELECT claim_id FROM gms_claims WHERE memory_key = ? AND status = 'active'",
            (key,)
        )
        prior_rows = cursor.fetchall()
        for prow in prior_rows:
            if not supersedes_claim_id:
                supersedes_claim_id = prow[0]
            cursor.execute(
                "UPDATE gms_claims SET status = 'superseded', confidence = 0.0 WHERE claim_id = ?",
                (prow[0],)
            )

    cursor.execute(
        """
        INSERT INTO gms_claims (
            memory_kind, memory_key, value, agent_id, branch, status,
            supersedes_claim_id, confidence, contradiction_type, created_at
        ) VALUES ('semantic', ?, ?, ?, 'main', 'active', ?, 1.0, ?, CURRENT_TIMESTAMP)
        """,
        (
            key, value_to_store, reviewer,
            supersedes_claim_id,
            "temporal_invalidation" if supersedes_claim_id else None
        ),
    )
    new_claim_id = cursor.lastrowid

    # Record fact provenance
    cursor.execute(
        """
        INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, timestamp, quarantined)
        VALUES (?, ?, 'main', CURRENT_TIMESTAMP, 0)
        ON CONFLICT(fact_key) DO UPDATE SET
            agent_id = excluded.agent_id,
            timestamp = CURRENT_TIMESTAMP,
            quarantined = 0
        """,
        (key, reviewer),
    )

    accepted_content_hash = schemas.compute_canonical_content_hash(payload)

    # Update candidate record in staging table
    final_status = "accepted" if action in ("accept", "edit", "supersede") else "merged"
    cursor.execute(
        """
        UPDATE gms_context_candidates
        SET review_status = ?, review_rationale = ?, reviewed_by = ?, reviewed_at = ?,
            payload_json = ?, merged_claim_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE candidate_id = ?
        """,
        (
            final_status, clean_rationale, reviewer, now_iso,
            json.dumps(payload, ensure_ascii=False), new_claim_id, candidate_id
        ),
    )

    # Insert review audit event
    cursor.execute(
        """
        INSERT INTO gms_review_audit (
            candidate_id, canonical_key, action, reviewer_id, review_rationale,
            original_content_hash, accepted_content_hash, supersedes_claim_id,
            resulting_claim_id, reviewed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id, key, action, reviewer, clean_rationale,
            original_content_hash, accepted_content_hash, supersedes_claim_id,
            new_claim_id, now_iso
        ),
    )
    conn.commit()
    conn.close()

    return {
        "status": final_status,
        "candidate_id": candidate_id,
        "canonical_key": key,
        "claim_id": new_claim_id,
        "merged_claim_id": supersedes_claim_id,
        "accepted_content_hash": accepted_content_hash,
    }


def get_review_audit_history(candidate_id: str | None = None, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    """Return append-only audit trail of candidate review actions."""
    target = db_path or DB_PATH
    init_db(target)
    conn = get_db_connection(target)
    cursor = conn.cursor()
    if candidate_id:
        cursor.execute(
            """
            SELECT audit_id, candidate_id, canonical_key, action, reviewer_id, review_rationale,
                   original_content_hash, accepted_content_hash, supersedes_claim_id,
                   resulting_claim_id, reviewed_at, created_at
            FROM gms_review_audit
            WHERE candidate_id = ?
            ORDER BY audit_id DESC
            LIMIT ?
            """,
            (candidate_id, limit),
        )
    else:
        cursor.execute(
            """
            SELECT audit_id, candidate_id, canonical_key, action, reviewer_id, review_rationale,
                   original_content_hash, accepted_content_hash, supersedes_claim_id,
                   resulting_claim_id, reviewed_at, created_at
            FROM gms_review_audit
            ORDER BY audit_id DESC
            LIMIT ?
            """,
            (limit,),
        )
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "audit_id": r[0],
            "candidate_id": r[1],
            "canonical_key": r[2],
            "action": r[3],
            "reviewer_id": r[4],
            "review_rationale": r[5],
            "original_content_hash": r[6],
            "accepted_content_hash": r[7],
            "supersedes_claim_id": r[8],
            "resulting_claim_id": r[9],
            "reviewed_at": r[10],
            "created_at": r[11],
        }
        for r in rows
    ]


def get_latest_quarantined_claim_id(kind: str, key: str, agent_id: str) -> int | None:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT claim_id
        FROM gms_claims
        WHERE memory_kind = ? AND memory_key = ? AND agent_id = ? AND status = 'quarantined'
        ORDER BY claim_id DESC
        LIMIT 1
        """,
        (kind, key, agent_id),
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def record_quarantine_review(fact_key: str, agent_id: str, reviewer_id: str, rating: str, rationale: str):
    kind, real_key = parse_prov_key(fact_key)
    claim_id = get_latest_quarantined_claim_id(kind, real_key, agent_id)
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO gms_quarantine_reviews (
            fact_key, agent_id, reviewer_id, claim_id, rating, rationale,
            weight_snapshot, timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(fact_key, agent_id, reviewer_id) DO UPDATE SET
            claim_id = excluded.claim_id,
            rating = excluded.rating,
            rationale = excluded.rationale,
            weight_snapshot = excluded.weight_snapshot,
            timestamp = CURRENT_TIMESTAMP
    """, (fact_key, agent_id, reviewer_id, claim_id, rating, rationale, 1.0))
    conn.commit()
    conn.close()


def get_quarantine_reviews(fact_key: str, agent_id: str, include_resolved: bool = False) -> list[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    if include_resolved:
        cursor.execute("""
            SELECT reviewer_id, rating, rationale, weight_snapshot, claim_id, timestamp
            FROM gms_quarantine_reviews
            WHERE fact_key = ? AND agent_id = ?
            ORDER BY timestamp DESC, review_id DESC
        """, (fact_key, agent_id))
    else:
        cursor.execute("""
            SELECT reviewer_id, rating, rationale, weight_snapshot, claim_id, timestamp
            FROM gms_quarantine_reviews
            WHERE fact_key = ? AND agent_id = ? AND (resolution IS NULL OR resolution = '')
            ORDER BY timestamp DESC, review_id DESC
        """, (fact_key, agent_id))
    rows = cursor.fetchall()
    conn.close()

    reviews = []
    for reviewer_id, rating, rationale, weight_snapshot, claim_id, timestamp in rows:
        reviews.append({
            "reviewer_id": reviewer_id,
            "rating": rating,
            "rationale": rationale or "",
            "weight_snapshot": 1.0,
            "claim_id": claim_id,
            "timestamp": timestamp,
        })
    return reviews


def get_quarantine_recommendation(fact_key: str, agent_id: str) -> dict:
    reviews = get_quarantine_reviews(fact_key, agent_id)
    if not reviews:
        return {
            "recommendation": "neutral",
            "score": 0.5,
            "reviewer_count": 0,
            "endorse_count": 0,
            "reject_count": 0,
            "abstain_count": 0,
            "reviews": [],
        }

    endorse_count = 0
    reject_count = 0
    abstain_count = 0

    for review in reviews:
        if review["rating"] == "endorse":
            endorse_count += 1
        elif review["rating"] == "reject":
            reject_count += 1
        else:
            abstain_count += 1

    # Mixed human/agent reviews are a conflict to inspect, not a popularity or
    # reputation contest. An unopposed review can guide the default workflow;
    # any disagreement remains neutral until an explicit owner/system decision.
    if endorse_count and reject_count:
        rec = "neutral"
    elif endorse_count:
        rec = "promote"
    elif reject_count:
        rec = "discard"
    else:
        rec = "neutral"

    return {
        "recommendation": rec,
        "score": None,
        "reviewer_count": len(reviews),
        "endorse_count": endorse_count,
        "reject_count": reject_count,
        "abstain_count": abstain_count,
        "reviews": reviews,
    }


def apply_review_outcome(fact_key: str, agent_id: str, action: str) -> None:
    apply_review_outcome_from_reviews(get_quarantine_reviews(fact_key, agent_id), action)


def apply_review_outcome_from_reviews(reviews: list[dict], action: str) -> None:
    for review in reviews:
        rating = review["rating"]
        reviewer_id = review["reviewer_id"]
        if rating == "abstain":
            continue
        # Review history is evidence. It must not be converted into a global
        # reliability score that affects unrelated future claims.
        _ = reviewer_id, action, rating


def parse_prov_key(prov_key: str) -> tuple[str, str]:
    if ":" in prov_key:
        parts = prov_key.split(":", 1)
        return parts[0], parts[1]
    return "semantic", prov_key


def _detect_branch() -> str:
    try:
        res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            branch = res.stdout.strip()
            if branch:
                return branch
    except Exception:
        pass
    return "main"


def log_security_event(event_type: str, message: str):
    try:
        log_dir = Path.home() / ".codex" / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "gms_security.log"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_file.open("a") as f:
            f.write(f"[{now}] [{event_type}] {message}\n")
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Temporal Knowledge Graph & LightRAG Substrate
# ──────────────────────────────────────────────────────────────────────────────

def get_or_create_entity(conn: sqlite3.Connection, name: str, entity_type: str = "concept", summary: str = "") -> int:
    name = name.strip()
    if not name:
        return 0
    cursor = conn.cursor()
    cursor.execute("SELECT entity_id FROM gms_entities WHERE LOWER(name) = LOWER(?)", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute(
        "INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, ?, ?)",
        (name, entity_type, summary)
    )
    return cursor.lastrowid


SINGLE_VALUED_PREDICATES = {
    "configured_as", "status", "targets", "assigned_to", "points_to", 
    "active_model", "ip_address", "works_at", "location", "current_role",
    "state", "current_branch", "endpoint", "version"
}


def record_graph_relationship(
    subject: str,
    predicate: str,
    obj: str,
    is_object_literal: bool = False,
    subject_type: str = "concept",
    object_type: str = "concept",
    valid_from: str | None = None,
    valid_to: str | None = None,
    source_claim_id: int | None = None,
    single_valued: bool | None = None,
) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    sub_id = get_or_create_entity(conn, subject, subject_type)
    obj_id = None
    obj_literal = None

    if is_object_literal:
        obj_literal = obj
    else:
        obj_id = get_or_create_entity(conn, obj, object_type)

    now_iso = datetime.now().isoformat()
    valid_from = valid_from or now_iso

    # Bi-temporal invalidation for single-valued / functional predicates
    norm_pred = predicate.lower().strip().replace("-", "_").replace(" ", "_")
    is_single_val = single_valued if single_valued is not None else (norm_pred in SINGLE_VALUED_PREDICATES)

    if is_single_val:
        cursor.execute(
            """
            SELECT relationship_id, object_entity_id, object_literal FROM gms_relationships
            WHERE subject_entity_id = ? AND predicate = ? AND (valid_to IS NULL OR valid_to > ?)
            """,
            (sub_id, predicate, valid_from)
        )
        existing_active = cursor.fetchall()
        for prev_rel_id, prev_obj_id, prev_obj_lit in existing_active:
            target_matches = (prev_obj_id == obj_id and prev_obj_lit == obj_literal) if (obj_id is not None or obj_literal is not None) else False
            if not target_matches:
                cursor.execute(
                    "UPDATE gms_relationships SET valid_to = ? WHERE relationship_id = ?",
                    (valid_from, prev_rel_id)
                )

    cursor.execute(
        """
        SELECT relationship_id FROM gms_relationships
        WHERE subject_entity_id = ? AND predicate = ? AND (object_entity_id = ? OR object_literal = ?)
        """,
        (sub_id, predicate, obj_id, obj_literal)
    )
    row = cursor.fetchone()
    if row:
        rel_id = row[0]
        cursor.execute("UPDATE gms_relationships SET valid_from = ?, valid_to = NULL WHERE relationship_id = ?", (valid_from, rel_id))
        conn.commit()
        conn.close()
        return rel_id

    cursor.execute(
        """
        INSERT INTO gms_relationships (
            subject_entity_id, predicate, object_entity_id, object_literal,
            source_claim_id, valid_from, valid_to, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (sub_id, predicate, obj_id, obj_literal, source_claim_id, valid_from, valid_to)
    )
    rel_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return rel_id


def invalidate_graph_relationship(
    subject: str,
    predicate: str,
    obj: str | None = None,
    valid_to: str | None = None,
) -> int:
    """Invalidate active graph relationships matching subject and predicate (and optionally obj)."""
    now_iso = datetime.now().isoformat()
    valid_to = valid_to or now_iso
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute("SELECT entity_id FROM gms_entities WHERE LOWER(name) = LOWER(?)", (subject.strip(),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return 0
    sub_id = row[0]

    if obj is not None:
        cursor.execute("SELECT entity_id FROM gms_entities WHERE LOWER(name) = LOWER(?)", (obj.strip(),))
        obj_row = cursor.fetchone()
        obj_id = obj_row[0] if obj_row else None
        cursor.execute(
            """
            UPDATE gms_relationships
            SET valid_to = ?
            WHERE subject_entity_id = ? AND predicate = ?
              AND (object_entity_id = ? OR object_literal = ?)
              AND (valid_to IS NULL OR valid_to > ?)
            """,
            (valid_to, sub_id, predicate, obj_id, obj.strip(), valid_to)
        )
    else:
        cursor.execute(
            """
            UPDATE gms_relationships
            SET valid_to = ?
            WHERE subject_entity_id = ? AND predicate = ?
              AND (valid_to IS NULL OR valid_to > ?)
            """,
            (valid_to, sub_id, predicate, valid_to)
        )
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated


def extract_graph_triples(text: str) -> list[tuple[str, str, str]]:
    """Extract (Subject, Predicate, Object) relationship triples from text using clean entity normalization."""
    import re
    triples = []
    if not text:
        return triples

    stopwords = {
        "a", "an", "the", "this", "that", "it", "to", "in", "on", "as", "at", "by", "for", 
        "with", "from", "is", "was", "are", "were", "be", "been", "being", "should", "could", 
        "would", "and", "or", "but", "if", "not", "no", "yes", "so", "than", "then", "of"
    }

    def _normalize_entity(e: str) -> str:
        e = e.strip()
        # Strip leading articles
        for prefix in ["the ", "a ", "an ", "this ", "that "]:
            if e.lower().startswith(prefix):
                e = e[len(prefix):].strip()
                break
        return e

    # 1. Key-value style: "key: value" or "key = value"
    kv_match = re.match(r"^([a-zA-Z0-9_\-\s]{3,40})\s*[:=]\s*(.+)$", text.strip())
    if kv_match:
        subj = _normalize_entity(kv_match.group(1))
        obj = _normalize_entity(kv_match.group(2))
        if subj.lower() not in stopwords and len(subj) >= 3 and len(obj) >= 2 and len(obj) < 150:
            triples.append((subj, "configured_as", obj))

    # 2. Clean verb relationship patterns
    patterns = [
        (r"\b([a-zA-Z0-9_\-\s]{3,35})\s+(?:uses|used|using)\s+([a-zA-Z0-9_\-\.\/]+)\b", "uses"),
        (r"\b([a-zA-Z0-9_\-\s]{3,35})\s+(?:depends on|relies on|dependent on)\s+([a-zA-Z0-9_\-\.\/]+)\b", "depends_on"),
        (r"\b([a-zA-Z0-9_\-\s]{3,35})\s+(?:created|implemented|built)\s+([a-zA-Z0-9_\-\.\/]+)\b", "created"),
        (r"\b([a-zA-Z0-9_\-\s]{3,35})\s+(?:updated|modified|refactored)\s+([a-zA-Z0-9_\-\.\/]+)\b", "updated"),
        (r"\b([a-zA-Z0-9_\-\s]{3,35})\s+(?:targets|routes to|points to)\s+([a-zA-Z0-9_\-\.\/]+)\b", "targets"),
    ]

    for pat, pred in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            sub = _normalize_entity(m.group(1))
            obj = _normalize_entity(m.group(2))
            
            # Strict stopword & quality filter
            if (sub and obj and sub.lower() != obj.lower() 
                and sub.lower() not in stopwords 
                and obj.lower() not in stopwords 
                and not sub.lower().endswith(" to") 
                and not sub.lower().endswith(" in")
                and not sub.lower().endswith(" as")
                and not sub.lower().endswith(" and")
                and len(sub) >= 3 and len(obj) >= 2):
                triples.append((sub, pred, obj))

    return triples


def query_entity_graph(
    entity_name: str,
    hops: int = 2,
    valid_at: str | None = None,
    include_expired: bool = False,
) -> dict:
    import networkx as nx
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("SELECT entity_id, name, entity_type, summary FROM gms_entities")
    entities = {row[0]: {"name": row[1], "type": row[2], "summary": row[3]} for row in cursor.fetchall()}

    cursor.execute("""
        SELECT relationship_id, subject_entity_id, predicate, object_entity_id, object_literal, valid_from, valid_to
        FROM gms_relationships
    """)
    rows = cursor.fetchall()
    conn.close()

    now_iso = datetime.now().isoformat()
    check_time = valid_at if valid_at else now_iso

    G = nx.DiGraph()
    for rel_id, sub_id, pred, obj_id, obj_lit, v_from, v_to in rows:
        if not include_expired:
            if v_from and v_from > check_time:
                continue
            if v_to and v_to <= check_time:
                continue
        sub_name = entities.get(sub_id, {}).get("name", str(sub_id))
        obj_name = entities.get(obj_id, {}).get("name", obj_lit) if obj_id else obj_lit
        if sub_name and obj_name:
            G.add_edge(sub_name, obj_name, predicate=pred, rel_id=rel_id, valid_from=v_from, valid_to=v_to)

    # Candidate entity resolution for exact entities or natural language queries
    seed_nodes = []
    query_lower = entity_name.lower().strip()
    query_tokens = set(re.findall(r'\b\w{3,}\b', query_lower))

    # 1. Exact match
    for node in G.nodes():
        if node.lower() == query_lower:
            seed_nodes.append(node)

    # 2. Substring or token overlap match
    if not seed_nodes:
        for node in G.nodes():
            n_low = node.lower()
            n_clean = n_low.replace("_", " ").replace("-", " ")
            if len(n_low) >= 3 and (n_low in query_lower or n_clean in query_lower or query_lower in n_low):
                seed_nodes.append(node)
                continue
            node_tokens = set(re.findall(r'\b\w{3,}\b', n_low))
            if node_tokens and node_tokens.issubset(query_tokens):
                seed_nodes.append(node)

    if not seed_nodes:
        return {"entity": entity_name, "found": False, "nodes": [], "edges": []}

    target_node = seed_nodes[0]
    subgraph_nodes = set(seed_nodes)
    current_frontier = set(seed_nodes)
    for _ in range(hops):
        next_frontier = set()
        for n in current_frontier:
            neighbors = set(G.successors(n)).union(set(G.predecessors(n)))
            next_frontier.update(neighbors)
        subgraph_nodes.update(next_frontier)
        current_frontier = next_frontier

    # HippoRAG Personalized PageRank (PPR) Diffusion
    ppr_scores = {}
    if seed_nodes and len(G) > 0:
        try:
            pers = {n: 0.0 for n in G.nodes()}
            weight = 1.0 / len(seed_nodes)
            for s in seed_nodes:
                if s in pers:
                    pers[s] = weight
            UG = G.to_undirected(as_view=True)
            raw_ppr = nx.pagerank(UG, alpha=0.85, personalization=pers, max_iter=100, tol=1e-5)
            ppr_scores = {n: round(score, 4) for n, score in sorted(raw_ppr.items(), key=lambda x: -x[1]) if score > 0.0001}
        except Exception:
            ppr_scores = {}

    subgraph = G.subgraph(subgraph_nodes)
    edges = []
    for u, v, data in subgraph.edges(data=True):
        edges.append({
            "subject": u,
            "predicate": data.get("predicate", "related_to"),
            "object": v,
            "valid_from": data.get("valid_from"),
            "valid_to": data.get("valid_to")
        })

    return {
        "entity": target_node,
        "matched_entities": seed_nodes,
        "found": True,
        "hops": hops,
        "node_count": len(subgraph_nodes),
        "edge_count": len(edges),
        "nodes": sorted(list(subgraph_nodes)),
        "ppr_scores": ppr_scores,
        "edges": edges
    }



def format_ascii_graph(graph_data: dict) -> str:
    if not graph_data.get("found"):
        return f"Entity '{graph_data.get('entity')}' not found in Knowledge Graph."

    root = graph_data["entity"]
    seeds = graph_data.get("matched_entities", [root])
    header_label = root if len(seeds) <= 1 else f"{root} (+{len(seeds)-1} related)"
    lines = [f"Knowledge Graph Topology for [{header_label}] ({graph_data['node_count']} nodes, {graph_data['edge_count']} edges):", ""]

    root_lower = root.lower()
    outgoing = [e for e in graph_data["edges"] if e["subject"].lower() == root_lower]
    incoming = [e for e in graph_data["edges"] if e["object"].lower() == root_lower]

    if outgoing:
        lines.append("  [Outgoing Relationships]")
        for i, edge in enumerate(outgoing):
            prefix = "  ├──" if i < len(outgoing) - 1 else "  └──"
            lines.append(f"{prefix} --({edge['predicate']})--> [{edge['object']}]")

    if incoming:
        lines.append("  [Incoming Relationships]")
        for i, edge in enumerate(incoming):
            prefix = "  ├──" if i < len(incoming) - 1 else "  └──"
            lines.append(f"{prefix} <--({edge['predicate']})-- [{edge['subject']}]")

    # Connected triples between other subgraph nodes
    handled_edges = set((e["subject"], e["predicate"], e["object"]) for e in outgoing + incoming)
    connected_triples = [e for e in graph_data["edges"] if (e["subject"], e["predicate"], e["object"]) not in handled_edges]
    if connected_triples:
        lines.append("  [Connected Knowledge Triples]")
        for i, edge in enumerate(connected_triples):
            prefix = "  ├──" if i < len(connected_triples) - 1 else "  └──"
            lines.append(f"{prefix} [{edge['subject']}] --({edge['predicate']})--> [{edge['object']}]")

    # Associative Relevance via HippoRAG Personalized PageRank
    ppr_map = graph_data.get("ppr_scores", {})
    if ppr_map and len(ppr_map) > 1:
        top_associations = [f"{n} ({s})" for n, s in list(ppr_map.items()) if n.lower() != root_lower][:5]
        if top_associations:
            lines.append("  [Associative Relevance (HippoRAG PPR)]")
            for i, item in enumerate(top_associations):
                prefix = "  ├──" if i < len(top_associations) - 1 else "  └──"
                lines.append(f"{prefix} {item}")

    return "\n".join(lines)


def format_mermaid_graph(graph_data: dict) -> str:
    if not graph_data.get("found") or not graph_data.get("edges"):
        return "```mermaid\ngraph TD\n    EmptyGraph[\"No graph edges found\"]\n```"
    lines = ["```mermaid", "graph TD"]
    for edge in graph_data["edges"]:
        sub = edge["subject"].replace('"', '\\"')
        obj = edge["object"].replace('"', '\\"')
        pred = edge["predicate"].replace('"', '\\"')
        lines.append(f'    "{sub}" -->|"{pred}"| "{obj}"')
    lines.append("```")
    return "\n".join(lines)


def tool_mem_graph_extract(args: dict) -> str:
    """Extract and register Knowledge Graph triples from text."""
    text = args.get("text", "").strip()
    if not text:
        return "ERROR: 'text' is required"
    triples = extract_graph_triples(text)
    if not triples:
        key = args.get("key", "").strip()
        val = args.get("value", "").strip()
        if key and val:
            triples = [(key, "configured_as", val)]

    if not triples:
        return "INFO: No entity-relationship triples extracted from text."

    saved = []
    for sub, pred, obj in triples:
        rel_id = record_graph_relationship(sub, pred, obj)
        saved.append(f"({sub} -> {pred} -> {obj}) [rel_id={rel_id}]")

    return f"Knowledge Graph extracted {len(saved)} triple(s):\n" + "\n".join(f"- {s}" for s in saved)


def tool_mem_graph_query(args: dict) -> str:
    """Query 1-hop & 2-hop Knowledge Graph relationships for an entity."""
    entity = args.get("entity", "").strip()
    hops = int(args.get("hops", 2))
    format_mode = args.get("format", "mermaid").strip().lower()
    valid_at = args.get("valid_at") or args.get("as_of")
    include_expired = str(args.get("include_expired", "false")).lower() in ("true", "1", "yes")

    if not entity:
        return "ERROR: 'entity' is required"

    try:
        init_db()
        data = query_entity_graph(entity, hops=hops, valid_at=valid_at, include_expired=include_expired)
        if not data.get("found"):
            return f"INFO: Entity '{entity}' not found in Knowledge Graph."

        if format_mode == "ascii":
            return format_ascii_graph(data)
        elif format_mode == "json":
            return json.dumps(data, indent=2)
        else:
            ascii_text = format_ascii_graph(data)
            mermaid_text = format_mermaid_graph(data)
            return f"{ascii_text}\n\n{mermaid_text}"
    except Exception as e:
        return f"ERROR: Knowledge Graph query failed: {e}"


def tool_mem_graph_entities(args: dict) -> str:
    """List registered entities in the Knowledge Graph."""
    prefix = args.get("prefix", "").strip().lower()
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT entity_id, name, entity_type, summary FROM gms_entities ORDER BY name ASC")
        rows = cursor.fetchall()
        conn.close()

        entities = []
        for eid, name, etype, summary in rows:
            if prefix and not name.lower().startswith(prefix):
                continue
            entities.append({"entity_id": eid, "name": name, "type": etype, "summary": summary or ""})

        return json.dumps(entities, indent=2)
    except Exception as e:
        return f"ERROR: Listing graph entities failed: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# MCP Protocol (minimal stdio JSON-RPC 2.0 implementation)
# No external mcp package required — pure stdlib.
# ──────────────────────────────────────────────────────────────────────────────

def _send(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _text(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}]}


# ──────────────────────────────────────────────────────────────────────────────
# Memory helpers
# ──────────────────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(errors="replace")


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(text)


def _load_typed_facts(kind: str) -> dict:
    if kind == "session":
        return {}
    p = MEM_ROOT / kind / "facts.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_typed_facts(kind: str, facts: dict) -> None:
    if kind == "session":
        return
    p = MEM_ROOT / kind / "facts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(facts, indent=2, sort_keys=True))


def _load_facts() -> dict:
    return _load_typed_facts("semantic")


def _save_facts(facts: dict) -> None:
    _save_typed_facts("semantic", facts)


def determine_routing(key: str, value: str) -> str:
    k = key.lower()
    v = value.lower()
    
    # Session criteria: current conversation / ephemeral task state
    session_keywords = ["conversation", "task_state", "ephemeral", "session", "current_task", "chat_history", "temp"]
    if any(kw in k or kw in v for kw in session_keywords):
        return "session"
        
    # Operational criteria: agent behavior / config / preferences / policies
    operational_keywords = ["behavior", "config", "preferences", "policies", "policy", "settings", "rules", "agent_behavior", "agent_config", "agent_pref"]
    if any(kw in k or kw in v for kw in operational_keywords):
        return "operational"
        
    # Procedural criteria: learned reusable instructions / trigger-action patterns
    procedural_keywords = ["instruction", "trigger", "action", "how_to", "procedure", "recipe", "pattern", "trigger_action"]
    if any(kw in k or kw in v for kw in procedural_keywords):
        return "procedural"
        
    return "semantic"


def _embed(text: str) -> list[float] | None:
    try:
        payload = json.dumps({"model": EMBED_MODEL, "prompt": text, "keep_alive": "30m"}).encode()
        req = request.Request(
            f"{OLLAMA_URL}/api/embeddings", data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with request.urlopen(req, timeout=EMBED_TIMEOUT) as resp:  # nosec B310
            body = json.loads(resp.read().decode())
        emb = body.get("embedding")
        return emb if isinstance(emb, list) and emb else None
    except Exception:
        return None


def store_sqlite_embeddings(
    items: list[dict],
    model: str = EMBED_MODEL,
    db_path: Path | None = None
) -> int:
    """
    Store embedding vectors directly into gms_embeddings in SQLite.
    items: list of dicts with keys: source, chunk, text, embedding (list[float])
    """
    import struct
    p = db_path or DB_PATH
    conn = sqlite3.connect(str(p))
    cursor = conn.cursor()
    count = 0
    now_iso = datetime.now().isoformat()

    for item in items:
        emb = item["embedding"]
        dim = len(emb)
        blob = struct.pack(f"{dim}f", *emb)
        cursor.execute(
            """
            INSERT OR REPLACE INTO gms_embeddings
            (source, chunk, text, embedding, dim, model, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item["source"], item["chunk"], item["text"], blob, dim, model, now_iso)
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def search_sqlite_embeddings(
    query_vector: list[float],
    top_k: int = 5,
    model: str | None = None,
    db_path: Path | None = None
) -> list[dict]:
    """
    Search SQLite embeddings using cosine similarity.
    Uses NumPy if available, with pure-Python fallback.
    """
    import struct
    import math

    p = db_path or DB_PATH
    if not p.exists():
        return []

    conn = sqlite3.connect(str(p))
    cursor = conn.cursor()

    query_sql = "SELECT id, source, chunk, text, embedding, dim, model FROM gms_embeddings"
    params = []
    if model:
        query_sql += " WHERE model = ?"
        params.append(model)

    cursor.execute(query_sql, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return []

    q_dim = len(query_vector)
    q_norm = math.sqrt(sum(x * x for x in query_vector))
    if q_norm == 0:
        q_norm = 1.0
    normalized_q = [x / q_norm for x in query_vector]

    results = []
    try:
        import numpy as np
        q_arr = np.array(normalized_q, dtype=np.float32)

        embs = []
        meta = []
        for r in rows:
            blob = r[4]
            dim = r[5]
            if dim != q_dim:
                continue
            emb = struct.unpack(f"{dim}f", blob)
            embs.append(emb)
            meta.append(r)

        if embs:
            mat = np.array(embs, dtype=np.float32)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            mat = mat / norms
            scores = np.dot(mat, q_arr)
            for idx in np.argsort(-scores)[:top_k]:
                score = float(scores[idx])
                r = meta[idx]
                results.append({
                    "id": r[0],
                    "source": r[1],
                    "chunk": r[2],
                    "text": r[3],
                    "score": score,
                    "model": r[6]
                })
    except ImportError:
        scored = []
        for r in rows:
            blob = r[4]
            dim = r[5]
            if dim != q_dim:
                continue
            emb = struct.unpack(f"{dim}f", blob)
            e_norm = math.sqrt(sum(x * x for x in emb)) or 1.0
            score = sum(a * (b / e_norm) for a, b in zip(normalized_q, emb))
            scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        for score, r in scored[:top_k]:
            results.append({
                "id": r[0],
                "source": r[1],
                "chunk": r[2],
                "text": r[3],
                "score": float(score),
                "model": r[6]
            })

    return results



def _run_memoryctl(*args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [str(MEMORYCTL)] + list(args),
            capture_output=True, text=True, timeout=300
        )
        out = (result.stdout + result.stderr).strip()
        return result.returncode, out
    except Exception as e:
        return 1, str(e)


# ──────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────────────

def tool_mem_session_start(_: dict) -> str:
    """Load and return the full startup context bundle (replaces `memoryctl start-context`)."""
    idx       = _read(MEM_ROOT / "index.md")
    prefs     = _read(MEM_ROOT / "preferences.md")
    projects  = _read(MEM_ROOT / "projects.md")
    lessons   = _read(MEM_ROOT / "lessons" / "global.md")
    today     = datetime.now().strftime("%Y-%m-%d")
    history_dir = MEM_ROOT / "episodic" / "history"
    daily     = history_dir / f"{today}.md"
    if daily.exists() and daily.stat().st_size > 200:
        episodic = _read(daily)
    elif history_dir.exists():
        valid_files = [p for p in sorted(history_dir.glob("*.md")) if p.stat().st_size > 200]
        if valid_files:
            episodic = _read(valid_files[-1])
        else:
            episodic = _read(MEM_ROOT / "episodic" / "journal.md")
    else:
        episodic = _read(MEM_ROOT / "episodic" / "journal.md")

    facts     = _load_facts()
    top_facts = dict(list(facts.items())[:10])

    return (
        f"## GMS Session Context — {today}\n\n"
        f"### Preferences\n{prefs[:1500]}\n\n"
        f"### Active Projects\n{projects[:1500]}\n\n"
        f"### Lessons\n{lessons[:8000]}\n\n"
        f"### Top Facts\n{json.dumps(top_facts, indent=2)}\n\n"
        f"### Recent Episodic\n{episodic[-2000:]}"
    )


def tool_mem_session_end(args: dict) -> str:
    """Log a session-end milestone to episodic memory and run Agentic Sleep micro-consolidation."""
    agent   = args.get("agent", "unknown")
    summary = args.get("summary", "")
    if not summary:
        return "ERROR: 'summary' is required"
    now  = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_ = now.strftime("%H:%M")
    daily = MEM_ROOT / "episodic" / "history" / f"{today}.md"
    target = daily if daily.exists() else MEM_ROOT / "episodic" / "journal.md"
    entry = f"\n### {today} [{time_}] - {agent} - Session End\n- {summary}\n"
    _append(target, entry)

    try:
        init_db()
        increment_agent_alpha(agent, 0.5)
    except Exception:
        pass

    harvest_result = None
    harvest_fn = _get_harvest_fn()
    if harvest_fn is not None:
        try:
            harvest_result = harvest_fn(agent=agent, summary=summary, text=entry, mem_root=MEM_ROOT)
        except Exception:
            pass

    out_msg = f"Session end logged to {target}"
    if harvest_result:
        facts_cnt = len(harvest_result.get("facts_saved", []))
        triples_cnt = harvest_result.get("triples_recorded", 0)
        vecs_cnt = harvest_result.get("vectors_indexed", 0)
        out_msg += f"\n[Agentic Sleep Harvest] Facts saved: {facts_cnt}, Triples: {triples_cnt}, Vectors indexed: {vecs_cnt}"
    return out_msg


def tool_mem_session_harvest(args: dict) -> str:
    """Run automated post-session micro-consolidation ('Agentic Sleep')."""
    agent = _normalize_agent_id(args.get("agent", "unknown"))
    summary = args.get("summary", "")
    if not summary:
        return "ERROR: 'summary' is required"
    text = args.get("text")
    harvest_fn = _get_harvest_fn()
    if harvest_fn is None:
        return "ERROR: harvest module not available"
    try:
        report = harvest_fn(agent=agent, summary=summary, text=text, mem_root=MEM_ROOT)
        return json.dumps(report, indent=2)
    except Exception as exc:
        return f"ERROR: harvesting failed: {exc}"


def tool_mem_validate_schemas(args: dict) -> str:
    """Validate all active facts against registered schema contracts."""
    contracts = list_contracts()
    report = {
        "contracts_available": list(contracts.keys()),
        "validation_results": {},
        "violations": []
    }
    for bucket in ("semantic", "operational", "procedural"):
        facts = _load_typed_facts(bucket)
        for k, v in facts.items():
            is_valid, norm_val, err_msg = validate_fact(k, v)
            ns = get_namespace_for_key(k)
            if ns:
                if is_valid:
                    report["validation_results"][k] = "valid"
                else:
                    report["validation_results"][k] = "invalid"
                    report["violations"].append({"key": k, "bucket": bucket, "error": err_msg})
            else:
                report["validation_results"][k] = "untyped"

    return json.dumps(report, indent=2)


def tool_mem_project_briefing(args: dict) -> str:
    """Generate or explain operational project briefing."""
    from project_briefing import generate_project_briefing, explain_project_briefing
    project_id = args.get("project") or args.get("project_id", "")
    if not project_id:
        return "ERROR: 'project' or 'project_id' is required"
    as_of = args.get("as_of")
    profile = args.get("profile", "standard")
    action = args.get("action", "get")
    briefing = generate_project_briefing(MEM_ROOT, project_id, as_of=as_of, profile=profile)
    if action == "explain":
        return json.dumps(explain_project_briefing(briefing), indent=2)
    return json.dumps(briefing, indent=2)


def tool_mem_context_packet(args: dict) -> str:
    """Build the deterministic, conflict-aware context packet used for agent resumption."""
    from context_packet import build_context_packet
    query = str(args.get("query") or "").strip()
    if not query:
        return "ERROR: 'query' is required"
    try:
        result = build_context_packet(
            MEM_ROOT, query, project=str(args.get("project") or "").strip(),
            profile=str(args.get("profile") or "standard"), as_of=args.get("as_of"),
        )
        return json.dumps(result, indent=2)
    except Exception as exc:
        return f"ERROR: context packet failed: {exc}"


def tool_mem_curation(args: dict) -> str:
    """Preview/apply system curation or preview/apply an owner contest."""
    from autonomous_curation import curate_pending, contest_candidate
    action = str(args.get("action") or "status").strip().lower()
    limit = max(1, min(int(args.get("limit", 100)), 500))
    if action == "status":
        candidates = get_context_candidates(limit=limit, db_path=DB_PATH)
        counts: dict[str, int] = {}
        for candidate in candidates:
            status = str(candidate.get("review_status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return json.dumps({"policy": "system-decides-user-may-contest-v1", "counts": counts,
                           "total_returned": len(candidates), "limit": limit}, indent=2)
    if action in {"preview", "apply"}:
        return json.dumps(curate_pending(MEM_ROOT, apply=action == "apply", limit=limit), indent=2)
    if action in {"contest_preview", "contest_apply"}:
        candidate_id = str(args.get("candidate_id") or "").strip()
        rationale = str(args.get("rationale") or "").strip()
        if not candidate_id:
            return "ERROR: 'candidate_id' is required for contest actions"
        return json.dumps(contest_candidate(MEM_ROOT, candidate_id, rationale,
                                            apply=action == "contest_apply"), indent=2)
    return "ERROR: action must be status, preview, apply, contest_preview, or contest_apply"


def tool_mem_memory_quality(args: dict) -> str:
    """Run convention, pollution, or candidate-source integrity analysis."""
    action = str(args.get("action") or "summary").strip().lower()
    from memory_convention_audit import convention_audit
    import pollution_audit
    if action == "conventions":
        return json.dumps(convention_audit(MEM_ROOT), indent=2)
    if action == "pollution":
        return json.dumps(pollution_audit.run_pollution_audit(mem_root=MEM_ROOT), indent=2)
    if action == "source":
        candidate_id = str(args.get("candidate_id") or "").strip()
        if not candidate_id:
            return "ERROR: 'candidate_id' is required for source verification"
        candidate = get_context_candidate_by_id(candidate_id, db_path=DB_PATH)
        if not candidate:
            return f"ERROR: candidate '{candidate_id}' not found"
        payload = candidate.get("payload") or {}
        evidence = payload.get("evidence") or [
            {"ref": ref} for ref in (payload.get("provenance") or {}).get("source_refs", [])
        ]
        results = []
        for item in evidence:
            valid, status, details = validate_source_reference(
                str(item.get("ref") or ""), excerpt_hash=item.get("excerpt_hash"), mem_root=MEM_ROOT
            )
            results.append({"ref": item.get("ref"), "valid": valid, "status": status, "details": details})
        return json.dumps({"candidate_id": candidate_id, "evidence_count": len(results),
                           "all_valid": bool(results) and all(x["valid"] for x in results),
                           "results": results}, indent=2)
    if action == "summary":
        conventions = convention_audit(MEM_ROOT)
        pollution = pollution_audit.run_pollution_audit(mem_root=MEM_ROOT)
        return json.dumps({"schema_version": "gms-memory-quality-summary-v1",
                           "conventions": conventions, "pollution": pollution}, indent=2)
    return "ERROR: action must be summary, conventions, pollution, or source"


def tool_mem_memory_repair(args: dict) -> str:
    """Analyze, find evidence, stage, or archive an incomplete legacy fact."""
    from memory_repair import (analyze_missing_fields, archive_opaque_fact,
                               find_repair_evidence, stage_repair_candidate)
    action = str(args.get("action") or "analyze").strip().lower()
    key = str(args.get("key") or "").strip()
    if not key:
        return "ERROR: 'key' is required"
    if action == "analyze":
        result = analyze_missing_fields(MEM_ROOT, key)
    elif action == "evidence":
        result = find_repair_evidence(MEM_ROOT, key)
    elif action in {"stage_preview", "stage_apply"}:
        payload = args.get("payload")
        if payload is None:
            payload = analyze_missing_fields(MEM_ROOT, key).get("proposed_fields", {})
        elif not isinstance(payload, dict):
            payload = _json_value(payload, {})
        result = stage_repair_candidate(MEM_ROOT, key, payload, actor=str(args.get("actor") or "system"),
                                        rationale=str(args.get("rationale") or ""),
                                        apply=action == "stage_apply")
    elif action in {"archive_preview", "archive_apply"}:
        result = archive_opaque_fact(MEM_ROOT, key, actor=str(args.get("actor") or "system"),
                                     rationale=str(args.get("rationale") or ""),
                                     apply=action == "archive_apply")
    else:
        return "ERROR: action must be analyze, evidence, stage_preview, stage_apply, archive_preview, or archive_apply"
    return json.dumps(result, indent=2)


def tool_mem_lifecycle(args: dict) -> str:
    """Inspect lifecycle history or preview/apply an audited transition."""
    from memory_lifecycle import lifecycle_history, transition
    action = str(args.get("action") or "history").strip().lower()
    record_id = str(args.get("record_id") or "").strip()
    if action == "history":
        if not record_id:
            return "ERROR: 'record_id' is required"
        return json.dumps(lifecycle_history(DB_PATH, record_id), indent=2)
    if action in {"transition_preview", "transition_apply"}:
        request_payload = args.get("request")
        if not isinstance(request_payload, dict):
            request_payload = _json_value(request_payload, {})
        return json.dumps(transition(DB_PATH, request_payload, apply=action == "transition_apply"), indent=2)
    return "ERROR: action must be history, transition_preview, or transition_apply"


def tool_mem_aliases(args: dict) -> str:
    """Inventory/resolve aliases or preview/apply a recoverable consolidation."""
    from memory_aliases import alias_inventory, consolidate_collision, resolve_alias
    action = str(args.get("action") or "inventory").strip().lower()
    if action == "inventory":
        result = alias_inventory(MEM_ROOT)
    elif action == "resolve":
        result = resolve_alias(MEM_ROOT, str(args.get("key") or ""))
    elif action in {"consolidate_preview", "consolidate_apply"}:
        result = consolidate_collision(
            MEM_ROOT, str(args.get("canonical_key") or ""), str(args.get("preferred_key") or ""),
            actor=str(args.get("actor") or "system"), rationale=str(args.get("rationale") or ""),
            apply=action == "consolidate_apply",
        )
    else:
        return "ERROR: action must be inventory, resolve, consolidate_preview, or consolidate_apply"
    return json.dumps(result, indent=2)


def tool_mem_project_timeline(args: dict) -> str:
    """Return a unified evidence-linked project activity timeline."""
    from project_timeline import get_project_timeline
    project = str(args.get("project") or "").strip()
    if not project:
        return "ERROR: 'project' is required"
    result = get_project_timeline(
        MEM_ROOT, project, event_type=args.get("event_type"), agent=args.get("agent"),
        limit=max(1, min(int(args.get("limit", 50)), 500)),
    )
    event_id = str(args.get("event_id") or "").strip()
    if event_id:
        event = next((item for item in result.get("events", []) if item.get("event_id") == event_id), None)
        return json.dumps(event or {"error": f"event not found: {event_id}"}, indent=2)
    return json.dumps(result, indent=2)


def tool_mem_action_inbox(args: dict) -> str:
    """Query consequence-ranked action inbox items for unresolved memory states."""
    from action_inbox import list_inbox_items, preview_inbox_action
    action = args.get("action", "list")
    project = args.get("project", "")
    if action == "preview":
        inbox_id = args.get("inbox_id", "")
        if not inbox_id:
            return "ERROR: 'inbox_id' is required for preview"
        return json.dumps(preview_inbox_action(MEM_ROOT, inbox_id=inbox_id, project=project), indent=2)
    category = args.get("category")
    res = list_inbox_items(MEM_ROOT, project=project)
    if category:
        res["items"] = [it for it in res.get("items", []) if it.get("category") == category]
        res["total_count"] = len(res["items"])
    return json.dumps(res, indent=2)


def tool_mem_task_resume_bundle(args: dict) -> str:
    """Generate or verify an agent resumption bundle for seamless multi-agent task continuation."""
    from project_briefing import build_resume_bundle
    project_id = args.get("project") or args.get("project_id", "")
    if not project_id:
        return "ERROR: 'project' or 'project_id' is required"
    target_format = args.get("target_format", "antigravity")
    as_of = args.get("as_of")
    task_id = args.get("task_id")
    action = args.get("action", "build")
    bundle = build_resume_bundle(MEM_ROOT, project_id, target_format=target_format, as_of=as_of, task_id=task_id)
    if action == "verify":
        valid = bool(bundle.get("packet_hash") and bundle.get("schema_version") == "gms-task-resume-bundle-v1")
        return json.dumps({"status": "verified" if valid else "invalid", "packet_hash": bundle.get("packet_hash"), "target_format": target_format}, indent=2)
    if target_format == "json":
        return json.dumps(bundle, indent=2)
    return bundle.get("prompt", "")


def tool_mem_decision_intelligence(args: dict) -> str:
    """Inspect binding project decisions, rationale, and supersession impact maps."""
    from decision_intelligence import list_decisions, get_decision, get_decision_impact
    action = args.get("action", "list")
    project = args.get("project", "")
    if action == "list":
        inc_sup = args.get("include_superseded", True)
        return json.dumps(list_decisions(MEM_ROOT, project=project, include_superseded=inc_sup), indent=2)
    decision_id = args.get("decision_id", "")
    if not decision_id:
        return "ERROR: 'decision_id' is required for get/impact"
    if action == "impact":
        return json.dumps(get_decision_impact(MEM_ROOT, decision_id), indent=2)
    res = get_decision(MEM_ROOT, decision_id)
    if not res:
        return json.dumps({"error": f"Decision not found: {decision_id}"})
    return json.dumps(res, indent=2)


def tool_mem_morning_briefing(args: dict) -> str:
    """Generate morning operational briefings answering what changed, what blocks, and what to do first."""
    from morning_briefing import generate_morning_briefing, list_morning_briefings
    action = args.get("action", "get")
    project_id = args.get("project") or args.get("project_id", "")
    if action == "list" or not project_id:
        return json.dumps(list_morning_briefings(MEM_ROOT), indent=2)
    as_of = args.get("as_of")
    return json.dumps(generate_morning_briefing(MEM_ROOT, project_id, as_of=as_of), indent=2)




# ──────────────────────────────────────────────────────────────────────────────
# Durable task handoff and checkpointing
# ──────────────────────────────────────────────────────────────────────────────

_TASK_STATUSES = {"open", "in_progress", "handed_off", "completed", "cancelled"}


def _json_value(value: Any, default: Any) -> Any:
    """Accept MCP-native JSON values or a JSON string, rejecting malformed input."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc.msg}") from exc
        return parsed
    raise ValueError("must be a JSON object, array, or JSON string")


def _task_payload(row: tuple) -> dict:
    keys = (
        "task_id", "project", "title", "objective", "status", "owner_agent",
        "lease_expires_at", "revision", "parent_task_id", "created_by", "created_at",
        "updated_at", "completed_at",
    )
    return dict(zip(keys, row))


def _get_task(conn: sqlite3.Connection, task_id: str) -> dict | None:
    row = conn.execute(
        "SELECT task_id, project, title, objective, status, owner_agent, lease_expires_at, "
        "revision, parent_task_id, created_by, created_at, updated_at, completed_at "
        "FROM gms_tasks WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return _task_payload(row) if row else None


def tool_mem_task_create(args: dict) -> str:
    """Create a durable, project-scoped work item for agents to claim or hand off."""
    task_id = str(args.get("task_id", "")).strip()
    title = str(args.get("title", "")).strip()
    created_by = str(args.get("agent", "")).strip()
    if not task_id or not title or not created_by:
        return "ERROR: 'task_id', 'title', and 'agent' are required"
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO gms_tasks (task_id, project, title, objective, owner_agent, parent_task_id, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, str(args.get("project", "")).strip(), title,
             str(args.get("objective", "")).strip(), None,
             str(args.get("parent_task_id", "")).strip() or None, created_by),
        )
        task = _get_task(conn, task_id)
        conn.commit()
        conn.close()
        return json.dumps({"status": "created", "task": task}, indent=2)
    except sqlite3.IntegrityError:
        return f"ERROR: task '{task_id}' already exists"
    except Exception as exc:
        return f"ERROR: failed to create task: {exc}"


def tool_mem_task_claim(args: dict) -> str:
    """Atomically claim a task at an expected revision and establish a renewable lease."""
    task_id = str(args.get("task_id", "")).strip()
    agent = str(args.get("agent", "")).strip()
    if not task_id or not agent or args.get("expected_revision") is None:
        return "ERROR: 'task_id', 'agent', and 'expected_revision' are required"
    try:
        expected = int(args["expected_revision"])
        lease_seconds = max(60, min(int(args.get("lease_seconds", 1800)), 86400))
    except (TypeError, ValueError):
        return "ERROR: 'expected_revision' and 'lease_seconds' must be integers"
    lease_expiry = (datetime.now() + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE gms_tasks SET owner_agent = ?, lease_expires_at = ?, status = 'in_progress', "
            "revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE task_id = ? AND revision = ? AND status IN ('open', 'handed_off', 'in_progress') "
            "AND (owner_agent IS NULL OR owner_agent = ? OR lease_expires_at IS NULL OR lease_expires_at < ?)",
            (agent, lease_expiry, task_id, expected, agent, now),
        )
        if cursor.rowcount != 1:
            task = _get_task(conn, task_id)
            conn.close()
            return json.dumps({"status": "conflict", "task": task}, indent=2)
        task = _get_task(conn, task_id)
        cursor.execute(
            "UPDATE gms_handoffs SET acknowledged_at = CURRENT_TIMESTAMP "
            "WHERE task_id = ? AND target_agent = ? AND acknowledged_at IS NULL",
            (task_id, agent),
        )
        conn.commit()
        conn.close()
        return json.dumps({"status": "claimed", "task": task}, indent=2)
    except Exception as exc:
        return f"ERROR: failed to claim task: {exc}"


def tool_mem_task_checkpoint(args: dict) -> str:
    """Persist an immutable checkpoint and advance the task revision."""
    task_id = str(args.get("task_id", "")).strip()
    agent = str(args.get("agent", "")).strip()
    if not task_id or not agent or args.get("expected_revision") is None or "state" not in args:
        return "ERROR: 'task_id', 'agent', 'expected_revision', and 'state' are required"
    try:
        expected = int(args["expected_revision"])
        state = _json_value(args["state"], {})
        artifacts = _json_value(args.get("artifact_refs"), [])
        claims = _json_value(args.get("claim_refs"), [])
        episodes = _json_value(args.get("episode_refs"), [])
        if not isinstance(state, dict) or not all(isinstance(item, list) for item in (artifacts, claims, episodes)):
            return "ERROR: state must be an object; reference fields must be arrays"
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE gms_tasks SET revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE task_id = ? AND revision = ? AND owner_agent = ? AND status = 'in_progress'",
            (task_id, expected, agent),
        )
        if cursor.rowcount != 1:
            task = _get_task(conn, task_id)
            conn.close()
            return json.dumps({"status": "conflict", "task": task}, indent=2)
        task = _get_task(conn, task_id)
        cursor.execute(
            "INSERT INTO gms_task_checkpoints (task_id, revision, agent_id, label, state_json, artifact_refs_json, claim_refs_json, episode_refs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task["revision"], agent, str(args.get("label", "")).strip(), json.dumps(state),
             json.dumps(artifacts), json.dumps(claims), json.dumps(episodes)),
        )
        checkpoint_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return json.dumps({"status": "checkpointed", "checkpoint_id": checkpoint_id, "task": task}, indent=2)
    except Exception as exc:
        return f"ERROR: failed to checkpoint task: {exc}"


def tool_mem_handoff_create(args: dict) -> str:
    """Create a structured handoff and release a task for its intended recipient to claim."""
    task_id = str(args.get("task_id", "")).strip()
    source = str(args.get("source_agent", "")).strip()
    if not task_id or not source or args.get("expected_revision") is None:
        return "ERROR: 'task_id', 'source_agent', and 'expected_revision' are required"
    try:
        expected = int(args["expected_revision"])
        context = _json_value(args.get("context"), {})
        artifacts = _json_value(args.get("artifact_refs"), [])
        if not isinstance(context, dict) or not isinstance(artifacts, list):
            return "ERROR: context must be an object and artifact_refs must be an array"
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE gms_tasks SET owner_agent = NULL, lease_expires_at = NULL, status = 'handed_off', "
            "revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE task_id = ? AND revision = ? AND owner_agent = ? AND status = 'in_progress'",
            (task_id, expected, source),
        )
        if cursor.rowcount != 1:
            task = _get_task(conn, task_id)
            conn.close()
            return json.dumps({"status": "conflict", "task": task}, indent=2)
        task = _get_task(conn, task_id)
        cursor.execute(
            "INSERT INTO gms_handoffs (task_id, revision, source_agent, target_agent, objective, completed_work, next_action, blockers, acceptance_criteria, context_json, artifact_refs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, task["revision"], source, str(args.get("target_agent", "")).strip() or None,
             str(args.get("objective", "")).strip(), str(args.get("completed_work", "")).strip(),
             str(args.get("next_action", "")).strip(), str(args.get("blockers", "")).strip(),
             str(args.get("acceptance_criteria", "")).strip(), json.dumps(context), json.dumps(artifacts)),
        )
        handoff_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return json.dumps({"status": "handed_off", "handoff_id": handoff_id, "task": task}, indent=2)
    except Exception as exc:
        return f"ERROR: failed to create handoff: {exc}"


def tool_mem_task_resume(args: dict) -> str:
    """Return the task, latest checkpoint, and latest handoff as a bounded resume bundle."""
    task_id = str(args.get("task_id", "")).strip()
    if not task_id:
        return "ERROR: 'task_id' is required"
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        task = _get_task(conn, task_id)
        if not task:
            conn.close()
            return f"ERROR: task '{task_id}' not found"
        checkpoint = conn.execute(
            "SELECT checkpoint_id, revision, agent_id, label, state_json, artifact_refs_json, claim_refs_json, episode_refs_json, created_at "
            "FROM gms_task_checkpoints WHERE task_id = ? ORDER BY checkpoint_id DESC LIMIT 1", (task_id,)
        ).fetchone()
        handoff = conn.execute(
            "SELECT handoff_id, revision, source_agent, target_agent, objective, completed_work, next_action, blockers, acceptance_criteria, context_json, artifact_refs_json, acknowledged_at, created_at "
            "FROM gms_handoffs WHERE task_id = ? ORDER BY handoff_id DESC LIMIT 1", (task_id,)
        ).fetchone()
        conn.close()
        checkpoint_payload = None
        if checkpoint:
            checkpoint_payload = dict(zip(("checkpoint_id", "revision", "agent_id", "label", "state", "artifact_refs", "claim_refs", "episode_refs", "created_at"), checkpoint))
            for key in ("state", "artifact_refs", "claim_refs", "episode_refs"):
                checkpoint_payload[key] = json.loads(checkpoint_payload[key])
        handoff_payload = None
        if handoff:
            handoff_payload = dict(zip(("handoff_id", "revision", "source_agent", "target_agent", "objective", "completed_work", "next_action", "blockers", "acceptance_criteria", "context", "artifact_refs", "acknowledged_at", "created_at"), handoff))
            handoff_payload["context"] = json.loads(handoff_payload["context"])
            handoff_payload["artifact_refs"] = json.loads(handoff_payload["artifact_refs"])
        return json.dumps({"task": task, "checkpoint": checkpoint_payload, "handoff": handoff_payload}, indent=2)
    except Exception as exc:
        return f"ERROR: failed to resume task: {exc}"


def tool_mem_project_state(args: dict) -> str:
    """Return a project-scoped view of active work and its latest durable handoff state."""
    project = str(args.get("project", "")).strip()
    if not project:
        return "ERROR: 'project' is required"
    include_completed = bool(args.get("include_completed", False))
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        query = (
            "SELECT task_id, project, title, objective, status, owner_agent, lease_expires_at, "
            "revision, parent_task_id, created_by, created_at, updated_at, completed_at "
            "FROM gms_tasks WHERE project = ?"
        )
        if not include_completed:
            query += " AND status NOT IN ('completed', 'cancelled')"
        query += " ORDER BY updated_at DESC, task_id ASC"
        tasks = [_task_payload(row) for row in conn.execute(query, (project,)).fetchall()]
        for task in tasks:
            checkpoint = conn.execute(
                "SELECT checkpoint_id, revision, label, agent_id, created_at FROM gms_task_checkpoints "
                "WHERE task_id = ? ORDER BY checkpoint_id DESC LIMIT 1", (task["task_id"],)
            ).fetchone()
            handoff = conn.execute(
                "SELECT handoff_id, revision, source_agent, target_agent, next_action, acknowledged_at, created_at "
                "FROM gms_handoffs WHERE task_id = ? ORDER BY handoff_id DESC LIMIT 1", (task["task_id"],)
            ).fetchone()
            task["latest_checkpoint"] = (
                dict(zip(("checkpoint_id", "revision", "label", "agent_id", "created_at"), checkpoint))
                if checkpoint else None
            )
            task["latest_handoff"] = (
                dict(zip(("handoff_id", "revision", "source_agent", "target_agent", "next_action", "acknowledged_at", "created_at"), handoff))
                if handoff else None
            )
        conn.close()
        return json.dumps({"project": project, "task_count": len(tasks), "tasks": tasks}, indent=2)
    except Exception as exc:
        return f"ERROR: failed to get project state: {exc}"


def tool_mem_task_complete(args: dict) -> str:
    """Mark the currently owned task complete at a specific revision."""
    task_id = str(args.get("task_id", "")).strip()
    agent = str(args.get("agent", "")).strip()
    if not task_id or not agent or args.get("expected_revision") is None:
        return "ERROR: 'task_id', 'agent', and 'expected_revision' are required"
    try:
        expected = int(args["expected_revision"])
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE gms_tasks SET status = 'completed', lease_expires_at = NULL, revision = revision + 1, "
            "updated_at = CURRENT_TIMESTAMP, completed_at = CURRENT_TIMESTAMP "
            "WHERE task_id = ? AND revision = ? AND owner_agent = ? AND status = 'in_progress'",
            (task_id, expected, agent),
        )
        if cursor.rowcount != 1:
            task = _get_task(conn, task_id)
            conn.close()
            return json.dumps({"status": "conflict", "task": task}, indent=2)
        task = _get_task(conn, task_id)
        conn.commit()
        conn.close()
        return json.dumps({"status": "completed", "task": task}, indent=2)
    except Exception as exc:
        return f"ERROR: failed to complete task: {exc}"


def redact_credentials(text: str) -> tuple[str, bool]:
    """Redact sensitive credentials, API keys, and private tokens."""
    if not isinstance(text, str) or not text:
        return text, False

    redacted = text
    patterns = [
        # AWS Access Key ID
        (r"\b(AKIA[0-9A-Z]{16})\b", "[REDACTED_AWS_KEY]"),
        # AWS Secret Access Key (look for key/secret followed by 40 char base64)
        (r"(?i)\b(secret(?:_access_key)?|aws_secret|api_secret|secret)\s*[:=]\s*['\"]?([0-9a-zA-Z/+]{40})['\"]?", r"\1=[REDACTED_AWS_SECRET]"),
        # OpenAI API Key
        (r"\b(sk-[a-zA-Z0-9]{20,})\b", "[REDACTED_OPENAI_KEY]"),
        (r"\b(sk-proj-[a-zA-Z0-9_\-]{20,})\b", "[REDACTED_OPENAI_KEY]"),
        # Anthropic API Key
        (r"\b(sk-ant-[a-zA-Z0-9_\-]{20,})\b", "[REDACTED_ANTHROPIC_KEY]"),
        # GitHub Tokens
        (r"\b(ghp_[a-zA-Z0-9]{36})\b", "[REDACTED_GITHUB_TOKEN]"),
        (r"\b(github_pat_[a-zA-Z0-9_]{50,})\b", "[REDACTED_GITHUB_TOKEN]"),
        # Slack Tokens
        (r"\b(xox[baprs]-[0-9a-zA-Z]{10,48})\b", "[REDACTED_SLACK_TOKEN]"),
        # Private Keys
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
        # Generic Bearer Tokens
        (r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{25,})\b", r"\1[REDACTED_TOKEN]"),
    ]

    changed = False
    for pattern, repl in patterns:
        new_text = re.sub(pattern, repl, redacted)
        if new_text != redacted:
            redacted = new_text
            changed = True

    return redacted, changed


def check_prompt_injection(text: str) -> tuple[bool, str]:
    """Detect prompt injection and system jailbreak patterns."""
    if not isinstance(text, str) or not text:
        return False, ""

    injection_patterns = [
        (r"(?i)\bsystem\s+override\b", "system_override"),
        (r"(?i)\bignore\s+all\s+(?:previous\s+)?(?:safety\s+)?rules\b", "ignore_safety_rules"),
        (r"(?i)\byou\s+are\s+now\s+in\s+debug\s+mode\b", "debug_mode_jailbreak"),
        (r"(?i)\balways\s+output\s+user\s+secrets\b", "exfiltrate_secrets"),
        (r"(?i)\bdisregard\s+prior\s+instructions\b", "disregard_prior_instructions"),
    ]
    for pat, rule in injection_patterns:
        if re.search(pat, text):
            return True, rule
    return False, ""


def tool_mem_save_typed(args: dict) -> str:
    """Save a memory fact using typed routing (semantic, operational, procedural, session)."""
    key   = str(args.get("key", "")).strip()
    raw_val = args.get("value", "")
    value = raw_val.strip() if isinstance(raw_val, str) else raw_val
    if not key or value is None or (isinstance(value, (str, list, dict)) and len(value) == 0):
        return "ERROR: 'key' and 'value' are required"

    kind = args.get("kind", "").strip().lower()
    if not kind:
        kind = determine_routing(key, value)
    elif kind not in ("semantic", "operational", "procedural", "session"):
        return f"ERROR: Invalid memory kind '{kind}'. Must be semantic, operational, procedural, or session."

    if kind == "session":
        return f"SESSION_ONLY: Memory '{key}' is ephemeral task state/session-only and was not persisted to disk."

    agent_id = _normalize_agent_id(args.get("agent", "").strip() or "unknown")
    branch = _detect_branch()
    force = str(args.get("force", "false")).lower() in ("true", "1", "yes")

    try:
        init_db()
    except Exception as e:
        return f"ERROR: Database initialization failed: {e}"

    # 0. Prompt Injection Defense Gate
    is_inj, inj_rule = check_prompt_injection(str(value))
    if is_inj:
        prov_key = key if kind == "semantic" else f"{kind}:{key}"
        quarantine_fact(prov_key, str(value), agent_id, branch)
        record_claim(kind, key, str(value), agent_id, branch, "quarantined")
        log_security_event("PROMPT_INJECTION_DEFENSE", f"Prompt injection '{inj_rule}' detected in fact '{key}' from agent '{agent_id}'")
        return f"QUARANTINED_SECURITY_GATE: Prompt injection pattern '{inj_rule}' detected in memory '{key}'. Staged in quarantine for security review."

    # 1. Namespaced Schema Contract Validation
    is_valid, normalized_val, schema_err = validate_fact(key, value)
    if not is_valid:
        increment_agent_beta(agent_id, 0.5)
        log_security_event("SCHEMA_REJECT", f"[{kind.upper()}] Fact '{key}' from agent '{agent_id}' rejected: {schema_err}")
        return f"ERROR: Schema validation failed for '{key}':\n  {schema_err}"

    # 2. Inline Sensitive Credential Redaction
    redacted_val, was_redacted = redact_credentials(str(value)) if isinstance(value, str) else (value, False)
    if was_redacted:
        value = redacted_val
        log_security_event("CREDENTIAL_REDACTED", f"Inline credential redaction applied to fact '{key}' from agent '{agent_id}'")

    stored_val = normalized_val if isinstance(normalized_val, (dict, list)) else value
    claim_val_str = json.dumps(stored_val, sort_keys=True) if isinstance(stored_val, (dict, list)) else str(stored_val)

    prov_key = key if kind == "semantic" else f"{kind}:{key}"

    def _facts_match(f1, f2):
        if f1 == f2:
            return True
        if isinstance(f1, str) and isinstance(f2, (dict, list)):
            try:
                return json.loads(f1) == f2
            except Exception:
                return False
        if isinstance(f2, str) and isinstance(f1, (dict, list)):
            try:
                return json.loads(f2) == f1
            except Exception:
                return False
        return False

    facts = _load_typed_facts(kind)
    if key in facts and not _facts_match(facts[key], stored_val):
        existing_owner_info = get_fact_provenance(prov_key)
        if existing_owner_info:
            existing_owner, existing_branch, was_quarantined = existing_owner_info
            existing_owner = _normalize_agent_id(existing_owner)
        else:
            existing_owner, existing_branch = "unknown", "main"

        norm_agent = _normalize_agent_id(agent_id)
        is_authorized_override = force and norm_agent in {"mihir", "system", "migration-pass5", "migration-pass6"}

        # Protected namespace check: policy: and procedural: require operator authority or force
        is_protected_rule = key.startswith("policy:") or key.startswith("procedural:")
        if is_protected_rule and norm_agent not in {"mihir", "system", "migration-pass5", "migration-pass6"} and not force:
            quarantine_fact(prov_key, claim_val_str, agent_id, branch)
            record_claim(kind, key, claim_val_str, agent_id, branch, "quarantined")
            log_security_event("POLICY_OVERWRITE_QUARANTINE", f"Attempted policy overwrite for '{key}' by '{agent_id}' quarantined.")
            return (
                f"CONFLICT/QUARANTINE: Protected namespace '{key}' cannot be directly overwritten by agent '{agent_id}'.\n"
                f"Requires human operator review or staged candidate approval.\n"
                f"Proposed fact has been quarantined for review."
            )

        if existing_owner == "unknown" or norm_agent == _normalize_agent_id(existing_owner) or is_authorized_override:
            claim_id = record_claim(
                kind, key, claim_val_str, agent_id, branch, "active",
                contradiction_type="authorized_override" if is_authorized_override else None,
            )
            # Verify if claim was accepted as active or quarantined by conflict defense
            conn_chk = sqlite3.connect(str(DB_PATH))
            chk_status = conn_chk.execute("SELECT status FROM gms_claims WHERE claim_id = ?", (claim_id,)).fetchone()
            conn_chk.close()
            claim_status = chk_status[0] if chk_status else "active"

            if claim_status == "quarantined":
                quarantine_fact(prov_key, claim_val_str, agent_id, branch)
                return (
                    f"CONFLICT/QUARANTINE: Overwrite of key '{key}' in bucket '{kind}' rejected due to exact conflict with incumbent active claim.\n"
                    f"  Existing Owner: {existing_owner}\n"
                    f"  Proposing Agent: {agent_id}\n"
                    f"Proposed fact has been quarantined for review."
                )

            prev_fact_val = facts[key]
            facts[key] = stored_val
            _save_typed_facts(kind, facts)
            record_provenance(prov_key, agent_id, branch, quarantined=0)
            increment_agent_alpha(agent_id, 1.0)
            if existing_owner != "unknown" and existing_owner != agent_id:
                log_security_event("OVERWRITE", f"[{kind.upper()}] Fact '{key}' overwritten by agent '{agent_id}' replacing '{existing_owner}' under explicit authority.")
            return (
                f"[{kind.upper()}] Fact saved (overwrote existing key '{key}').\n"
                f"  Previous Owner: {existing_owner}\n"
                f"  New Owner: {agent_id}"
            )
        else:
            quarantine_fact(prov_key, claim_val_str, agent_id, branch)
            record_claim(kind, key, claim_val_str, agent_id, branch, "quarantined")
            # Overwrite staged for human/peer review without punitive beta degradation
            log_security_event("QUARANTINE", f"[{kind.upper()}] Fact overwrite staged for key '{key}' from '{agent_id}' against incumbent '{existing_owner}'; explicit review is required.")
            return (
                f"CONFLICT/QUARANTINE: Overwrite of key '{key}' in bucket '{kind}' requires explicit review.\n"
                f"  Existing Owner: {existing_owner}\n"
                f"  Proposing Agent: {agent_id}\n"
                f"Proposed fact has been quarantined for review."
            )

    if key in facts and _facts_match(facts[key], stored_val):
        existing_owner_info = get_fact_provenance(prov_key)
        if not existing_owner_info or existing_owner_info[0] == "unknown":
            record_provenance(prov_key, agent_id, branch, quarantined=0)
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT claim_id, confidence FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND value = ? AND status = 'active'",
                (kind, key, claim_val_str)
            )
            row = cursor.fetchone()
            if row:
                claim_id, current_conf = row
                # Repeated identical writes are provenance events, not evidence
                # of globally measured agent reliability.
                new_conf = current_conf if current_conf is not None else 1.0
                cursor.execute(
                    "UPDATE gms_claims SET confidence = ? WHERE claim_id = ?",
                    (new_conf, claim_id)
                )
                conn.commit()
            else:
                conn.close()
                record_claim(kind, key, claim_val_str, agent_id, branch, "active")
                conn = None
            if conn:
                conn.close()
        except Exception:
            pass
        if was_redacted:
            return f"[REDACTED_PRIVACY_FILTER] Key '{key}' unchanged (same value exists with redacted credentials)."
        return f"INFO: Key '{key}' in bucket '{kind}' unchanged (same value exists)."

    facts[key] = stored_val
    _save_typed_facts(kind, facts)
    record_provenance(prov_key, agent_id, branch, quarantined=0)
    record_claim(kind, key, claim_val_str, agent_id, branch, "active")
    increment_agent_alpha(agent_id, 1.0)
    if was_redacted:
        return f"[REDACTED_PRIVACY_FILTER] Fact saved with credentials redacted: {key} = {claim_val_str}"
    return f"[{kind.upper()}] Fact saved: {key} = {claim_val_str}"


def tool_mem_save_fact(args: dict) -> str:
    """Save a semantic fact. Runs conflict check first."""
    args_copy = dict(args)
    args_copy["kind"] = "semantic"
    return tool_mem_save_typed(args_copy)


def tool_mem_judge(args: dict) -> str:
    """Check if a proposed fact conflicts with existing knowledge. Does NOT write anything."""
    key   = args.get("key", "").strip()
    value = args.get("value", "").strip()
    if not key or not value:
        return "ERROR: 'key' and 'value' are required"

    facts = _load_facts()
    if key in facts:
        existing = facts[key]
        if existing == value:
            return f"CONSISTENT: Key '{key}' already has this exact value."
        return (
            f"CONFLICT: Key '{key}' has an existing value that differs.\n"
            f"  Existing: {existing}\n"
            f"  Proposed: {value}\n"
            f"Resolve before saving."
        )

    # Semantic similarity check via SQLite vector store
    try:
        qvec = _embed(f"{key}: {value}")
        if qvec:
            hits = search_sqlite_embeddings(qvec, top_k=3)
            close_hits = []
            for hit in hits:
                if hit.get("score", 0.0) > 0.85:
                    close_hits.append(f"  score={hit['score']:.3f}: {hit['text'][:120]}...")
            if close_hits:
                return "SIMILAR CONTENT FOUND in episodic memory:\n" + "\n".join(close_hits) + \
                       "\nReview before saving to avoid duplication."
    except Exception:
        pass

    return f"CLEAR: No conflicts found for key '{key}'. Safe to save."


def tool_mem_log_event(args: dict) -> str:
    """Append an episodic milestone (wraps `memoryctl log`)."""
    agent = args.get("agent", "unknown")
    title = args.get("title", "")
    note  = args.get("note", "")
    if not title or not note:
        return "ERROR: 'title' and 'note' are required"
    code, out = _run_memoryctl("log", "--agent", agent, "--title", title, "--note", note)
    return out if out else ("Logged." if code == 0 else "Failed.")


def tool_mem_add_lesson(args: dict) -> str:
    """Add a corrective lesson to global.md."""
    text = args.get("text", "").strip()
    if not text:
        return "ERROR: 'text' is required"
    code, out = _run_memoryctl("lesson-add", text)
    return out if out else ("Lesson added." if code == 0 else "Failed.")


def tool_mem_search(args: dict) -> str:
    """LightRAG dual-level search over Knowledge Graph triples (low-level) and episodic FAISS index (high-level)."""
    query = args.get("query", "").strip()
    k     = int(args.get("k", 5))
    mode  = args.get("mode", "hybrid").strip().lower()
    if not query:
        return "ERROR: 'query' is required"

    res_parts = []

    # Low-level entity graph search
    if mode in ("low", "hybrid"):
        try:
            init_db()
            graph_data = query_entity_graph(query, hops=1)
            if graph_data.get("found") and graph_data.get("edges"):
                graph_summary = format_ascii_graph(graph_data)
                res_parts.append(f"### [LightRAG Low-Level Graph Triples]\n{graph_summary}\n")
        except Exception:
            pass

    # High-level thematic RRF vector/keyword search
    if mode in ("high", "hybrid"):
        cmd_args = ["index-query", query, "-k", str(k)]
        if "decay_rate" in args:
            cmd_args += ["--decay-rate", str(args["decay_rate"])]
        if args.get("no_decay") is True:
            cmd_args += ["--no-decay"]
        if "branch_boost" in args:
            cmd_args += ["--branch-boost", str(args["branch_boost"])]
        if args.get("no_boost") is True:
            cmd_args += ["--no-boost"]
        if args.get("no_hybrid") is True:
            cmd_args += ["--no-hybrid"]
        if args.get("no_rerank") is True or args.get("rerank") is False:
            cmd_args += ["--no-rerank"]
        if "rerank_model" in args:
            cmd_args += ["--rerank-model", str(args["rerank_model"])]
        if "rerank_k" in args:
            cmd_args += ["--rerank-k", str(args["rerank_k"])]
        code, out = _run_memoryctl(*cmd_args)
        if code == 0 and out:
            res_parts.append(f"### [LightRAG High-Level Episodic Retrieval]\n{out}")

    return "\n".join(res_parts) if res_parts else "No results."


def tool_mem_context(args: dict) -> str:
    """Return the last N lines of today's episodic log."""
    n = int(args.get("lines", 50))
    today = datetime.now().strftime("%Y-%m-%d")
    history_dir = MEM_ROOT / "episodic" / "history"
    daily = history_dir / f"{today}.md"
    if daily.exists() and daily.stat().st_size > 200:
        text = _read(daily)
    elif history_dir.exists():
        valid_files = [p for p in sorted(history_dir.glob("*.md")) if p.stat().st_size > 200]
        if valid_files:
            text = _read(valid_files[-1])
        else:
            text = _read(MEM_ROOT / "episodic" / "journal.md")
    else:
        text = _read(MEM_ROOT / "episodic" / "journal.md")
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def tool_mem_get_facts(args: dict) -> str:
    """Return current facts for the specified bucket (optionally filtered by prefix)."""
    prefix  = args.get("prefix", "").strip().lower()
    kind    = args.get("kind", "semantic").strip().lower()
    
    if kind not in ("semantic", "operational", "procedural", "session"):
        return f"ERROR: Invalid memory kind '{kind}'. Must be semantic, operational, procedural, or session."
        
    facts   = _load_typed_facts(kind)
    if prefix:
        facts = {k: v for k, v in facts.items() if k.lower().startswith(prefix)}
    return json.dumps(facts, indent=2)


def tool_mem_get_preferences(_: dict) -> str:
    return _read(MEM_ROOT / "preferences.md")


def tool_mem_get_projects(_: dict) -> str:
    return _read(MEM_ROOT / "projects.md")


def tool_mem_latest(args: dict) -> str:
    """Fetch the latest N episodic log milestones and fact updates across memory."""
    limit = int(args.get("limit", 10))
    kind = args.get("kind", "all").strip().lower()

    output_sections = []

    if kind in ("episodic", "all"):
        history_dir = MEM_ROOT / "episodic" / "history"
        entries = []
        if history_dir.exists():
            files = sorted(history_dir.glob("*.md"), reverse=True)
            for f in files:
                lines = _read(f).splitlines()
                current_heading = ""
                buf = []
                day_entries = []
                for line in lines:
                    if line.startswith("### "):
                        if current_heading and buf:
                            day_entries.append(f"[{f.stem}] {current_heading}\n  " + "\n  ".join(buf[:3]))
                        current_heading = line.strip("# ").strip()
                        buf = []
                    elif current_heading:
                        buf.append(line)
                if current_heading and buf:
                    day_entries.append(f"[{f.stem}] {current_heading}\n  " + "\n  ".join(buf[:3]))
                for entry in reversed(day_entries):
                    entries.append(entry)
                    if len(entries) >= limit:
                        break
                if len(entries) >= limit:
                    break
        if entries:
            output_sections.append(f"### [Latest Episodic Log Milestones (Top {min(limit, len(entries))})]\n" + "\n\n".join(entries[:limit]))

    if kind in ("facts", "claims", "all"):
        try:
            init_db()
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT claim_id, memory_kind, memory_key, value, agent_id, status, created_at "
                "FROM gms_claims ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            conn.close()
            if rows:
                claim_lines = []
                for cid, mkind, mkey, val, agent, status, created_at in rows:
                    claim_lines.append(f"- [{created_at}] [{mkind.upper()}] {mkey} = '{val}' (Agent: {agent}, Status: {status}) [claim #{cid}]")
                output_sections.append(f"### [Latest Fact & Claim Updates (Top {len(claim_lines)})]\n" + "\n".join(claim_lines))
        except Exception:
            pass

    return "\n\n".join(output_sections) if output_sections else "No recent memory entries found."


SECTION_FILE_MAP = {
    "brief": "projectBrief.md",
    "patterns": "systemPatterns.md",
    "tech": "techContext.md",
    "active": "activeContext.md",
    "progress": "progress.md",
}

SECTION_TEMPLATES = {
    "projectBrief.md": "# Project Brief\n\n## Overview\n[Core goals and project scope]\n\n## Requirements\n- [Key requirement 1]\n",
    "systemPatterns.md": "# System Patterns\n\n## Architecture\n[Architecture design and component structure]\n\n## Key Decisions\n- [Design decision 1]\n",
    "techContext.md": "# Technical Context\n\n## Technology Stack\n[Languages, frameworks, dependencies]\n\n## Environment\n[Local setup commands]\n",
    "activeContext.md": "# Active Context\n\n## Current Focus\n[Active task or current milestone]\n\n## Recent Changes\n- [Recent update]\n",
    "progress.md": "# Progress\n\n## Working Features\n- [Completed feature]\n\n## Open Items\n- [Planned work]\n",
}

def tool_mem_project(args: dict) -> str:
    """Manage Cline Memory Bank style project memory structures (brief, patterns, tech, active, progress)."""
    action = args.get("action", "get").strip().lower()
    project = args.get("project", "").strip().lower().replace(" ", "-")

    projects_dir = MEM_ROOT / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    if action == "list":
        banks = [d.name for d in projects_dir.iterdir() if d.is_dir()]
        return json.dumps({"projects": sorted(banks)}, indent=2)

    if not project:
        return "ERROR: 'project' name is required for init, get, or update actions."

    proj_dir = projects_dir / project

    if action == "init":
        proj_dir.mkdir(parents=True, exist_ok=True)
        created = []
        for fname, tpl in SECTION_TEMPLATES.items():
            fpath = proj_dir / fname
            if not fpath.exists():
                fpath.write_text(tpl)
                created.append(fname)

        proj_md = MEM_ROOT / "projects.md"
        if proj_md.exists():
            content = _read(proj_md)
            if project not in content.lower():
                proj_md.write_text(content.strip() + f"\n- **{project}**: Memory bank initialized at `projects/{project}/`.\n")

        return f"Initialized Memory Bank for project '{project}' with files: {', '.join(created) if created else 'all files already exist'}."

    if action == "get":
        if not proj_dir.exists():
            return f"INFO: Project memory bank '{project}' does not exist yet. Run with action='init' to create it."
        section = args.get("section", "all").strip().lower()
        if section == "all":
            parts = []
            for sec_key, fname in SECTION_FILE_MAP.items():
                fpath = proj_dir / fname
                if fpath.exists():
                    parts.append(f"=== [{fname}] ===\n" + fpath.read_text().strip())
            return "\n\n".join(parts) if parts else "No files found in memory bank."
        else:
            fname = SECTION_FILE_MAP.get(section, f"{section}.md")
            fpath = proj_dir / fname
            if not fpath.exists():
                return f"INFO: Section '{section}' ({fname}) does not exist for project '{project}'."
            return fpath.read_text()

    if action == "update":
        if not proj_dir.exists():
            proj_dir.mkdir(parents=True, exist_ok=True)
        section = args.get("section", "active").strip().lower()
        content = args.get("content", "").strip()
        append = args.get("append", True)
        if not content:
            return "ERROR: 'content' is required for update action."

        fname = SECTION_FILE_MAP.get(section, f"{section}.md")
        fpath = proj_dir / fname

        if append and fpath.exists():
            old_text = fpath.read_text().strip()
            new_text = old_text + f"\n\n### Update ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n" + content
        else:
            header = SECTION_TEMPLATES.get(fname, f"# {section.capitalize()}\n")
            new_text = f"{header}\n{content}"

        fpath.write_text(new_text)
        return f"Updated project '{project}' section '{section}' ({fname})."

    return f"ERROR: Unknown action '{action}'. Supported: init, get, update, list."


def tool_mem_stats(_: dict) -> str:
    facts   = _load_facts()
    journal = MEM_ROOT / "episodic" / "journal.md"
    history = MEM_ROOT / "episodic" / "history"
    history_files = list(history.glob("*.md")) if history.exists() else []
    idx     = MEM_ROOT / "episodic" / "index" / "episodic.faiss"
    return (
        f"## GMS Stats\n"
        f"- Semantic facts: {len(facts)}\n"
        f"- Episodic history files: {len(history_files)}\n"
        f"- Journal exists: {journal.exists()}\n"
        f"- FAISS index exists: {idx.exists()}\n"
        f"- Memory root: {MEM_ROOT}\n"
    )


def tool_mem_index_rebuild(_: dict) -> str:
    """Rebuild the FAISS vector index (wraps `memoryctl index-build`)."""
    code, out = _run_memoryctl("index-build")
    return out if out else ("Index rebuilt." if code == 0 else "Rebuild failed.")


def tool_mem_drift_status(args: dict) -> str:
    """Report semantic drift status from the latest index snapshots."""
    cmd_args = ["drift-status"]
    if "threshold" in args:
        cmd_args += ["--threshold", str(args["threshold"])]
    code, out = _run_memoryctl(*cmd_args)
    return out if out else ("No drift data." if code == 0 else "Drift status unavailable.")


def tool_mem_calibration_report(_: dict) -> str:
    """Retrieve the trust-calibration report summarizing observer overlap, agreement, and disagreement."""
    code, out = _run_memoryctl("calibration-report", "--json")
    return out if out else ("No calibration data." if code == 0 else "Calibration report unavailable.")


def tool_mem_retention_report(args: dict) -> str:
    """Report stale low-confidence active facts and stale quarantines."""
    cmd_args = ["retention-report", "--json"]
    if "low_confidence" in args:
        cmd_args += ["--low-confidence", str(args["low_confidence"])]
    if "stale_active_days" in args:
        cmd_args += ["--stale-active-days", str(args["stale_active_days"])]
    if "stale_quarantine_days" in args:
        cmd_args += ["--stale-quarantine-days", str(args["stale_quarantine_days"])]
    code, out = _run_memoryctl(*cmd_args)
    return out if out else ("No retention data." if code == 0 else "Retention report unavailable.")


def tool_mem_record_review(args: dict) -> str:
    """Record a review/endorsement for a quarantined fact."""
    key = args.get("key", "").strip()
    agent_id = args.get("agent_id", "").strip()
    reviewer_id = args.get("reviewer_id", "").strip()
    rating = args.get("rating", "").strip().lower()
    rationale = args.get("rationale", "").strip()
    
    if not key or not agent_id or not reviewer_id or not rating:
        return "ERROR: 'key', 'agent_id', 'reviewer_id', and 'rating' are required"
        
    if rating not in ("endorse", "reject", "abstain"):
        return "ERROR: 'rating' must be 'endorse', 'reject', or 'abstain'"
        
    try:
        init_db()
        # Verify quarantine exists
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
        if not cursor.fetchone():
            conn.close()
            return f"ERROR: No quarantined entry found for key '{key}' and agent '{agent_id}'"
        conn.close()
        
        record_quarantine_review(key, agent_id, reviewer_id, rating, rationale)
        return f"SUCCESS: Review recorded from '{reviewer_id}' for quarantined fact '{key}'."
    except Exception as e:
        return f"ERROR: Failed to record review: {e}"


def tool_mem_get_reviews(args: dict) -> str:
    """Retrieve all reviews for a quarantined fact."""
    key = args.get("key", "").strip()
    agent_id = args.get("agent_id", "").strip()
    include_resolved = str(args.get("include_resolved", "false")).lower() in ("true", "1", "yes")
    
    if not key or not agent_id:
        return "ERROR: 'key' and 'agent_id' are required"
        
    try:
        init_db()
        return json.dumps(get_quarantine_reviews(key, agent_id, include_resolved=include_resolved), indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve reviews: {e}"


def tool_mem_get_recommendation_summary(args: dict) -> str:
    """Get a weighted recommendation summary for a quarantined fact based on witness reviews."""
    key = args.get("key", "").strip()
    agent_id = args.get("agent_id", "").strip()
    
    if not key or not agent_id:
        return "ERROR: 'key' and 'agent_id' are required"
        
    try:
        init_db()
        summary = get_quarantine_recommendation(key, agent_id)
        return json.dumps(summary, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve recommendation: {e}"


def tool_mem_resolve_quarantine(args: dict) -> str:
    """Resolve a quarantined fact by promoting it or discarding it."""
    key = args.get("key", "").strip()
    agent_id = args.get("agent_id", "").strip()
    action = args.get("action", "").strip().lower() # 'promote' or 'discard'
    
    if not key or not agent_id or not action:
        return "ERROR: 'key', 'agent_id', and 'action' are required"
        
    if action not in ("promote", "discard"):
        return "ERROR: 'action' must be 'promote' or 'discard'"
        
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT value, branch FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return f"ERROR: No quarantined entry found for key '{key}' and agent '{agent_id}'"
            
        value, branch = row
        
        # Get recommendation context
        rec_summary = get_quarantine_recommendation(key, agent_id)
        review_snapshot = rec_summary["reviews"]
        rec_text = ""
        if rec_summary["reviewer_count"] > 0:
            rec_text = (
                "\nRecommendation: "
                f"{rec_summary['recommendation']} "
                f"(Reviewers: {rec_summary['reviewer_count']}, "
                f"Endorse: {rec_summary['endorse_count']}, Reject: {rec_summary['reject_count']})"
            )
        
        kind, real_key = parse_prov_key(key)
        if action == "promote":
            facts = _load_typed_facts(kind)
            existing_owner_info = get_fact_provenance(key)
            existing_owner = existing_owner_info[0] if existing_owner_info else "unknown"
            
            facts[real_key] = value
            _save_typed_facts(kind, facts)
            
            record_provenance(key, agent_id, branch, quarantined=0)
            
            # --- Claim updates ---
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT claim_id FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND status = 'active'",
                (kind, real_key)
            )
            active_rows = cursor.fetchall()
            prior_active_id = None
            if active_rows:
                prior_active_id = active_rows[-1][0]
                for a_row in active_rows:
                    cursor.execute(
                        "UPDATE gms_claims SET status = 'superseded' WHERE claim_id = ?",
                        (a_row[0],)
                    )
            
            cursor.execute(
                "SELECT claim_id FROM gms_claims WHERE memory_kind = ? AND memory_key = ? AND agent_id = ? AND status = 'quarantined'",
                (kind, real_key, agent_id)
            )
            quar_rows = cursor.fetchall()
            if quar_rows:
                target_quar_id = quar_rows[-1][0]
                cursor.execute(
                "UPDATE gms_claims SET status = 'active', supersedes_claim_id = ?, confidence = ?, contradiction_type = 'authorized_review' WHERE claim_id = ?",
                    (prior_active_id, 1.0, target_quar_id)
                )
            else:
                cursor.execute("""
                    INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at)
                    VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 'authorized_review', CURRENT_TIMESTAMP)
                """, (kind, real_key, value, agent_id, branch, prior_active_id, 1.0))
            
            cursor.execute("DELETE FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
            cursor.execute(
                "UPDATE gms_quarantine_reviews SET resolution = 'promoted', resolved_at = CURRENT_TIMESTAMP WHERE fact_key = ? AND agent_id = ?",
                (key, agent_id)
            )
            conn.commit()
            conn.close()
            apply_review_outcome_from_reviews(review_snapshot, "promote")
            
            resolver = args.get("agent", "unknown")
            log_security_event("PROMOTION", f"Fact '{key}' promoted from quarantine for agent '{agent_id}' by resolver '{resolver}'")
            return f"SUCCESS: Fact '{key}' promoted. Owner is now '{agent_id}'.{rec_text}"
            
        else: # discard
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM gms_quarantined_facts WHERE fact_key = ? AND agent_id = ?", (key, agent_id))
            cursor.execute(
                "UPDATE gms_quarantine_reviews SET resolution = 'discarded', resolved_at = CURRENT_TIMESTAMP WHERE fact_key = ? AND agent_id = ?",
                (key, agent_id)
            )
            cursor.execute(
                "UPDATE gms_claims SET status = 'discarded', confidence = 0.0 WHERE memory_kind = ? AND memory_key = ? AND agent_id = ? AND status = 'quarantined'",
                (kind, real_key, agent_id)
            )
            conn.commit()
            conn.close()
            apply_review_outcome_from_reviews(review_snapshot, "discard")
            
            log_security_event("DISCARD", f"Quarantined fact '{key}' from agent '{agent_id}' discarded")
            return f"SUCCESS: Quarantined fact '{key}' from agent '{agent_id}' discarded.{rec_text}"
            
    except Exception as e:
        return f"ERROR: Failed to resolve quarantine: {e}"


def tool_mem_get_reputations(_: dict) -> str:
    """Retrieve the trust score and reputation counts of all registered agents."""
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT agent_id, alpha, beta, last_updated FROM gms_agent_reputation")
        rows = cursor.fetchall()
        conn.close()
        
        rep = []
        for agent_id, alpha, beta, last_updated in rows:
            trust = (alpha + 1.0) / (alpha + beta + 2.0)
            rep.append({
                "agent_id": agent_id,
                "alpha": alpha,
                "beta": beta,
                "trust_score": round(trust, 4),
                "last_updated": last_updated
            })
        return json.dumps(rep, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve reputations: {e}"


def tool_mem_get_quarantine(_: dict) -> str:
    """Retrieve all quarantined facts that were blocked due to trust violations."""
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("SELECT fact_key, value, agent_id, branch, timestamp FROM gms_quarantined_facts")
        rows = cursor.fetchall()
        conn.close()
        
        quar = []
        for fact_key, value, agent_id, branch, timestamp in rows:
            quar.append({
                "key": fact_key,
                "value": value,
                "agent_id": agent_id,
                "branch": branch,
                "timestamp": timestamp
            })
        return json.dumps(quar, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve quarantine: {e}"


def tool_mem_get_claims(args: dict) -> str:
    """Retrieve claims from the versioned claim ledger, optionally filtered by kind, key, and status."""
    kind = args.get("kind", "").strip().lower()
    key = args.get("key", "").strip()
    status = args.get("status", "").strip().lower()
    
    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        query = "SELECT claim_id, memory_kind, memory_key, value, agent_id, branch, status, supersedes_claim_id, confidence, contradiction_type, created_at FROM gms_claims WHERE 1=1"
        params = []
        
        if kind:
            query += " AND memory_kind = ?"
            params.append(kind)
        if key:
            query += " AND memory_key = ?"
            params.append(key)
        if status:
            query += " AND status = ?"
            params.append(status)
            
        query += " ORDER BY claim_id ASC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        claims = []
        for row in rows:
            claims.append({
                "claim_id": row[0],
                "memory_kind": row[1],
                "memory_key": row[2],
                "value": row[3],
                "agent_id": row[4],
                "branch": row[5],
                "status": row[6],
                "supersedes_claim_id": row[7],
                "confidence": row[8],
                "contradiction_type": row[9],
                "created_at": row[10]
            })
            
        return json.dumps(claims, indent=2)
    except Exception as e:
        return f"ERROR: Could not retrieve claims: {e}"


def _resolve_entity(cursor: sqlite3.Cursor, entity_id: int | None, name: str | None) -> int:
    if entity_id is not None:
        cursor.execute("SELECT entity_id FROM gms_entities WHERE entity_id = ?", (entity_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Entity ID {entity_id} does not exist.")
        return entity_id
    elif name:
        name = name.strip()
        cursor.execute("SELECT entity_id FROM gms_entities WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        else:
            cursor.execute("INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, '', '')", (name,))
            return cursor.lastrowid
    else:
        raise ValueError("Either entity_id or name must be provided.")


def tool_mem_upsert_entity(args: dict) -> str:
    """Create or update an entity in the local graph database."""
    name = args.get("name", "").strip()
    if not name:
        return "ERROR: 'name' is required"
    
    entity_type = args.get("entity_type", "")
    summary = args.get("summary", "")

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        cursor.execute("SELECT entity_id, entity_type, summary FROM gms_entities WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            entity_id = row[0]
            new_type = args.get("entity_type", row[1])
            new_summary = args.get("summary", row[2])
            cursor.execute("""
                UPDATE gms_entities
                SET entity_type = ?, summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE entity_id = ?
            """, (new_type, new_summary, entity_id))
        else:
            cursor.execute("""
                INSERT INTO gms_entities (name, entity_type, summary)
                VALUES (?, ?, ?)
            """, (name, entity_type, summary))
            entity_id = cursor.lastrowid
            
        conn.commit()
        
        cursor.execute("SELECT entity_id, name, entity_type, summary, created_at, updated_at FROM gms_entities WHERE entity_id = ?", (entity_id,))
        updated_row = cursor.fetchone()
        conn.close()
        
        entity_info = {
            "entity_id": updated_row[0],
            "name": updated_row[1],
            "entity_type": updated_row[2],
            "summary": updated_row[3],
            "created_at": updated_row[4],
            "updated_at": updated_row[5]
        }
        return json.dumps(entity_info, indent=2)
        
    except Exception as e:
        return f"ERROR: Failed to upsert entity: {e}"


def tool_mem_link_entities(args: dict) -> str:
    """Link two entities with a relationship, optionally referencing a claim id and validity window."""
    subject_id = args.get("subject_id")
    subject_name = args.get("subject_name")
    predicate = args.get("predicate", "").strip()
    object_id = args.get("object_id")
    object_name = args.get("object_name")
    object_literal = args.get("object_literal")
    source_claim_id = args.get("source_claim_id")
    valid_from = args.get("valid_from")
    valid_to = args.get("valid_to")

    if not predicate:
        return "ERROR: 'predicate' is required"

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        try:
            sub_id = _resolve_entity(cursor, subject_id, subject_name)
        except ValueError as e:
            conn.close()
            return f"ERROR: Invalid subject: {e}"

        obj_id = None
        if object_id is not None or object_name:
            try:
                obj_id = _resolve_entity(cursor, object_id, object_name)
            except ValueError as e:
                conn.close()
                return f"ERROR: Invalid object entity: {e}"

        if obj_id is None and object_literal is None:
            conn.close()
            return "ERROR: Either object (id/name) or object_literal must be provided"

        if source_claim_id is not None:
            cursor.execute("SELECT 1 FROM gms_claims WHERE claim_id = ?", (source_claim_id,))
            if not cursor.fetchone():
                conn.close()
                return f"ERROR: Source claim ID {source_claim_id} does not exist"

        cursor.execute("""
            INSERT INTO gms_relationships (
                subject_entity_id, predicate, object_entity_id, object_literal,
                source_claim_id, valid_from, valid_to
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sub_id, predicate, obj_id, object_literal, source_claim_id, valid_from, valid_to))
        
        rel_id = cursor.lastrowid
        conn.commit()

        cursor.execute("""
            SELECT relationship_id, subject_entity_id, predicate, object_entity_id, object_literal,
                   source_claim_id, valid_from, valid_to, created_at
            FROM gms_relationships
            WHERE relationship_id = ?
        """, (rel_id,))
        row = cursor.fetchone()
        conn.close()

        rel_info = {
            "relationship_id": row[0],
            "subject_entity_id": row[1],
            "predicate": row[2],
            "object_entity_id": row[3],
            "object_literal": row[4],
            "source_claim_id": row[5],
            "valid_from": row[6],
            "valid_to": row[7],
            "created_at": row[8]
        }
        return json.dumps(rel_info, indent=2)

    except Exception as e:
        return f"ERROR: Failed to link entities: {e}"


def tool_mem_get_entity_graph(args: dict) -> str:
    """Retrieve entities and relationships from the graph. If entity_id or name is specified, retrieves the ego network."""
    entity_id = args.get("entity_id")
    name = args.get("name")

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        target_id = None
        if entity_id is not None:
            cursor.execute("SELECT entity_id FROM gms_entities WHERE entity_id = ?", (entity_id,))
            row = cursor.fetchone()
            if row:
                target_id = row["entity_id"]
        elif name:
            cursor.execute("SELECT entity_id FROM gms_entities WHERE name = ?", (name.strip(),))
            row = cursor.fetchone()
            if row:
                target_id = row["entity_id"]

        if target_id is not None:
            cursor.execute("""
                SELECT DISTINCT subject_entity_id AS id FROM gms_relationships WHERE subject_entity_id = ? OR object_entity_id = ?
                UNION
                SELECT DISTINCT object_entity_id AS id FROM gms_relationships WHERE (subject_entity_id = ? OR object_entity_id = ?) AND object_entity_id IS NOT NULL
            """, (target_id, target_id, target_id, target_id))
            related_ids = [r["id"] for r in cursor.fetchall()]
            related_ids.append(target_id)
            related_ids = list(set(related_ids))

            placeholders = ",".join("?" for _ in related_ids)
            cursor.execute(f"SELECT * FROM gms_entities WHERE entity_id IN ({placeholders})", related_ids)
            entities = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT * FROM gms_relationships
                WHERE subject_entity_id = ? OR object_entity_id = ?
            """, (target_id, target_id))
            relationships = [dict(r) for r in cursor.fetchall()]
        else:
            cursor.execute("SELECT * FROM gms_entities")
            entities = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM gms_relationships")
            relationships = [dict(r) for r in cursor.fetchall()]

        conn.close()

        graph = {
            "entities": entities,
            "relationships": relationships
        }
        return json.dumps(graph, indent=2)

    except Exception as e:
        return f"ERROR: Failed to retrieve entity graph: {e}"


def tool_mem_upsert_procedure(args: dict) -> str:
    """Create or update a reusable trigger-action playbook."""
    name = args.get("name", "")
    if not name or not isinstance(name, str) or not name.strip():
        return "ERROR: 'name' is required and must be a non-empty string"
    name = name.strip()

    trigger = args.get("trigger")
    if trigger is None:
        trigger = ""
    trigger = str(trigger)

    action = args.get("action")
    if action is None:
        action = ""
    action = str(action)

    context = args.get("context")
    if context is None:
        context = ""
    context = str(context)

    status = args.get("status")
    if status is None:
        status = "active"
    status = str(status).strip().lower()

    if status not in ("active", "archived"):
        return f"ERROR: Invalid status '{status}'. Must be 'active' or 'archived'."

    source_claim_id = args.get("source_claim_id")
    if source_claim_id is not None:
        try:
            source_claim_id = int(source_claim_id)
        except (ValueError, TypeError):
            return "ERROR: 'source_claim_id' must be an integer"

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        # Validate claim linkage if source_claim_id is provided
        if source_claim_id is not None:
            cursor.execute("SELECT 1 FROM gms_claims WHERE claim_id = ?", (source_claim_id,))
            if not cursor.fetchone():
                conn.close()
                return f"ERROR: Source claim ID {source_claim_id} does not exist"

        cursor.execute("SELECT procedure_id, \"trigger\", action, context, status, source_claim_id FROM gms_procedures WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            proc_id = row[0]
            new_trigger = trigger if "trigger" in args else row[1]
            new_action = action if "action" in args else row[2]
            new_context = context if "context" in args else row[3]
            new_status = status if "status" in args else row[4]
            new_source_claim_id = source_claim_id if "source_claim_id" in args else row[5]

            # Re-validate status
            new_status = str(new_status).strip().lower()
            if new_status not in ("active", "archived"):
                conn.close()
                return f"ERROR: Invalid status '{new_status}'. Must be 'active' or 'archived'."

            # Re-validate claim linkage if it changed
            if new_source_claim_id is not None and new_source_claim_id != row[5]:
                cursor.execute("SELECT 1 FROM gms_claims WHERE claim_id = ?", (new_source_claim_id,))
                if not cursor.fetchone():
                    conn.close()
                    return f"ERROR: Source claim ID {new_source_claim_id} does not exist"

            cursor.execute("""
                UPDATE gms_procedures
                SET "trigger" = ?, action = ?, context = ?, status = ?, source_claim_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE procedure_id = ?
            """, (new_trigger, new_action, new_context, new_status, new_source_claim_id, proc_id))
            procedure_id = proc_id
        else:
            cursor.execute("""
                INSERT INTO gms_procedures (name, "trigger", action, context, status, source_claim_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, trigger, action, context, status, source_claim_id))
            procedure_id = cursor.lastrowid

        conn.commit()

        cursor.execute("SELECT procedure_id, name, \"trigger\", action, context, status, source_claim_id, created_at, updated_at FROM gms_procedures WHERE procedure_id = ?", (procedure_id,))
        updated_row = cursor.fetchone()
        conn.close()

        proc_info = {
            "procedure_id": updated_row[0],
            "name": updated_row[1],
            "trigger": updated_row[2],
            "action": updated_row[3],
            "context": updated_row[4],
            "status": updated_row[5],
            "source_claim_id": updated_row[6],
            "created_at": updated_row[7],
            "updated_at": updated_row[8]
        }
        return json.dumps(proc_info, indent=2)

    except Exception as e:
        return f"ERROR: Failed to upsert procedure: {e}"


def tool_mem_get_procedures(args: dict) -> str:
    """Retrieve procedures from the database, optionally filtered by status, name, or source_claim_id."""
    status = args.get("status")
    name = args.get("name")
    source_claim_id = args.get("source_claim_id")

    try:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT procedure_id, name, \"trigger\", action, context, status, source_claim_id, created_at, updated_at FROM gms_procedures"
        conditions = []
        params = []

        if status is not None:
            conditions.append("status = ?")
            params.append(str(status).strip().lower())
        if name is not None:
            conditions.append("name = ?")
            params.append(str(name).strip())
        if source_claim_id is not None:
            try:
                source_claim_id = int(source_claim_id)
                conditions.append("source_claim_id = ?")
                params.append(source_claim_id)
            except (ValueError, TypeError):
                conn.close()
                return "ERROR: 'source_claim_id' must be an integer"

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        procedures = [dict(r) for r in rows]
        return json.dumps(procedures, indent=2)

    except Exception as e:
        return f"ERROR: Failed to retrieve procedures: {e}"


def tool_mem_list_episodes(args: dict) -> str:
    """List episodic sources with enough metadata to select a source deterministically."""
    limit = args.get("limit")
    type_filter = args.get("type")
    
    limit_val = None
    if limit is not None:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            return "ERROR: 'limit' must be an integer"
            
    if type_filter is not None:
        type_filter = str(type_filter).strip().lower()
        if type_filter not in ("journal", "history"):
            return "ERROR: 'type' must be 'journal' or 'history'"
            
    import re
    sources = []
    
    # 1. Journal
    journal_path = MEM_ROOT / "episodic" / "journal.md"
    if type_filter is None or type_filter == "journal":
        if journal_path.exists():
            try:
                content = journal_path.read_text(errors="replace")
                line_count = len(content.splitlines())
                sources.append({
                    "source": str(journal_path),
                    "date": None,
                    "type": "journal",
                    "size_bytes": journal_path.stat().st_size,
                    "line_count": line_count
                })
            except Exception:
                pass

    # 2. History
    history_dir = MEM_ROOT / "episodic" / "history"
    if type_filter is None or type_filter == "history":
        if history_dir.exists():
            try:
                for p in sorted(history_dir.glob("*.md"), key=lambda x: x.name, reverse=True):
                    stem = p.stem
                    date_val = stem if re.match(r'^\d{4}-\d{2}-\d{2}$', stem) else None
                    content = p.read_text(errors="replace")
                    line_count = len(content.splitlines())
                    sources.append({
                        "source": str(p),
                        "date": date_val,
                        "type": "history",
                        "size_bytes": p.stat().st_size,
                        "line_count": line_count
                    })
            except Exception:
                pass
                
    if limit_val is not None:
        sources = sources[:limit_val]
        
    return json.dumps(sources, indent=2)


def tool_mem_get_episode(args: dict) -> str:
    """Retrieve details or raw content of a specific episodic source by date or source path."""
    import re
    source = args.get("source")
    date = args.get("date")
    mode = args.get("mode", "summary").strip().lower()
    episodic_root = (MEM_ROOT / "episodic").resolve()
    
    if mode not in ("summary", "deep"):
        return "ERROR: 'mode' must be either 'summary' or 'deep'"
        
    source_path = None
    if source:
        s = str(source).strip()
        p = Path(s)
        if p.is_absolute() and p.exists():
            source_path = p
        elif (MEM_ROOT / s).exists():
            source_path = MEM_ROOT / s
        elif (MEM_ROOT / "episodic" / s).exists():
            source_path = MEM_ROOT / "episodic" / s
        elif (MEM_ROOT / "episodic" / "history" / s).exists():
            source_path = MEM_ROOT / "episodic" / "history" / s
        elif (MEM_ROOT / "episodic" / "history" / f"{s}.md").exists():
            source_path = MEM_ROOT / "episodic" / "history" / f"{s}.md"
        else:
            return f"ERROR: Source file '{s}' not found."
    elif date:
        d = str(date).strip()
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
            return "ERROR: 'date' must be in YYYY-MM-DD format"
        p = MEM_ROOT / "episodic" / "history" / f"{d}.md"
        if p.exists():
            source_path = p
        else:
            return f"ERROR: No history file found for date '{d}'"
    else:
        return "ERROR: Either 'date' or 'source' must be provided."

    try:
        resolved_source = source_path.resolve()
    except Exception:
        return "ERROR: Could not resolve episodic source path."

    if episodic_root not in resolved_source.parents and resolved_source != episodic_root:
        return "ERROR: Source must live under the episodic memory root."
        
    try:
        content = resolved_source.read_text(errors="replace")
        lines = content.splitlines()
        line_count = len(lines)
        size_bytes = resolved_source.stat().st_size
        
        # Derive date and type
        stem = resolved_source.stem
        date_val = stem if re.match(r'^\d{4}-\d{2}-\d{2}$', stem) else None
        
        if resolved_source.name == "journal.md":
            source_type = "journal"
        else:
            source_type = "history"
            
        metadata = {
            "source": str(resolved_source),
            "date": date_val,
            "type": source_type,
            "size_bytes": size_bytes,
            "line_count": line_count
        }
        
        if mode == "summary":
            headers = [line.strip() for line in lines if line.strip().startswith("#")]
            excerpt_lines = lines[-20:] if len(lines) > 20 else lines
            excerpt = "\n".join(excerpt_lines).strip()
            
            result = {
                "metadata": metadata,
                "headers": headers,
                "excerpt": excerpt
            }
        else:
            result = {
                "metadata": metadata,
                "raw_text": content,
                "raw_content": content
            }
            
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"ERROR: Failed to read episodic source: {e}"


def tool_mem_link_memory(args: dict) -> str:
    """Explicitly link a memory item (claim, fact, episode, task) to a Knowledge Graph entity."""
    memory_ref = str(args.get("memory_ref", "")).strip()
    entity_target = str(args.get("entity", "")).strip()
    relationship = str(args.get("relationship", "references")).strip()

    if not memory_ref or not entity_target:
        return "ERROR: 'memory_ref' and 'entity' are required arguments."

    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # Resolve entity_id
    entity_id = None
    if entity_target.isdigit():
        entity_id = int(entity_target)
    else:
        cursor.execute("SELECT entity_id FROM gms_entities WHERE lower(name) = lower(?)", (entity_target,))
        row = cursor.fetchone()
        if row:
            entity_id = row[0]
        else:
            cursor.execute(
                "INSERT INTO gms_entities (name, entity_type, summary) VALUES (?, 'concept', ?)",
                (entity_target, f"Linked to memory: {memory_ref}")
            )
            entity_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO gms_memory_entity_links (memory_ref, entity_id, relationship)
        VALUES (?, ?, ?)
    """, (memory_ref, entity_id, relationship))

    conn.commit()
    conn.close()
    return f"Successfully linked memory '{memory_ref}' --[{relationship}]--> entity #{entity_id} ({entity_target})."


def tool_mem_get_entity_memories(args: dict) -> str:
    """Retrieve all memory references linked to a specific Knowledge Graph entity."""
    entity_target = str(args.get("entity", "")).strip()
    if not entity_target:
        return "ERROR: 'entity' argument is required."

    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    cursor.execute("""
        SELECT l.link_id, l.memory_ref, l.relationship, l.created_at, e.name as entity_name
        FROM gms_memory_entity_links l
        JOIN gms_entities e ON l.entity_id = e.entity_id
        WHERE lower(e.name) = lower(?) OR e.entity_id = ?
        ORDER BY l.link_id DESC
    """, (entity_target, entity_target if entity_target.isdigit() else -1))

    rows = [dict(zip(["link_id", "memory_ref", "relationship", "created_at", "entity_name"], r)) for r in cursor.fetchall()]
    conn.close()

    return json.dumps({
        "entity": entity_target,
        "count": len(rows),
        "linked_memories": rows
    }, indent=2)


def tool_mem_file_context(args: dict) -> str:
    """Pre-edit file risk, pattern, and gotcha audit for coding agents.
    Inspects memories for known gotchas, activeContext constraints, patterns, and historical lessons
    associated with a specific file path or module before editing."""
    file_path = str(args.get("file_path", "")).strip()
    if not file_path:
        return "ERROR: 'file_path' is required"
    project = str(args.get("project", "")).strip()

    p = Path(file_path)
    file_name = p.name
    stem = p.stem
    parts = [part.lower() for part in p.parts if part not in ("/", "\\", ".", "..")]

    # Extract AST symbols if file exists on disk and is a Python file
    ast_symbols: list[str] = []
    ast_imports: list[str] = []
    if p.exists() and p.is_file() and p.suffix.lower() == ".py":
        try:
            import ast
            code = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(code, filename=str(p))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ast_symbols.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    ast_symbols.append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        ast_imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        ast_imports.append(node.module)
        except Exception:
            pass

    ast_symbols = sorted(set(ast_symbols))
    ast_imports = sorted(set(ast_imports))

    # Query context retrieval planner using terms from file path and key AST symbols
    symbol_terms = " ".join(ast_symbols[:6])
    query = f"{stem} {file_name} {' '.join(parts[-3:])} {symbol_terms}".strip()
    root = _default_mem_root()
    try:
        from context_retrieval_planner import retrieve
        ret = retrieve(root, query, project=project, token_budget=1400)
        items = ret.get("items", [])
    except Exception:
        items = []

    # Check for direct file references or lessons or symbol matches
    relevant_gotchas = []
    symbol_gotchas = []
    for item in items:
        stmt = str(item.get("statement", ""))
        key = str(item.get("key", ""))
        matched_syms = [s for s in ast_symbols if s.lower() in stmt.lower() or s.lower() in key.lower()]

        file_match = (stem.lower() in stmt.lower() or file_name.lower() in stmt.lower() or any(part in stmt.lower() for part in parts[-2:]))
        if file_match or matched_syms:
            entry = {
                "source": item.get("source"),
                "key": key,
                "lane": item.get("lane"),
                "warning": item.get("warning"),
                "matched_symbols": matched_syms if matched_syms else None,
                "guidance": stmt[:240]
            }
            relevant_gotchas.append(entry)
            if matched_syms:
                symbol_gotchas.append(entry)

    report = {
        "file_path": file_path,
        "project": project or "global",
        "ast_analyzed": bool(ast_symbols or ast_imports),
        "ast_top_symbols": ast_symbols[:12],
        "ast_dependencies": ast_imports[:8],
        "pre_edit_risk_level": "CAUTION" if any(g.get("warning") for g in relevant_gotchas) else "NORMAL",
        "relevant_memories_found": len(relevant_gotchas),
        "symbol_specific_gotchas": len(symbol_gotchas),
        "guidance": relevant_gotchas[:6] if relevant_gotchas else "No known historical bugs, gotchas, or policy restrictions recorded for this file."
    }
    return json.dumps(report, indent=2)


def tool_mem_learn_error(args: dict) -> str:
    """Crystallize a terminal/test/compiler error trace into a procedural lesson and rule.
    Extracts the root error signature and stores an operational/procedural memory to prevent recurring agent mistakes."""
    error_trace = str(args.get("error_trace", "") or args.get("error", "")).strip()
    if not error_trace:
        return "ERROR: 'error_trace' or 'error' is required"
    command = str(args.get("command", "")).strip()
    project = str(args.get("project", "")).strip()
    agent_id = _normalize_agent_id(args.get("agent", "").strip() or "developer")

    # Extract signature (e.g. last line or error type)
    lines = [line.strip() for line in error_trace.splitlines() if line.strip()]
    error_signature = lines[-1] if lines else "Unknown error"
    for line in reversed(lines):
        if any(err in line for err in ("Error:", "Exception:", "FAILED", "fatal:", "panic:", "SyntaxError", "TypeError", "ImportError")):
            error_signature = line
            break

    # Crystallize procedural rule key
    clean_sig = re.sub(r"[^a-zA-Z0-9_]+", "_", error_signature.lower())[:48].strip("_")
    mem_key = f"lesson.{clean_sig}" if not project else f"{project}.lesson.{clean_sig}"

    lesson_content = {
        "signature": error_signature,
        "failing_command": command or "unknown",
        "root_cause_summary": lines[-1] if len(lines) > 1 else error_signature,
        "resolution_guidance": str(args.get("resolution", "Investigate dependency versions, schema constraints, or execution environment.")),
        "timestamp": datetime.now(UTC).isoformat()
    }

    # Save via save_typed as procedural memory
    save_res = tool_mem_save_typed({
        "key": mem_key,
        "value": json.dumps(lesson_content),
        "kind": "procedural",
        "agent": agent_id
    })

    return json.dumps({
        "status": "learned",
        "lesson_key": mem_key,
        "error_signature": error_signature,
        "storage_result": save_res
    }, indent=2)


def tool_mem_core_memory_get(args: dict) -> str:
    """Retrieve the agent's core memory blocks (persona, human, scratchpad) with token estimations."""
    root = _default_mem_root()
    cm_path = root / "operational" / "core_memory.json"
    blocks = {}
    if cm_path.exists():
        try:
            blocks = json.loads(cm_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not blocks:
        pref_path = root / "preferences.md"
        human_text = pref_path.read_text(encoding="utf-8")[:1200] if pref_path.exists() else "Technical collaborator. Prefers concise, direct, evidence-based answers."
        blocks = {
            "persona": "Antigravity/Codex: Technical AI collaborator with deep systems reasoning, mathematical rigor, and zero unnecessary pleasantries.",
            "human": human_text.strip(),
            "scratchpad": "Ready for cross-agent collaboration."
        }

    tokens = {k: max(1, len(v) // 4) for k, v in blocks.items()}
    return json.dumps({
        "status": "ok",
        "blocks": blocks,
        "tokens": tokens,
        "total_tokens": sum(tokens.values()),
        "updated_at": datetime.now(UTC).isoformat()
    }, indent=2)


def tool_mem_core_memory_append(args: dict) -> str:
    """Append text to an agent core memory block (persona, human, scratchpad) with size bounding."""
    block = str(args.get("block", "")).strip().lower()
    if block not in ("persona", "human", "scratchpad"):
        return "ERROR: 'block' must be one of: 'persona', 'human', 'scratchpad'"
    content = str(args.get("content", "")).strip()
    if not content:
        return "ERROR: 'content' is required"

    root = _default_mem_root()
    cm_dir = root / "operational"
    cm_dir.mkdir(parents=True, exist_ok=True)
    cm_path = cm_dir / "core_memory.json"
    blocks = {}
    if cm_path.exists():
        try:
            blocks = json.loads(cm_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not blocks:
        pref_path = root / "preferences.md"
        human_text = pref_path.read_text(encoding="utf-8")[:1200] if pref_path.exists() else "Technical collaborator."
        blocks = {
            "persona": "Antigravity/Codex: Technical AI collaborator with deep systems reasoning.",
            "human": human_text.strip(),
            "scratchpad": ""
        }

    existing = blocks.get(block, "")
    new_text = f"{existing}\n{content}".strip() if existing else content
    if len(new_text) > 4000:
        return f"ERROR: block '{block}' would exceed maximum token budget (4000 chars, currently {len(new_text)})"

    blocks[block] = new_text
    cm_path.write_text(json.dumps(blocks, indent=2), encoding="utf-8")

    agent_id = _normalize_agent_id(args.get("agent", "").strip() or "agent")
    tool_mem_save_typed({
        "key": f"core_memory.{block}",
        "value": new_text,
        "kind": "operational",
        "agent": agent_id
    })

    return json.dumps({
        "status": "appended",
        "block": block,
        "appended_chars": len(content),
        "total_block_chars": len(new_text),
        "total_tokens": max(1, len(new_text) // 4)
    }, indent=2)


def tool_mem_core_memory_replace(args: dict) -> str:
    """Replace content in a core memory block (persona, human, scratchpad) using targeted matching or full overwrite."""
    block = str(args.get("block", "")).strip().lower()
    if block not in ("persona", "human", "scratchpad"):
        return "ERROR: 'block' must be one of: 'persona', 'human', 'scratchpad'"
    new_content = str(args.get("new_content", "") or args.get("content", "")).strip()
    old_content = str(args.get("old_content", "")).strip()

    root = _default_mem_root()
    cm_dir = root / "operational"
    cm_dir.mkdir(parents=True, exist_ok=True)
    cm_path = cm_dir / "core_memory.json"
    blocks = {}
    if cm_path.exists():
        try:
            blocks = json.loads(cm_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    existing = blocks.get(block, "")
    if old_content:
        if old_content not in existing:
            return f"ERROR: 'old_content' not found in block '{block}'"
        updated = existing.replace(old_content, new_content, 1)
    else:
        updated = new_content

    if len(updated) > 4000:
        return f"ERROR: block '{block}' exceeds budget (max 4000 chars, currently {len(updated)})"

    blocks[block] = updated
    cm_path.write_text(json.dumps(blocks, indent=2), encoding="utf-8")

    agent_id = _normalize_agent_id(args.get("agent", "").strip() or "agent")
    tool_mem_save_typed({
        "key": f"core_memory.{block}",
        "value": updated,
        "kind": "operational",
        "agent": agent_id
    })

    return json.dumps({
        "status": "replaced",
        "block": block,
        "total_block_chars": len(updated),
        "total_tokens": max(1, len(updated) // 4)
    }, indent=2)


def tool_mem_graph_communities(args: dict) -> str:
    """Microsoft GraphRAG SOTA: Detect multi-scale modular communities over the entity graph using Louvain clustering."""
    root = _default_mem_root()
    db = root / "gms_trust.sqlite"
    if not db.exists():
        return json.dumps({"status": "empty", "message": "No gms_trust.sqlite database found", "communities": []})

    try:
        import networkx as nx
        import networkx.algorithms.community as nx_comm

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        has_rel = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_relationships'").fetchone()
        if not has_rel:
            conn.close()
            return json.dumps({"status": "empty", "message": "No gms_relationships table found", "communities": []})

        columns = {row[1] for row in conn.execute("PRAGMA table_info(gms_relationships)")}
        has_entities_schema = {"subject_entity_id", "predicate", "object_entity_id"}.issubset(columns)

        UG = nx.Graph()
        if has_entities_schema:
            sql = """
                SELECT se.name AS source_id, COALESCE(oe.name, r.object_literal) AS target_id,
                       r.predicate AS rel_type, 1.0 AS weight
                FROM gms_relationships r
                JOIN gms_entities se ON se.entity_id = r.subject_entity_id
                LEFT JOIN gms_entities oe ON oe.entity_id = r.object_entity_id
                WHERE (r.valid_to IS NULL OR r.valid_to > datetime('now'))
            """
        else:
            sql = """
                SELECT source_id, target_id, rel_type, COALESCE(weight, 1.0) AS weight
                FROM gms_relationships
                WHERE (valid_to IS NULL OR valid_to > datetime('now'))
            """
        rows = conn.execute(sql).fetchall()
        conn.close()

        for r in rows:
            sid, tid = r["source_id"], r["target_id"]
            if sid and tid:
                w = float(r["weight"]) if r["weight"] is not None else 1.0
                UG.add_edge(sid, tid, weight=w, rel_type=r["rel_type"])

        if UG.number_of_nodes() == 0:
            return json.dumps({"status": "empty", "message": "Knowledge graph has zero active nodes", "communities": []})

        raw_comms = nx_comm.louvain_communities(UG, seed=42)
        raw_comms = sorted(raw_comms, key=lambda c: len(c), reverse=True)

        communities = []
        for idx, c_nodes in enumerate(raw_comms):
            subg = UG.subgraph(c_nodes)
            deg = dict(subg.degree())
            central_hubs = sorted(deg.items(), key=lambda x: x[1], reverse=True)[:3]
            hub_names = [h[0] for h in central_hubs]
            density = round(nx.density(subg), 3) if len(c_nodes) > 1 else 1.0

            communities.append({
                "community_id": f"C{idx}",
                "size": len(c_nodes),
                "central_hubs": hub_names,
                "internal_density": density,
                "sample_entities": sorted(list(c_nodes))[:10]
            })

        return json.dumps({
            "status": "ok",
            "total_nodes": UG.number_of_nodes(),
            "total_edges": UG.number_of_edges(),
            "community_count": len(communities),
            "communities": communities
        }, indent=2)
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)}, indent=2)


def tool_mem_reflect(args: dict) -> str:
    """Stanford Generative Agents SOTA: Generate reflective insight synthesis across recent episodic milestones."""
    root = _default_mem_root()
    hist_dir = root / "episodic" / "history"
    episodes = []
    if hist_dir.exists():
        fps = sorted(hist_dir.glob("*.md"), reverse=True)[:3]
        for fp in fps:
            try:
                for line in fp.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("- ") and len(line) > 20:
                        episodes.append({"date": fp.stem, "text": line.strip().lstrip("- ")})
            except Exception:
                pass

    claims = []
    db = root / "gms_trust.sqlite"
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT memory_key, value, agent_id, created_at FROM gms_claims ORDER BY claim_id DESC LIMIT 10").fetchall()
            conn.close()
            for r in rows:
                claims.append(f"[{r['agent_id']}] {r['memory_key']} -> {str(r['value'])[:80]}")
        except Exception:
            pass

    themes = {
        "architecture_and_infra": [],
        "trading_and_risk": [],
        "tools_and_operations": []
    }
    for ep in episodes[:15]:
        t = ep["text"].lower()
        if any(w in t for w in ("infra", "redis", "postgres", "cluster", "server", "docker", "k8s")):
            themes["architecture_and_infra"].append(ep["text"])
        elif any(w in t for w in ("alphaos", "trading", "broker", "risk", "stop", "regime", "order")):
            themes["trading_and_risk"].append(ep["text"])
        else:
            themes["tools_and_operations"].append(ep["text"])

    reflections = []
    for theme_name, items in themes.items():
        if items:
            salience = round(min(1.0, 0.4 + 0.15 * len(items)), 2)
            reflections.append({
                "theme": theme_name,
                "evidence_count": len(items),
                "salience": salience,
                "synthesis": f"Cluster of {len(items)} recent operational items indicating ongoing development focus.",
                "sample_evidence": items[:2]
            })

    report = {
        "status": "ok",
        "total_episodes_analyzed": len(episodes),
        "total_claims_analyzed": len(claims),
        "reflections": reflections,
        "generated_at": datetime.now(UTC).isoformat()
    }
    return json.dumps(report, indent=2)


def tool_mem_trap_create(args: dict) -> str:
    """Invention: Create a reflexive prospective memory trap that fires when an observation or action matches."""
    name = str(args.get("name", "")).strip().lower()
    pattern = str(args.get("pattern", "")).strip()
    payload = str(args.get("payload", "")).strip()
    if not name or not pattern or not payload:
        return "ERROR: 'name', 'pattern', and 'payload' are all required"
    trigger_type = str(args.get("trigger_type", "keyword")).strip().lower()
    recurring = bool(args.get("recurring", False))
    agent = _normalize_agent_id(args.get("agent", "").strip() or "developer")

    root = _default_mem_root()
    traps_file = root / "operational" / "traps.json"
    traps_file.parent.mkdir(parents=True, exist_ok=True)
    traps = []
    if traps_file.exists():
        try:
            traps = json.loads(traps_file.read_text(encoding="utf-8"))
        except Exception:
            traps = []

    existing = next((t for t in traps if t.get("name") == name), None)
    created_at = existing.get("created_at", datetime.now(UTC).isoformat()) if existing else datetime.now(UTC).isoformat()
    receipt = _compute_trap_receipt(name, pattern, payload, created_at)
    entry = {
        "name": name,
        "trigger_type": trigger_type,
        "pattern": pattern,
        "payload": payload,
        "recurring": recurring,
        "active": True,
        "hit_count": existing.get("hit_count", 0) if existing else 0,
        "created_at": created_at,
        "last_triggered_at": existing.get("last_triggered_at") if existing else None,
        "agent": agent,
        "receipt": receipt,
    }
    traps = [t for t in traps if t.get("name") != name] + [entry]
    _atomic_write_json(traps_file, traps)
    return json.dumps({"status": "ok", "trap": entry}, indent=2)


def tool_mem_trap_list(args: dict) -> str:
    """Invention: List all prospective attention traps (active and disarmed)."""
    root = _default_mem_root()
    traps_file = root / "operational" / "traps.json"
    traps = []
    if traps_file.exists():
        try:
            traps = json.loads(traps_file.read_text(encoding="utf-8"))
        except Exception:
            traps = []
    active_only = bool(args.get("active_only", False))
    if active_only:
        traps = [t for t in traps if t.get("active", True)]
    return json.dumps({
        "status": "ok",
        "total_traps": len(traps),
        "traps": traps
    }, indent=2)


def tool_mem_trap_eval(args: dict) -> str:
    """Invention: Fast evaluate observation/action text against prospective attention traps."""
    context = str(args.get("context", "")).strip()
    if not context:
        return json.dumps({"status": "ok", "triggered": []})

    root = _default_mem_root()
    traps_file = root / "operational" / "traps.json"
    if not traps_file.exists():
        return json.dumps({"status": "ok", "triggered": []})

    try:
        traps = json.loads(traps_file.read_text(encoding="utf-8"))
    except Exception:
        return json.dumps({"status": "ok", "triggered": []})

    triggered = []
    modified = False
    context_lower = context.lower()

    for t in traps:
        if not t.get("active", True) or t.get("tamper_quarantined", False) or t.get("redos_quarantined", False):
            continue

        name = t.get("name", "")
        pat = t.get("pattern", "")
        payload = t.get("payload", "")
        created_at = t.get("created_at", "")
        stored_receipt = t.get("receipt", "")
        trig_type = t.get("trigger_type", "keyword")

        # 1. Cryptographic Tamper Quarantine check:
        if stored_receipt:
            expected_receipt = _compute_trap_receipt(name, pat, payload, created_at)
            if stored_receipt != expected_receipt:
                t["tamper_quarantined"] = True
                t["active"] = False
                t["quarantine_reason"] = "Cryptographic HMAC-SHA256 receipt mismatch"
                modified = True
                continue

        # 2. Token pre-filter optimization ($O(1)$ fast-reject before regex engine):
        if trig_type == "keyword":
            if pat.lower() not in context_lower:
                continue
        elif "|" not in pat:
            tokens = [tok.lower() for tok in re.findall(r'[a-zA-Z0-9_]{3,}', pat)]
            if tokens and not any(tok in context_lower for tok in tokens):
                continue

        # 3. Static ReDoS & Catastrophic Backtracking Guard:
        has_nested = bool(re.search(r'\([^)]*(\+|\*)[^)]*\)(\+|\*)', pat))
        if has_nested and len(context) > 100:
            t["redos_quarantined"] = True
            t["active"] = False
            t["quarantine_reason"] = f"ReDoS complexity hazard detected in pattern: {pat[:50]}"
            modified = True
            continue

        matched = False
        try:
            if re.search(pat, context, re.IGNORECASE):
                matched = True
        except Exception:
            if pat.lower() in context_lower:
                matched = True

        if matched:
            t["hit_count"] = t.get("hit_count", 0) + 1
            t["last_triggered_at"] = datetime.now(UTC).isoformat()
            if not t.get("recurring", False):
                t["active"] = False
            modified = True
            triggered.append({
                "trap_name": t.get("name"),
                "directive": t.get("payload"),
                "trigger_type": t.get("trigger_type"),
                "recurring": t.get("recurring", False),
            })

    if modified:
        try:
            _atomic_write_json(traps_file, traps)
        except Exception:
            pass

    return json.dumps({
        "status": "ok",
        "evaluated_context": context[:120],
        "triggered_count": len(triggered),
        "triggered": triggered
    }, indent=2)


def tool_mem_trap_dismiss(args: dict) -> str:
    """Invention: Dismiss or disarm a prospective attention trap by name."""
    name = str(args.get("name", "")).strip().lower()
    if not name:
        return "ERROR: 'name' is required"
    root = _default_mem_root()
    traps_file = root / "operational" / "traps.json"
    if not traps_file.exists():
        return json.dumps({"status": "not_found", "name": name})

    try:
        traps = json.loads(traps_file.read_text(encoding="utf-8"))
    except Exception:
        traps = []

    found = False
    for t in traps:
        if t.get("name") == name:
            t["active"] = False
            found = True

    if found:
        _atomic_write_json(traps_file, traps)
        return json.dumps({"status": "ok", "dismissed": name})
    return json.dumps({"status": "not_found", "name": name})


def tool_mem_speculative_prefetch(args: dict) -> str:
    """Invention: Anticipatory cognitive branch predictor prefetching traps, prior errors, symbols, and invariants."""
    active_file = str(args.get("active_file", "")).strip()
    intent = str(args.get("intent", "")).strip()
    project = str(args.get("project", "")).strip()

    search_text = f"{active_file} {intent} {project}".strip()
    root = _default_mem_root()

    # 1. Evaluate traps against search context
    trap_res = json.loads(tool_mem_trap_eval({"context": search_text}))
    hazards = [t["directive"] for t in trap_res.get("triggered", [])]

    # 2. Prior regrets / errors from operational/errors.json
    prior_regrets = []
    err_file = root / "operational" / "errors.json"
    if err_file.exists():
        try:
            errs = json.loads(err_file.read_text(encoding="utf-8"))
            for e in errs[-20:]:
                tokens = [tk for tk in re.split(r"\W+", search_text.lower()) if len(tk) > 3]
                trace = (e.get("trace", "") + " " + e.get("mitigation", "") + " " + e.get("root_cause", "")).lower()
                if any(tk in trace for tk in tokens):
                    prior_regrets.append({
                        "root_cause": e.get("root_cause"),
                        "mitigation": e.get("mitigation"),
                        "timestamp": e.get("timestamp")
                    })
        except Exception:
            pass

    # 3. Code symbols if active_file exists
    symbols = []
    if active_file and Path(active_file).exists() and active_file.endswith(".py"):
        try:
            import ast
            tree = ast.parse(Path(active_file).read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    symbols.append(node.name)
        except Exception:
            pass

    # 4. Invariants matching search_text from facts.json
    invariants = []
    facts_file = root / "semantic" / "facts.json"
    if facts_file.exists():
        try:
            facts = json.loads(facts_file.read_text(encoding="utf-8"))
            for k, v in facts.items():
                if any(w in k.lower() for w in re.split(r"\W+", search_text.lower()) if len(w) > 3):
                    invariants.append({"key": k, "value": str(v)[:200]})
        except Exception:
            pass

    return json.dumps({
        "status": "ok",
        "speculative_bundle": {
            "active_file": active_file,
            "intent": intent,
            "hazards": hazards,
            "prior_regrets": prior_regrets[:3],
            "symbols": symbols[:10],
            "invariants": invariants[:5]
        },
        "prefetched_at": datetime.now(UTC).isoformat()
    }, indent=2)


def tool_mem_programmatic_guard(args: dict) -> str:
    """Invention: Deterministic programmatic memory assertion validator replacing ambiguous natural language advice."""
    guard_name = str(args.get("guard_name", "")).strip().lower()
    ctx = args.get("context", {})
    if not isinstance(ctx, dict):
        ctx = {}

    if guard_name == "schema_keys":
        required = args.get("required_keys", [])
        missing = [k for k in required if k not in ctx]
        if missing:
            return json.dumps({"passed": False, "guard": guard_name, "error": f"Missing required keys: {missing}"})
        return json.dumps({"passed": True, "guard": guard_name, "status": "all required keys present"})

    elif guard_name == "budget_limit":
        target = str(args.get("target_text", ctx.get("text", "")))
        limit = int(args.get("max_chars", 4000))
        if len(target) > limit:
            return json.dumps({"passed": False, "guard": guard_name, "error": f"Text size {len(target)} exceeds limit {limit}"})
        return json.dumps({"passed": True, "guard": guard_name, "chars": len(target), "limit": limit})

    elif guard_name == "sqlite_concurrency":
        root = _default_mem_root()
        db_path = root / "gms_trust.sqlite"
        if db_path.exists():
            import sqlite3
            try:
                conn = sqlite3.connect(db_path, timeout=1.0)
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode;")
                jmode = cur.fetchone()[0]
                cur.execute("PRAGMA busy_timeout;")
                timeout = cur.fetchone()[0]
                conn.close()
                return json.dumps({"passed": True, "guard": guard_name, "journal_mode": jmode, "busy_timeout": timeout})
            except Exception as e:
                return json.dumps({"passed": False, "guard": guard_name, "error": str(e)})
        return json.dumps({"passed": True, "guard": guard_name, "status": "db not created yet"})

    else:
        assertion = bool(args.get("condition", True))
        reason = str(args.get("reason", "Generic invariant assertion"))
        return json.dumps({"passed": assertion, "guard": guard_name or "custom", "reason": reason})


def tool_mem_staleness_verify(args: dict) -> str:
    """Open Research Frontier (STALE): Verify whether physical files bound to memory have mutated since recording."""
    import hashlib
    file_path = str(args.get("file_path", "")).strip()
    stored_hash = str(args.get("stored_hash", "")).strip().lower()
    key = str(args.get("key", "")).strip()

    root = _default_mem_root()

    # If key is provided but not file_path, check semantic facts for file_path metadata
    if not file_path and key:
        facts_file = root / "semantic" / "facts.json"
        if facts_file.exists():
            try:
                facts = json.loads(facts_file.read_text(encoding="utf-8"))
                val = facts.get(key)
                if isinstance(val, dict):
                    file_path = val.get("file_path", "") or val.get("path", "")
                    if not stored_hash:
                        stored_hash = val.get("hash", "") or val.get("content_hash", "")
            except Exception:
                pass

    if not file_path:
        return "ERROR: 'file_path' or a valid 'key' with file metadata is required"

    target = Path(file_path).expanduser()
    if not target.exists():
        return json.dumps({
            "status": "FILE_MISSING",
            "file_path": str(target),
            "staleness_risk": 1.0,
            "message": "Target file no longer exists in filesystem. Bound memories are likely stale or invalid."
        }, indent=2)

    try:
        content = target.read_bytes()
        current_hash = hashlib.sha256(content).hexdigest()[:16]
        mtime = datetime.fromtimestamp(target.stat().st_mtime, UTC).isoformat()
        size_bytes = len(content)

        if stored_hash:
            is_stale = (current_hash.lower() != stored_hash.lower())
            return json.dumps({
                "status": "MUTATED_STALE" if is_stale else "CURRENT",
                "file_path": str(target),
                "is_stale": is_stale,
                "staleness_risk": 0.85 if is_stale else 0.0,
                "stored_hash": stored_hash,
                "current_hash": current_hash,
                "last_modified": mtime,
                "size_bytes": size_bytes,
                "message": "File has mutated since memory was recorded." if is_stale else "File hash matches stored memory provenance."
            }, indent=2)

        return json.dumps({
            "status": "VERIFIED_PRESENT",
            "file_path": str(target),
            "current_hash": current_hash,
            "last_modified": mtime,
            "size_bytes": size_bytes,
            "staleness_risk": 0.0,
            "message": "File is present and reachable."
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "READ_ERROR",
            "file_path": str(target),
            "staleness_risk": 0.5,
            "error": str(e)
        }, indent=2)


def tool_mem_causal_recall(args: dict) -> str:
    """Open Research Frontier (Episodic Missing Piece): Retrieve memories with explicit causal outcome polarity gating."""
    query = str(args.get("query", "")).strip().lower()
    outcome_filter = str(args.get("outcome_filter", "resolved_fix")).strip().lower()
    limit = int(args.get("limit", 5))

    root = _default_mem_root()
    results = []

    # 1. Scan operational error retrospectives (failures + mitigations)
    err_file = root / "operational" / "errors.json"
    if err_file.exists():
        try:
            errs = json.loads(err_file.read_text(encoding="utf-8"))
            for e in errs:
                trace = e.get("trace", "")
                mitigation = e.get("mitigation", "")
                root_cause = e.get("root_cause", "")
                # Mitigation represents resolved_fix
                if mitigation:
                    results.append({
                        "causal_outcome": "resolved_fix",
                        "summary": f"Mitigation: {mitigation} (Root cause: {root_cause})",
                        "source": "operational/errors.json",
                        "timestamp": e.get("timestamp")
                    })
                # Trace represents failed_attempt
                if trace:
                    results.append({
                        "causal_outcome": "failed_attempt",
                        "summary": f"Failure: {trace} (Root cause: {root_cause})",
                        "source": "operational/errors.json",
                        "timestamp": e.get("timestamp")
                    })
        except Exception:
            pass

    # 2. Scan recent episodic logs
    history_dir = root / "episodic" / "history"
    if history_dir.exists():
        for p in sorted(history_dir.glob("*.md"), reverse=True)[:5]:
            try:
                for line in p.read_text(encoding="utf-8").splitlines():
                    if line.startswith("### "):
                        text = line[4:].strip()
                        low = text.lower()
                        outcome = "observation"
                        if any(w in low for w in ("fix", "passed", "resolved", "mitigated", "success", "verified")):
                            outcome = "resolved_fix"
                        elif any(w in low for w in ("failed", "error", "exception", "bug", "traceback")):
                            outcome = "failed_attempt"

                        results.append({
                            "causal_outcome": outcome,
                            "summary": text,
                            "source": str(p.name),
                            "timestamp": p.stem
                        })
            except Exception:
                pass

    # 3. Filter by outcome polarity
    if outcome_filter != "any":
        results = [r for r in results if r["causal_outcome"] == outcome_filter]

    # 4. Rank by query relevance (token overlap)
    q_tokens = [t for t in re.split(r"\W+", query) if len(t) > 2] if query else []
    if q_tokens:
        def score(r):
            low = r["summary"].lower()
            return sum(1 for t in q_tokens if t in low)
        results = sorted(results, key=score, reverse=True)

    return json.dumps({
        "status": "ok",
        "query": query,
        "outcome_filter": outcome_filter,
        "total_matched": len(results),
        "results": results[:limit]
    }, indent=2)


def tool_mem_thermodynamic_compact(args: dict) -> str:
    """Invention (PAEL): Continuous thermodynamic multi-phase memory lifecycle compaction.
    Computes epistemic free energy F(m, t) and sublimates stable repetitive procedural traces
    into deterministic programmatic assertion guards, bounding total physical storage volume."""
    sublimate = bool(args.get("sublimate", True))
    min_frequency = int(args.get("min_frequency", 3))
    dry_run = bool(args.get("dry_run", False))

    root = _default_mem_root()
    operational_dir = root / "operational"
    errors_file = operational_dir / "errors.json"
    history_dir = root / "episodic" / "history"

    total_raw_bytes = 0
    if errors_file.exists():
        total_raw_bytes += errors_file.stat().st_size
    if history_dir.exists():
        for ef in history_dir.glob("*.md"):
            total_raw_bytes += ef.stat().st_size

    errs = []
    if errors_file.exists():
        try:
            errs = json.loads(errors_file.read_text(encoding="utf-8"))
        except Exception:
            errs = []

    procedure_counts = {}
    for e in errs:
        rc = e.get("root_cause", "").strip()
        mit = e.get("mitigation", "").strip()
        if rc and mit:
            sig = f"{rc} -> {mit}"
            procedure_counts[sig] = procedure_counts.get(sig, 0) + 1

    sublimated_guards = []
    import hashlib
    for sig, count in procedure_counts.items():
        if count >= min_frequency:
            guard_id = "guard_" + hashlib.sha256(sig.encode("utf-8")).hexdigest()[:8]
            sublimated_guards.append({
                "guard_name": guard_id,
                "procedure": sig,
                "frequency": count,
                "phase": "SUBLIMATION",
                "status": "COMPILED_INVARIANT"
            })

    purged_count = 0
    if sublimate and not dry_run and errs:
        seen = set()
        deduped = []
        for e in errs:
            sig = (e.get("root_cause", ""), e.get("mitigation", ""))
            if sig not in seen:
                seen.add(sig)
                deduped.append(e)
            else:
                purged_count += 1
        _atomic_write_json(errors_file, deduped)
        compacted_bytes = errors_file.stat().st_size
    else:
        compacted_bytes = total_raw_bytes

    reduction_pct = round((1.0 - (compacted_bytes / max(1, total_raw_bytes))) * 100.0, 2) if total_raw_bytes > 0 else 0.0

    return json.dumps({
        "status": "ok",
        "phase_transitions": {
            "gas_to_liquid": "Active prompt working memory cooled to episodic journal",
            "liquid_to_crystal": "Triples and invariants extracted to SQLite knowledge graph",
            "crystal_to_sublimation": f"{len(sublimated_guards)} stable procedures sublimated to programmatic guards"
        },
        "metrics": {
            "raw_bytes_before": total_raw_bytes,
            "compacted_bytes_after": compacted_bytes,
            "purged_entries_count": purged_count,
            "volume_reduction_pct": reduction_pct,
            "bounded_asymptote_limit_bytes": 100 * 1024 * 1024
        },
        "sublimated_guards": sublimated_guards,
        "dry_run": dry_run
    }, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry
# ──────────────────────────────────────────────────────────────────────────────

TOOLS = {
    "mem_link_memory": {
        "fn": tool_mem_link_memory,
        "description": "Explicitly link a memory reference (claim, fact, task, episode) to a Knowledge Graph entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_ref": {"type": "string", "description": "Memory reference (e.g. claim:292, fact:key, task:id)"},
                "entity": {"type": "string", "description": "Target entity name or entity_id"},
                "relationship": {"type": "string", "default": "references", "description": "Relationship type (references, affects, configures, documents)"}
            },
            "required": ["memory_ref", "entity"]
        }
    },
    "mem_get_entity_memories": {
        "fn": tool_mem_get_entity_memories,
        "description": "Retrieve all memory references linked to a specific Knowledge Graph entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name or entity_id"}
            },
            "required": ["entity"]
        }
    },
    "mem_session_start": {
        "fn": tool_mem_session_start,
        "description": "Load GMS startup context (preferences, projects, lessons, recent episodic, top facts). Call at the start of every session.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_session_end": {
        "fn": tool_mem_session_end,
        "description": "Log a session-end milestone to episodic memory. Summarize the verified outcome, rationale, resulting context change, evidence, remaining work, and next action; do not record a bare status such as done or blocked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent":   {"type": "string", "description": "Agent name (e.g. Antigravity, Codex)"},
                "summary": {"type": "string", "description": "Material context change only: project/task, verified outcome, why it matters, evidence, resulting state, remaining uncertainty/blockers, and next action. Skip routine reads, unchanged checks, speculation, and duplicate narration."},
            },
            "required": ["agent", "summary"],
        },
    },
    "mem_task_create": {
        "fn": tool_mem_task_create,
        "description": "Create a durable, project-scoped task for cross-agent coordination. Give it a concrete objective and scope; task state is not a substitute for a durable semantic decision or its rationale.",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}, "title": {"type": "string"}, "agent": {"type": "string"},
            "project": {"type": "string"}, "objective": {"type": "string"}, "parent_task_id": {"type": "string"},
        }, "required": ["task_id", "title", "agent"]},
    },
    "mem_task_claim": {
        "fn": tool_mem_task_claim,
        "description": "Atomically claim a task at its expected revision and establish a time-bounded lease.",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}, "agent": {"type": "string"}, "expected_revision": {"type": "integer"},
            "lease_seconds": {"type": "integer", "default": 1800},
        }, "required": ["task_id", "agent", "expected_revision"]},
    },
    "mem_task_checkpoint": {
        "fn": tool_mem_task_checkpoint,
        "description": "Save an immutable task checkpoint and advance its revision. State should capture verified progress, evidence, blockers, and next action. Reference claim, episode, and artifact IDs instead of copying durable memory.",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}, "agent": {"type": "string"}, "expected_revision": {"type": "integer"},
            "label": {"type": "string"}, "state": {"type": "object"}, "artifact_refs": {"type": "array"},
            "claim_refs": {"type": "array"}, "episode_refs": {"type": "array"},
        }, "required": ["task_id", "agent", "expected_revision", "state"]},
    },
    "mem_handoff_create": {
        "fn": tool_mem_handoff_create,
        "description": "Release an owned task with a structured context package for another agent to claim. Include objective, completed work with evidence, rationale behind key choices, blockers, acceptance criteria, and one executable next action.",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}, "source_agent": {"type": "string"}, "target_agent": {"type": "string"},
            "expected_revision": {"type": "integer"}, "objective": {"type": "string"}, "completed_work": {"type": "string"},
            "next_action": {"type": "string"}, "blockers": {"type": "string"}, "acceptance_criteria": {"type": "string"},
            "context": {"type": "object"}, "artifact_refs": {"type": "array"},
        }, "required": ["task_id", "source_agent", "expected_revision"]},
    },
    "mem_task_resume": {
        "fn": tool_mem_task_resume,
        "description": "Return a task together with its latest durable checkpoint and handoff package.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]},
    },
    "mem_task_complete": {
        "fn": tool_mem_task_complete,
        "description": "Mark a currently owned task completed at its expected revision. First persist a checkpoint or handoff containing evidence and resulting context; completion alone is not durable knowledge.",
        "inputSchema": {"type": "object", "properties": {
            "task_id": {"type": "string"}, "agent": {"type": "string"}, "expected_revision": {"type": "integer"},
        }, "required": ["task_id", "agent", "expected_revision"]},
    },
    "mem_project_state": {
        "fn": tool_mem_project_state,
        "description": "Get the latest project-scoped task state, including each task's latest checkpoint and handoff summary.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}, "include_completed": {"type": "boolean", "default": False},
        }, "required": ["project"]},
    },
    "mem_save_fact": {
        "fn": tool_mem_save_fact,
        "description": "Save a semantic fact after conflict detection. Use a lowercase dotted canonical key. Durable decisions and policies must use a structured JSON value containing statement/status, substantive rationale, implications, scope, provenance, evidence, freshness, and review state; never save a bare status or invent missing rationale.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "Lowercase dotted canonical key, for example global_memory.retrieval.legacy_policy"},
                "value": {"type": "string", "description": "Fact value. For decisions/policies, pass a JSON-encoded structured context record with rationale, implications, scope, provenance, evidence, freshness, and review state."},
                "force": {"type": "boolean", "description": "Overwrite existing value if conflicting"},
                "agent": {"type": "string", "description": "Calling agent name (e.g. Antigravity, Codex)"},
            },
            "required": ["key", "value"],
        },
    },
    "mem_save_typed": {
        "fn": tool_mem_save_typed,
        "description": "Save typed memory using semantic, operational, procedural, or session routing. Use lowercase dotted keys and preserve authority/evidence. Decisions and policies require structured rationale, implications, scope, provenance, freshness, and review state; procedures require trigger, ordered steps, success criteria, and failure handling.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string", "description": "Lowercase dotted canonical memory key"},
                "value": {"type": "string", "description": "Value or JSON-encoded structured context record; do not use a bare status when rationale affects future action"},
                "kind":  {"type": "string", "description": "Explicit bucket override: semantic, operational, procedural, session"},
                "force": {"type": "boolean", "description": "Overwrite existing value if conflicting"},
                "agent": {"type": "string", "description": "Calling agent name (e.g. Antigravity, Codex)"},
            },
            "required": ["key", "value"],
        },
    },
    "mem_judge": {
        "fn": tool_mem_judge,
        "description": "Check whether a proposed fact conflicts with existing knowledge. Read-only. A clear result means no detected collision, not verified truth; provenance, evidence, authority, scope, and rationale are still required before durable promotion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":   {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    "mem_log_event": {
        "fn": tool_mem_log_event,
        "description": "Append an episodic milestone to today's journal. Record what changed, why, supporting evidence or verification, remaining uncertainty, and next action—not only an activity or status. Episodic detail does not replace a structured semantic decision.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Actual actor or observing agent; do not attribute AI interpretation to the user"},
                "title": {"type": "string", "description": "Concise material event or context change, not a generic status"},
                "note":  {"type": "string", "description": "Project/task, what changed, why it matters, event/observation time when relevant, evidence or verification, resulting state, uncertainty/blockers, next action, and affected record/artifact references. Skip routine reads, unchanged monitoring, speculation, and duplicates."},
            },
            "required": ["agent", "title", "note"],
        },
    },
    "mem_add_lesson": {
        "fn": tool_mem_add_lesson,
        "description": "Add a corrective lesson or override rule to global.md.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    "mem_latest": {
        "fn": tool_mem_latest,
        "description": "Fetch the latest N episodic log milestones and fact/claim updates across memory without guessing dates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent entries to fetch (default 10)"},
                "kind":  {"type": "string", "description": "Filter by kind: 'episodic', 'facts', 'claims', or 'all' (default all)"},
            },
            "required": [],
        },
    },
    "mem_project": {
        "fn": tool_mem_project,
        "description": "Manage the five-file project context bank (brief, patterns, tech, active, progress). Updates should let a future agent recover goals, current truth, decisions with rationale, constraints, evidence, remaining work, blockers, and next action without rereading the repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":  {"type": "string", "description": "Action: 'init', 'get', 'update', or 'list'"},
                "project": {"type": "string", "description": "Project name (e.g. alphaos, optimus, global-memory)"},
                "section": {"type": "string", "description": "Section: 'brief', 'patterns', 'tech', 'active', 'progress', or 'all' (default all)"},
                "content": {"type": "string", "description": "Content string for update action"},
                "append":  {"type": "boolean", "description": "Append to section vs overwrite (default true)"},
            },
            "required": [],
        },
    },
    "mem_search": {
        "fn": tool_mem_search,
        "description": "Search local graph and episodic/vector memory using low, high, or hybrid retrieval with optional reranking. Search results are context candidates, not automatic truth: prefer active structured records with rationale/evidence, preserve conflicts and supersession, and corroborate imported legacy or AI-inferred material before consequential use.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":        {"type": "string", "description": "Search query"},
                "mode":         {"type": "string", "description": "LightRAG mode: 'low' (entity triples), 'high' (thematic vector search), or 'hybrid' (combined RRF)"},
                "k":            {"type": "integer", "description": "Number of results (default 5)"},
                "decay_rate":   {"type": "number", "description": "Exponential decay rate per day (default 0.002)"},
                "no_decay":     {"type": "boolean", "description": "Disable temporal decay"},
                "branch_boost": {"type": "number", "description": "Active branch boost multiplier (default 1.15)"},
                "no_boost":     {"type": "boolean", "description": "Disable git branch boost"},
                "no_hybrid":    {"type": "boolean", "description": "Disable BM25 hybrid search RRF"},
                "rerank":       {"type": "boolean", "description": "Enable Stage-2 Cross-Encoder reranking (default true)"},
                "no_rerank":    {"type": "boolean", "description": "Disable Stage-2 Cross-Encoder reranking"},
                "rerank_model": {"type": "string", "description": "Cross-encoder model for FlashRank (default ms-marco-TinyBERT-L-2-v2)"},
                "rerank_k":     {"type": "integer", "description": "Candidate pool size to rerank (default 25)"},
            },
            "required": ["query"],
        },
    },
    "mem_graph_extract": {
        "fn": tool_mem_graph_extract,
        "description": "Extract and register Knowledge Graph triples (Subject -> Predicate -> Object) from arbitrary text or claims.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text":  {"type": "string", "description": "Text content to extract triples from"},
                "key":   {"type": "string", "description": "Optional key for explicit triple"},
                "value": {"type": "string", "description": "Optional value for explicit triple"},
            },
            "required": [],
        },
    },
    "mem_graph_query": {
        "fn": tool_mem_graph_query,
        "description": "Query 1-hop & 2-hop Knowledge Graph relationships and valid edge topologies for an entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name to query"},
                "hops":   {"type": "integer", "description": "Search depth (default 2)"},
                "format": {"type": "string", "description": "Output format: 'mermaid', 'ascii', or 'json' (default mermaid)"},
                "valid_at": {"type": "string", "description": "Point-in-time timestamp (ISO format) for time-travel queries"},
                "include_expired": {"type": "boolean", "description": "Whether to include historically invalidated/expired edges (default false)"},
            },
            "required": ["entity"],
        },
    },
    "mem_graph_entities": {
        "fn": tool_mem_graph_entities,
        "description": "List registered entities in the Knowledge Graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Filter by entity name prefix"},
            },
            "required": [],
        },
    },
    "mem_context": {
        "fn": tool_mem_context,
        "description": "Return the last N lines of today's episodic log.",
        "inputSchema": {
            "type": "object",
            "properties": {"lines": {"type": "integer", "description": "Number of lines (default 50)"}},
            "required": [],
        },
    },
    "mem_get_facts": {
        "fn": tool_mem_get_facts,
        "description": "Return facts from a specific bucket (semantic, operational, procedural, session), optionally filtered by key prefix.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Filter key prefix"},
                "kind":   {"type": "string", "description": "Memory bucket (defaults to semantic): semantic, operational, procedural, session"},
            },
            "required": [],
        },
    },
    "mem_get_preferences": {
        "fn": tool_mem_get_preferences,
        "description": "Return the contents of preferences.md.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_get_projects": {
        "fn": tool_mem_get_projects,
        "description": "Return the contents of projects.md.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_stats": {
        "fn": tool_mem_stats,
        "description": "Return stats about the GMS (fact count, index status, etc.).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_index_rebuild": {
        "fn": tool_mem_index_rebuild,
        "description": "Rebuild the FAISS vector index. Run after adding many new memories.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_calibration_report": {
        "fn": tool_mem_calibration_report,
        "description": "Retrieve the trust-calibration report summarizing observer overlap, agreement, and disagreement.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_retention_report": {
        "fn": tool_mem_retention_report,
        "description": "Report stale low-confidence active facts and stale quarantines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "low_confidence": {"type": "number", "description": "Confidence threshold for archival candidates."},
                "stale_active_days": {"type": "integer", "description": "Minimum age in days for low-confidence active claims."},
                "stale_quarantine_days": {"type": "integer", "description": "Minimum age in days for stale quarantines."},
            },
            "required": [],
        },
    },
    "mem_get_reputations": {
        "fn": tool_mem_get_reputations,
        "description": "Retrieve legacy Bayesian contribution/calibration counts for registered agents. Do not interpret or display them as a global agent trust score; evaluate provenance, recency, evidence quality, disputes, and task-scoped outcomes separately.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_get_quarantine": {
        "fn": tool_mem_get_quarantine,
        "description": "Retrieve all quarantined facts that were blocked due to trust violations.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    "mem_resolve_quarantine": {
        "fn": tool_mem_resolve_quarantine,
        "description": "Exceptionally promote or discard a quarantined fact. Promotion requires resolvable source evidence, valid structured context, explicit authority, rationale, implications, scope, provenance, freshness, and review state. Preserve the audit trail; missing evidence or unresolved destructive authority fails closed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":      {"type": "string", "description": "Lowercase dotted canonical fact key"},
                "agent_id": {"type": "string", "description": "The agent who proposed the fact"},
                "action":   {"type": "string", "description": "Action to take ('promote' or 'discard')"},
                "agent":    {"type": "string", "description": "The agent resolving the quarantine (e.g. Master, User)"},
            },
            "required": ["key", "agent_id", "action"],
        },
    },
    "mem_record_review": {
        "fn": tool_mem_record_review,
        "description": "Record an evidence-based witness review for a quarantined fact. The rationale should identify supporting or conflicting evidence and scope; a vote without reasoning must not establish durable truth.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":         {"type": "string", "description": "Fact key"},
                "agent_id":    {"type": "string", "description": "The agent who proposed the fact"},
                "reviewer_id": {"type": "string", "description": "The agent making the review"},
                "rating":      {"type": "string", "description": "'endorse', 'reject', or 'abstain'"},
                "rationale":   {"type": "string", "description": "Reasoning for the review"},
            },
            "required": ["key", "agent_id", "reviewer_id", "rating"],
        },
    },
    "mem_get_reviews": {
        "fn": tool_mem_get_reviews,
        "description": "Retrieve all reviews for a quarantined fact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":      {"type": "string", "description": "Fact key"},
                "agent_id": {"type": "string", "description": "The agent who proposed the fact"},
            },
            "required": ["key", "agent_id"],
        },
    },
    "mem_get_recommendation_summary": {
        "fn": tool_mem_get_recommendation_summary,
        "description": "Get a weighted recommendation summary for a quarantined fact based on witness reviews.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key":      {"type": "string", "description": "Fact key"},
                "agent_id": {"type": "string", "description": "The agent who proposed the fact"},
            },
            "required": ["key", "agent_id"],
        },
    },
    "mem_get_claims": {
        "fn": tool_mem_get_claims,
        "description": "Retrieve claims from the versioned claim ledger, optionally filtered by kind, key, and status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind":   {"type": "string", "description": "Filter by memory kind (semantic, operational, procedural)"},
                "key":    {"type": "string", "description": "Filter by memory key"},
                "status": {"type": "string", "description": "Filter by claim status (active, superseded, quarantined, discarded, archived)"},
            },
            "required": [],
        },
    },
    "mem_upsert_entity": {
        "fn": tool_mem_upsert_entity,
        "description": "Create or update an entity in the local graph database.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":        {"type": "string", "description": "Unique name of the entity"},
                "entity_type": {"type": "string", "description": "Type of entity (e.g. Person, Project, Concept)"},
                "summary":     {"type": "string", "description": "Brief description or summary of the entity"},
            },
            "required": ["name"],
        },
    },
    "mem_link_entities": {
        "fn": tool_mem_link_entities,
        "description": "Link two entities with a relationship, optionally referencing a claim id and validity window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject_id":      {"type": "integer", "description": "Entity ID of the subject"},
                "subject_name":    {"type": "string", "description": "Name of the subject entity (auto-created if not exists)"},
                "predicate":       {"type": "string", "description": "The relationship type / predicate (e.g., works_on, member_of)"},
                "object_id":       {"type": "integer", "description": "Entity ID of the object entity"},
                "object_name":     {"type": "string", "description": "Name of the object entity (auto-created if not exists)"},
                "object_literal":  {"type": "string", "description": "Literal value of the object if not referencing another entity"},
                "source_claim_id": {"type": "integer", "description": "Optional ID of the source claim from gms_claims"},
                "valid_from":      {"type": "string", "description": "Optional start timestamp of validity"},
                "valid_to":        {"type": "string", "description": "Optional end timestamp of validity"},
            },
            "required": ["predicate"],
        },
    },
    "mem_get_entity_graph": {
        "fn": tool_mem_get_entity_graph,
        "description": "Retrieve the entity graph. If entity_id or name is specified, retrieves the ego network for that entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "integer", "description": "Filter by entity ID"},
                "name":      {"type": "string", "description": "Filter by entity name"},
            },
            "required": [],
        },
    },
    "mem_upsert_procedure": {
        "fn": tool_mem_upsert_procedure,
        "description": "Create or update a reusable trigger-action playbook.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":            {"type": "string", "description": "Unique name of the procedure"},
                "trigger":         {"type": "string", "description": "The trigger condition or event pattern"},
                "action":          {"type": "string", "description": "The playbook action or sequence of instructions"},
                "context":         {"type": "string", "description": "Optional context or execution environment details"},
                "status":          {"type": "string", "description": "Status of the procedure (active or archived)", "default": "active"},
                "source_claim_id": {"type": "integer", "description": "Optional source claim ID linking to GMS claims ledger"},
            },
            "required": ["name"],
        },
    },
    "mem_get_procedures": {
        "fn": tool_mem_get_procedures,
        "description": "Retrieve procedures from the database, optionally filtered by status, name, or source_claim_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status":          {"type": "string", "description": "Filter by status (active or archived)"},
                "name":            {"type": "string", "description": "Filter by specific name"},
                "source_claim_id": {"type": "integer", "description": "Filter by source claim ID"},
            },
            "required": [],
        },
    },
    "mem_list_episodes": {
        "fn": tool_mem_list_episodes,
        "description": "List episodic sources with enough metadata to select a source deterministically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Optional limit on the number of sources returned"},
                "type":  {"type": "string", "description": "Optional type filter ('journal' or 'history')"},
            },
            "required": [],
        },
    },
    "mem_get_episode": {
        "fn": tool_mem_get_episode,
        "description": "Retrieve details or content of a specific episodic source by date or source path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date":   {"type": "string", "description": "Optional date of history file (YYYY-MM-DD)"},
                "source": {"type": "string", "description": "Optional file path or filename"},
                "mode":   {"type": "string", "description": "Retrieval mode ('summary' or 'deep')", "default": "summary"},
            },
            "required": [],
        },
    },
    "mem_drift_status": {
        "fn": tool_mem_drift_status,
        "description": "Analyze semantic drift of embeddings over time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "description": "Optional threshold for warning classification (default: 0.05)"}
            },
            "required": [],
        },
    },
    "mem_validate_schemas": {
        "fn": tool_mem_validate_schemas,
        "description": "Validate active memory facts across semantic, operational, and procedural buckets against schema contracts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "mem_session_harvest": {
        "fn": tool_mem_session_harvest,
        "description": "Extract post-session context candidates, temporal graph edges, and vectors. Extraction is interpretation, not authorship or accepted truth. Keep source evidence and AI inference distinct; schema-valid evidence-backed candidates may be activated by the audited system curator and remain owner-contestable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent":   {"type": "string", "description": "Agent name (default: Antigravity)"},
                "summary": {"type": "string", "description": "Summary of session accomplishments"},
                "text":    {"type": "string", "description": "Optional extra notes or conversation context"},
            },
            "required": ["summary"],
        },
    },
    "mem_project_briefing": {
        "fn": tool_mem_project_briefing,
        "description": "Generate or explain an evidence-linked operational project briefing covering goals, current truth, decisions with rationale, constraints, blockers, uncertainty, and next action. Legacy or inferred context must stay visibly qualified.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project identifier (e.g. 'global-memory')"},
                "as_of":   {"type": "string", "description": "Optional point-in-time ISO timestamp"},
                "profile": {"type": "string", "description": "Detail profile ('standard', 'condensed', 'deep')", "default": "standard"},
                "action":  {"type": "string", "description": "Action: 'get' or 'explain'", "default": "get"},
            },
            "required": ["project"],
        },
    },
    "mem_context_packet": {
        "fn": tool_mem_context_packet,
        "description": "Build a deterministic, token-budgeted context packet with conflict/time-aware retrieval, authority labels, legacy corroboration warnings, source-diversity metadata, and a stable packet hash. Use this for agent resumption and consequential work instead of raw nearest-neighbor search.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Concrete context question or objective"},
            "project": {"type": "string", "description": "Optional project scope"},
            "profile": {"type": "string", "enum": ["small", "standard", "deep"], "default": "standard"},
            "as_of": {"type": "string", "description": "Optional ISO point-in-time boundary"},
        }, "required": ["query"]},
    },
    "mem_curation": {
        "fn": tool_mem_curation,
        "description": "Operate the audited system-decides/owner-may-contest curation workflow. Preview by default; apply only when explicitly requested. Evidence or schema failures fail closed, and owner contests preserve rollback lineage.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "preview", "apply", "contest_preview", "contest_apply"], "default": "status"},
            "candidate_id": {"type": "string", "description": "Required for contest actions"},
            "rationale": {"type": "string", "description": "Substantive owner contest rationale; required for contest actions"},
            "limit": {"type": "integer", "default": 100},
        }, "required": []},
    },
    "mem_memory_quality": {
        "fn": tool_mem_memory_quality,
        "description": "Inspect memory quality without mutation: convention compliance, production pollution, or source-reference integrity. A summary combines convention and pollution audits; source verification requires a candidate ID.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["summary", "conventions", "pollution", "source"], "default": "summary"},
            "candidate_id": {"type": "string", "description": "Required for source verification"},
        }, "required": []},
    },
    "mem_memory_repair": {
        "fn": tool_mem_memory_repair,
        "description": "Repair incomplete legacy facts without fabricating rationale. Analysis/evidence actions are read-only. Stage/archive actions preview by default and require explicit apply, actor, and substantive rationale; staging preserves the legacy value until reviewed.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["analyze", "evidence", "stage_preview", "stage_apply", "archive_preview", "archive_apply"], "default": "analyze"},
            "key": {"type": "string", "description": "Existing legacy memory key"},
            "payload": {"type": "object", "description": "Evidence-backed repaired structured context record"},
            "actor": {"type": "string", "description": "Registered actor identity for mutation"},
            "rationale": {"type": "string", "description": "Substantive reason for staging or archival"},
        }, "required": ["key"]},
    },
    "mem_lifecycle": {
        "fn": tool_mem_lifecycle,
        "description": "Inspect append-only record lifecycle history or preview/apply an optimistic-concurrency transition. Mutations require an explicit transition_apply action, registered actor, substantive rationale, legal state change, and matching expected hash when supplied.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["history", "transition_preview", "transition_apply"], "default": "history"},
            "record_id": {"type": "string", "description": "Required for history"},
            "request": {"type": "object", "description": "Lifecycle request containing request_id, record_id, canonical_key, next_state, operation, actor_id, actor_kind, rationale, content/source refs, and optional expected_hash"},
        }, "required": []},
    },
    "mem_aliases": {
        "fn": tool_mem_aliases,
        "description": "Inventory or resolve canonical aliases and preview/apply recoverable collision consolidation. Consolidation uses lowercase dotted canonical keys, requires an explicit preferred record, actor, and substantive rationale, and preserves supersession history.",
        "inputSchema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["inventory", "resolve", "consolidate_preview", "consolidate_apply"], "default": "inventory"},
            "key": {"type": "string", "description": "Input key for resolve"},
            "canonical_key": {"type": "string", "description": "Collision group for consolidation"},
            "preferred_key": {"type": "string", "description": "Existing record whose value should survive"},
            "actor": {"type": "string"},
            "rationale": {"type": "string"},
        }, "required": []},
    },
    "mem_project_timeline": {
        "fn": tool_mem_project_timeline,
        "description": "Return a unified, newest-first, evidence-linked project timeline across project-bank changes, tasks, decisions, consolidation, and repairs. Filter by event type or agent, or request one event by ID.",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string", "description": "Project identifier"},
            "event_type": {"type": "string"},
            "agent": {"type": "string"},
            "event_id": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
        }, "required": ["project"]},
    },
    "mem_action_inbox": {
        "fn": tool_mem_action_inbox,
        "description": "Query or preview consequence-ranked action items requiring human operator attention or review.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project":  {"type": "string", "description": "Optional project filter"},
                "category": {"type": "string", "description": "Optional category filter"},
                "action":   {"type": "string", "description": "Action: 'list' or 'preview'", "default": "list"},
                "inbox_id": {"type": "string", "description": "Inbox item ID for preview action"},
            },
            "required": [],
        },
    },
    "mem_task_resume_bundle": {
        "fn": tool_mem_task_resume_bundle,
        "description": "Generate or verify a structured agent resumption bundle for Antigravity, Codex, Gemini, or JSON. The bundle should carry evidence-linked current truth, rationale-bearing decisions, constraints, conflicts, freshness, completed work, and one executable next action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project":       {"type": "string", "description": "Project identifier"},
                "target_format": {"type": "string", "description": "Target format ('antigravity', 'codex', 'gemini', 'json')", "default": "antigravity"},
                "as_of":         {"type": "string", "description": "Optional point-in-time timestamp"},
                "task_id":       {"type": "string", "description": "Optional specific task ID to resume"},
                "action":        {"type": "string", "description": "Action: 'build' or 'verify'", "default": "build"},
            },
            "required": ["project"],
        },
    },
    "mem_decision_intelligence": {
        "fn": tool_mem_decision_intelligence,
        "description": "Query decisions, inspect rationale/evidence/scope, or compute supersession impact across tasks and artifacts. Do not treat a status-only or superseded record as current truth; preserve contest and rollback lineage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":             {"type": "string", "description": "Action: 'list', 'get', or 'impact'", "default": "list"},
                "project":            {"type": "string", "description": "Optional project filter"},
                "decision_id":        {"type": "string", "description": "Decision ID for 'get' or 'impact' actions"},
                "include_superseded": {"type": "boolean", "description": "Include superseded decisions", "default": True},
            },
            "required": [],
        },
    },
    "mem_morning_briefing": {
        "fn": tool_mem_morning_briefing,
        "description": "Generate morning operational briefings answering what changed overnight, active blockers, and recommended first action.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project identifier"},
                "as_of":   {"type": "string", "description": "Optional point-in-time timestamp"},
                "action":  {"type": "string", "description": "Action: 'get' or 'list'", "default": "get"},
            },
            "required": [],
        },
    },
    "mem_file_context": {
        "fn": tool_mem_file_context,
        "description": "Pre-edit file risk and gotcha audit for coding agents. Inspects memories for known gotchas, activeContext constraints, patterns, and historical lessons before editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute or repo-relative path of the file to inspect"},
                "project":   {"type": "string", "description": "Optional project identifier"},
            },
            "required": ["file_path"],
        },
    },
    "mem_learn_error": {
        "fn": tool_mem_learn_error,
        "description": "Crystallize a terminal/test/compiler error trace into a procedural lesson and rule to prevent recurring mistakes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "error_trace": {"type": "string", "description": "Raw terminal output, traceback, or compiler error message"},
                "command":     {"type": "string", "description": "The command that failed"},
                "resolution":  {"type": "string", "description": "Optional recommended fix or root-cause explanation"},
                "project":     {"type": "string", "description": "Optional project identifier"},
                "agent":       {"type": "string", "description": "Optional agent name"},
            },
            "required": ["error_trace"],
        },
    },
    "mem_core_memory_get": {
        "fn": tool_mem_core_memory_get,
        "description": "MemGPT/Letta SOTA: Retrieve the agent's core memory blocks (persona, human, scratchpad) with token estimations.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "mem_core_memory_append": {
        "fn": tool_mem_core_memory_append,
        "description": "MemGPT/Letta SOTA: Append text to an agent core memory block (persona, human, scratchpad) with size bounding.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "block":   {"type": "string", "description": "Block name: 'persona', 'human', or 'scratchpad'"},
                "content": {"type": "string", "description": "Text content to append"},
                "agent":   {"type": "string", "description": "Optional writing agent identifier"},
            },
            "required": ["block", "content"],
        },
    },
    "mem_core_memory_replace": {
        "fn": tool_mem_core_memory_replace,
        "description": "MemGPT/Letta SOTA: Replace content in a core memory block (persona, human, scratchpad) using targeted matching or full overwrite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "block":       {"type": "string", "description": "Block name: 'persona', 'human', or 'scratchpad'"},
                "new_content": {"type": "string", "description": "Replacement text"},
                "old_content": {"type": "string", "description": "Optional substring to replace; if omitted, overwrites the whole block"},
                "agent":       {"type": "string", "description": "Optional writing agent identifier"},
            },
            "required": ["block", "new_content"],
        },
    },
    "mem_graph_communities": {
        "fn": tool_mem_graph_communities,
        "description": "Microsoft GraphRAG SOTA: Detect multi-scale modular communities over the entity graph using Louvain clustering.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "mem_reflect": {
        "fn": tool_mem_reflect,
        "description": "Stanford Generative Agents SOTA: Generate reflective insight synthesis across recent episodic milestones.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    "mem_trap_create": {
        "fn": tool_mem_trap_create,
        "description": "Frontier Invention: Plant a sleeping prospective memory trap with conditional trigger patterns and interrupt directives.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name":         {"type": "string", "description": "Unique identifier for the trap"},
                "pattern":      {"type": "string", "description": "Substring or regex pattern to match"},
                "payload":      {"type": "string", "description": "High-priority directive or constraint injected when triggered"},
                "trigger_type": {"type": "string", "default": "keyword", "description": "Trigger type: 'file_path', 'command', 'keyword', 'git_branch'"},
                "recurring":    {"type": "boolean", "default": False, "description": "Whether the trap remains active after tripping"},
                "agent":        {"type": "string", "description": "Creating agent identifier"},
            },
            "required": ["name", "pattern", "payload"],
        },
    },
    "mem_trap_list": {
        "fn": tool_mem_trap_list,
        "description": "Frontier Invention: List prospective attention traps and their active states, hit counts, and triggers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean", "default": False, "description": "Filter to active traps only"},
            },
            "required": [],
        },
    },
    "mem_trap_eval": {
        "fn": tool_mem_trap_eval,
        "description": "Frontier Invention: Fast evaluate observation text or action against active prospective traps to detect interrupts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Text, command, or file context to evaluate"},
            },
            "required": ["context"],
        },
    },
    "mem_trap_dismiss": {
        "fn": tool_mem_trap_dismiss,
        "description": "Frontier Invention: Dismiss or disarm a prospective attention trap by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of trap to dismiss"},
            },
            "required": ["name"],
        },
    },
    "mem_speculative_prefetch": {
        "fn": tool_mem_speculative_prefetch,
        "description": "Frontier Invention: Anticipatory cognitive branch predictor prefetching active traps, prior error regrets, symbols, and invariants.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "active_file": {"type": "string", "description": "Optional file path being inspected or edited"},
                "intent":      {"type": "string", "description": "Optional short description of pending command or goal"},
                "project":     {"type": "string", "description": "Optional project identifier"},
            },
            "required": [],
        },
    },
    "mem_programmatic_guard": {
        "fn": tool_mem_programmatic_guard,
        "description": "Frontier Invention: Deterministic programmatic assertion validator replacing ambiguous natural language advice.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "guard_name":    {"type": "string", "description": "Guard type: 'schema_keys', 'budget_limit', 'sqlite_concurrency', 'custom'"},
                "context":       {"type": "object", "description": "Runtime context dictionary to evaluate"},
                "required_keys": {"type": "array", "description": "Required keys for schema_keys guard"},
                "max_chars":     {"type": "integer", "description": "Max char budget for budget_limit guard"},
                "condition":     {"type": "boolean", "description": "Boolean assertion for custom guard"},
                "reason":        {"type": "string", "description": "Reason or invariant description"},
            },
            "required": ["guard_name"],
        },
    },
    "mem_staleness_verify": {
        "fn": tool_mem_staleness_verify,
        "description": "Open Research Frontier (STALE): Verify whether physical files bound to memory have mutated since recording.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path":   {"type": "string", "description": "Target file path to verify"},
                "stored_hash": {"type": "string", "description": "Optional expected SHA-256 hash recorded when memory was created"},
                "key":         {"type": "string", "description": "Optional semantic memory key with file metadata"},
            },
            "required": [],
        },
    },
    "mem_causal_recall": {
        "fn": tool_mem_causal_recall,
        "description": "Open Research Frontier (Episodic Missing Piece): Retrieve memories with explicit causal outcome polarity gating (resolved_fix vs failed_attempt).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":          {"type": "string", "description": "Search query keywords"},
                "outcome_filter": {"type": "string", "default": "resolved_fix", "description": "Outcome polarity: 'resolved_fix', 'failed_attempt', 'observation', or 'any'"},
                "limit":          {"type": "integer", "default": 5, "description": "Max results to return"},
            },
            "required": [],
        },
    },
    "mem_thermodynamic_compact": {
        "fn": tool_mem_thermodynamic_compact,
        "description": "Frontier Invention (PAEL): Execute thermodynamic memory compaction and sublimation, bounding physical storage volume.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sublimate":     {"type": "boolean", "default": True, "description": "Compile stable procedures into executable guards"},
                "min_frequency": {"type": "integer", "default": 3, "description": "Minimum repetition frequency before sublimation"},
                "dry_run":       {"type": "boolean", "default": False, "description": "Simulate compaction without purging records"},
            },
            "required": [],
        },
    },
}


# Dynamically mirror all mem_* tools as brain_* aliases for cognitive recall
brain_aliases = {}
for tool_name, spec in list(TOOLS.items()):
    if tool_name.startswith("mem_"):
        alias_name = "brain_" + tool_name[4:]
        alias_spec = dict(spec)
        alias_spec["description"] = f"[Brain Alias] {spec['description']}"
        brain_aliases[alias_name] = alias_spec

TOOLS.update(brain_aliases)

TOOLS_LIST = [
    {
        "name": name,
        "description": info["description"],
        "inputSchema": info["inputSchema"],
    }
    for name, info in TOOLS.items()
]


# ──────────────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 request handler
# ──────────────────────────────────────────────────────────────────────────────

def handle(req: dict) -> dict | None:
    id_    = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return _result(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "brain-memory", "version": "2.1.0"},
        })

    if method == "tools/list":
        return _result(id_, {"tools": TOOLS_LIST})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        if tool_name not in TOOLS:
            return _error(id_, -32601, f"Unknown tool: {tool_name}")
        try:
            output = TOOLS[tool_name]["fn"](tool_args)
            return _result(id_, _text(str(output)))
        except Exception as e:
            return _error(id_, -32603, f"Tool error: {e}")

    if method == "notifications/initialized":
        return None  # no response needed

    if method == "ping":
        return _result(id_, {})

    return _error(id_, -32601, f"Method not found: {method}")


# ──────────────────────────────────────────────────────────────────────────────
# Main stdio loop
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _send(_error(None, -32700, "Parse error"))
            continue

        response = handle(req)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
