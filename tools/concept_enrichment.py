#!/usr/bin/env python3
"""
tools/concept_enrichment.py — Asynchronous Nightly Concept Enrichment

Part of Mbrain UX Pass 2 (Two-Speed Architecture):
- Daytime: lightweight deterministic extraction and idempotent enqueueing.
- Nighttime: bounded local Ollama enrichment batch owned by Dream Cycle.
- Strictly unloads LLM from memory upon completion (keep_alive: 0).
- Stores proposals in gms_concept_candidates (never direct unreviewed canonical writes).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import request

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")).expanduser()
DEFAULT_DB_PATH = DEFAULT_MEM_ROOT / "gms_trust.sqlite"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
CONCEPT_PROVIDER = os.environ.get("CONCEPT_PROVIDER", "ollama")
CONCEPT_MODEL = os.environ.get("CONCEPT_MODEL", "qwen2.5:7b")
PROMPT_VERSION = "concept-enrichment-v1"


def init_concept_tables(db_path: Path | str | None = None) -> None:
    p = Path(db_path or DEFAULT_DB_PATH)
    if not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    c.execute(
        """
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
        """
    )

    c.execute(
        """
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
        """
    )

    c.execute(
        """
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
        """
    )

    conn.commit()
    conn.close()


def enqueue_concept_source(
    source_kind: str,
    source_ref: str,
    text: str,
    priority: int = 50,
    db_path: Path | str | None = None,
) -> int:
    """Idempotently enqueue a text excerpt for nightly concept enrichment."""
    if not text or not text.strip():
        return 0

    init_concept_tables(db_path)
    excerpt = text.strip()[:8000]
    source_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()

    p = Path(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    try:
        c.execute(
            """
            INSERT INTO gms_concept_enrichment_queue (
                source_kind, source_ref, source_hash, text_excerpt, priority, status
            ) VALUES (?, ?, ?, ?, ?, 'pending')
            ON CONFLICT(source_kind, source_ref, source_hash) DO NOTHING
            """,
            (source_kind, source_ref, source_hash, excerpt, priority)
        )
        conn.commit()
        qid = c.lastrowid or 0
        conn.close()
        return qid
    except Exception:
        conn.close()
        return 0


def recover_expired_leases(timeout_minutes: int = 30, db_path: Path | str | None = None) -> int:
    """Recover items leased longer than timeout_minutes back to 'pending'."""
    init_concept_tables(db_path)
    p = Path(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
    c.execute(
        """
        UPDATE gms_concept_enrichment_queue
        SET status = 'pending', lease_owner = NULL, leased_at = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE status = 'leased' AND leased_at < ?
        """,
        (cutoff,)
    )
    recovered = c.rowcount
    conn.commit()
    conn.close()
    return recovered


def lease_batch(
    batch_size: int = 8,
    lease_owner: str = "dream_cycle",
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Atomically lease up to batch_size pending items."""
    init_concept_tables(db_path)
    p = Path(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    c.execute(
        """
        SELECT queue_id, source_kind, source_ref, source_hash, text_excerpt, attempts
        FROM gms_concept_enrichment_queue
        WHERE status IN ('pending', 'retry') AND attempts < 3
        ORDER BY priority ASC, created_at ASC
        LIMIT ?
        """,
        (batch_size,)
    )
    rows = c.fetchall()
    if not rows:
        conn.close()
        return []

    qids = [r[0] for r in rows]
    now_iso = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in qids)
    c.execute(
        f"""
        UPDATE gms_concept_enrichment_queue
        SET status = 'leased', lease_owner = ?, leased_at = ?, attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
        WHERE queue_id IN ({placeholders})
        """,
        [lease_owner, now_iso] + qids
    )
    conn.commit()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "queue_id": r[0],
            "source_kind": r[1],
            "source_ref": r[2],
            "source_hash": r[3],
            "text_excerpt": r[4],
            "attempts": r[5] + 1,
        })
    return items


def validate_enrichment_output(payload: dict[str, Any], source_text: str) -> tuple[bool, str, dict[str, Any]]:
    """Validate JSON output against concept-enrichment-v1 contract."""
    if not isinstance(payload, dict):
        return False, "Output is not a JSON object", {}

    if payload.get("schema_version") != "concept-enrichment-v1":
        return False, f"Invalid schema_version: {payload.get('schema_version')}", {}

    entities = payload.get("entities", [])
    relationships = payload.get("relationships", [])

    if not isinstance(entities, list) or not isinstance(relationships, list):
        return False, "entities and relationships must be arrays", {}

    normalized_source = re.sub(r"\s+", " ", source_text.lower())
    valid_entities = []
    for e in entities:
        if not isinstance(e, dict):
            continue
        canon = str(e.get("canonical_name", "")).strip()
        etype = str(e.get("entity_type", "CONCEPT")).strip().upper()
        quote = str(e.get("evidence_quote", "")).strip()

        # Evidence quote verification
        norm_quote = re.sub(r"\s+", " ", quote.lower())
        if quote and norm_quote not in normalized_source and len(norm_quote) > 8:
            continue

        if canon:
            valid_entities.append({
                "surface_form": e.get("surface_form", canon),
                "canonical_name": canon,
                "entity_type": etype,
                "summary": e.get("summary", ""),
                "aliases": e.get("aliases", []),
                "evidence_quote": quote,
                "evidence_strength": e.get("evidence_strength", "explicit"),
                "novelty": e.get("novelty", "new"),
                "action": e.get("action", "review"),
                "reason": e.get("reason", "Extracted by concept model"),
            })

    valid_relationships = []
    for r in relationships:
        if not isinstance(r, dict):
            continue
        subj = str(r.get("subject", "")).strip()
        pred = str(r.get("predicate", "")).strip()
        obj = str(r.get("object", "")).strip()
        if subj and pred and obj and subj.lower() != obj.lower():
            valid_relationships.append({
                "subject": subj,
                "predicate": pred,
                "object": obj,
                "evidence_quote": r.get("evidence_quote", ""),
                "evidence_strength": r.get("evidence_strength", "explicit"),
                "valid_from": r.get("valid_from"),
                "valid_to": r.get("valid_to"),
                "action": r.get("action", "review"),
            })

    cleaned = {
        "schema_version": "concept-enrichment-v1",
        "entities": valid_entities,
        "relationships": valid_relationships,
    }
    return True, "", cleaned


def unload_ollama_model(model: str = CONCEPT_MODEL, url: str = OLLAMA_URL) -> bool:
    """Explicitly unload local model from memory by sending keep_alive: 0."""
    try:
        req = request.Request(
            f"{url}/api/generate",
            data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_ollama_enrichment(text: str, model: str = CONCEPT_MODEL, url: str = OLLAMA_URL) -> dict[str, Any]:
    """Invoke local Ollama with concept extraction prompt and keep_alive: 0."""
    prompt = f"""You are an expert Knowledge Graph Extraction Engine.
Extract entities and relationships from the text below according to schema version 'concept-enrichment-v1'.

Input Text:
\"\"\"
{text}
\"\"\"

Return ONLY valid JSON with this exact structure:
{{
  "schema_version": "concept-enrichment-v1",
  "entities": [
    {{
      "surface_form": "exact mention in text",
      "canonical_name": "clean.canonical.id",
      "entity_type": "INFRA | AGENT | MODEL | TICKER | POLICY | CONCEPT",
      "summary": "concise description backed by text",
      "aliases": ["alias1"],
      "evidence_quote": "exact quote from text",
      "evidence_strength": "explicit",
      "novelty": "new",
      "action": "review"
    }}
  ],
  "relationships": [
    {{
      "subject": "Subject Entity",
      "predicate": "verb_relationship",
      "object": "Object Entity",
      "evidence_quote": "exact quote from text",
      "evidence_strength": "explicit",
      "action": "review"
    }}
  ]
}}
"""
    req_body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": 0,  # Unload immediately after generation
    }
    req = request.Request(
        f"{url}/api/generate",
        data=json.dumps(req_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=45) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        raw_response = res.get("response", "{}")
        return json.loads(raw_response)


def process_enrichment_batch(
    batch_size: int = 8,
    llm_func: Callable[[str], dict[str, Any]] | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Process a bounded batch of queued excerpts and stage candidate entities."""
    init_concept_tables(db_path)
    p = Path(db_path or DEFAULT_DB_PATH)
    items = lease_batch(batch_size=batch_size, db_path=p)

    if not items:
        return {"status": "idle", "processed": 0, "candidates": 0}

    started_at = datetime.now(timezone.utc).isoformat()
    processed_count = 0
    candidate_count = 0
    errors_count = 0

    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    try:
        for item in items:
            qid = item["queue_id"]
            text = item["text_excerpt"]
            shash = item["source_hash"]

            try:
                if llm_func:
                    raw_out = llm_func(text)
                else:
                    raw_out = run_ollama_enrichment(text)

                is_valid, err_msg, cleaned = validate_enrichment_output(raw_out, text)
                if is_valid:
                    # Save entities
                    for ent in cleaned["entities"]:
                        c.execute(
                            """
                            INSERT INTO gms_concept_candidates (
                                queue_id, candidate_kind, payload_json, model, provider,
                                prompt_version, source_hash, validation_status, review_status
                            ) VALUES (?, 'entity', ?, ?, ?, ?, ?, 'valid', 'pending')
                            """,
                            (qid, json.dumps(ent), CONCEPT_MODEL, CONCEPT_PROVIDER, PROMPT_VERSION, shash)
                        )
                        candidate_count += 1

                    # Save relationships
                    for rel in cleaned["relationships"]:
                        c.execute(
                            """
                            INSERT INTO gms_concept_candidates (
                                queue_id, candidate_kind, payload_json, model, provider,
                                prompt_version, source_hash, validation_status, review_status
                            ) VALUES (?, 'relationship', ?, ?, ?, ?, ?, 'valid', 'pending')
                            """,
                            (qid, json.dumps(rel), CONCEPT_MODEL, CONCEPT_PROVIDER, PROMPT_VERSION, shash)
                        )
                        candidate_count += 1

                    now_iso = datetime.now(timezone.utc).isoformat()
                    c.execute(
                        """
                        UPDATE gms_concept_enrichment_queue
                        SET status = 'completed', completed_at = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE queue_id = ?
                        """,
                        (now_iso, qid)
                    )
                    processed_count += 1
                else:
                    # Mark retry or dead_letter
                    new_status = "dead_letter" if item["attempts"] >= 3 else "retry"
                    c.execute(
                        """
                        UPDATE gms_concept_enrichment_queue
                        SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE queue_id = ?
                        """,
                        (new_status, err_msg, qid)
                    )
                    errors_count += 1
            except Exception as item_err:
                errors_count += 1
                new_status = "dead_letter" if item["attempts"] >= 3 else "retry"
                c.execute(
                    """
                    UPDATE gms_concept_enrichment_queue
                    SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE queue_id = ?
                    """,
                    (new_status, str(item_err), qid)
                )

        # Audit record
        completed_at = datetime.now(timezone.utc).isoformat()
        c.execute(
            """
            INSERT INTO gms_concept_run_audit (
                started_at, completed_at, provider, model, prompt_version,
                items_processed, candidates_generated, errors_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (started_at, completed_at, CONCEPT_PROVIDER, CONCEPT_MODEL, PROMPT_VERSION,
             processed_count, candidate_count, errors_count, "completed" if errors_count == 0 else "partial")
        )
        conn.commit()
    finally:
        conn.close()
        # Guaranteed unload on any exit
        if not llm_func:
            unload_ollama_model(CONCEPT_MODEL)

    return {
        "status": "success",
        "processed": processed_count,
        "candidates": candidate_count,
        "errors": errors_count,
    }


def get_enrichment_status(db_path: Path | str | None = None) -> dict[str, Any]:
    """Return status summary of concept enrichment queue and runs."""
    init_concept_tables(db_path)
    p = Path(db_path or DEFAULT_DB_PATH)
    conn = sqlite3.connect(str(p))
    c = conn.cursor()

    status_counts = {}
    c.execute("SELECT status, COUNT(*) FROM gms_concept_enrichment_queue GROUP BY status")
    for s, cnt in c.fetchall():
        status_counts[s] = cnt

    c.execute("SELECT COUNT(*) FROM gms_concept_candidates WHERE review_status = 'pending'")
    pending_candidates = c.fetchone()[0]

    c.execute(
        """
        SELECT run_id, started_at, completed_at, items_processed, candidates_generated, status
        FROM gms_concept_run_audit
        ORDER BY run_id DESC LIMIT 1
        """
    )
    last_run_row = c.fetchone()
    last_run = None
    if last_run_row:
        last_run = {
            "run_id": last_run_row[0],
            "started_at": last_run_row[1],
            "completed_at": last_run_row[2],
            "items_processed": last_run_row[3],
            "candidates_generated": last_run_row[4],
            "status": last_run_row[5],
        }

    conn.close()
    return {
        "queue_counts": status_counts,
        "pending_candidates": pending_candidates,
        "last_run": last_run,
        "provider": CONCEPT_PROVIDER,
        "model": CONCEPT_MODEL,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="GMS Concept Enrichment Runner")
    parser.add_argument("--status", action="store_true", help="Print enrichment status")
    parser.add_argument("--batch", type=int, default=8, help="Drain batch size")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(get_enrichment_status(), indent=2))
    else:
        res = process_enrichment_batch(batch_size=args.batch)
        print(json.dumps(res, indent=2))
