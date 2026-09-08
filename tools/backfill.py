#!/usr/bin/env python3
"""
tools/backfill.py — Idempotent GMS v2.1.0 Data Migration & Backfill Engine

Safely backfills:
1. Schema & tables (init_db: gms_embeddings, bi-temporal indices)
2. Claims ledger (gms_claims) and provenance (gms_fact_provenance) for all active facts
3. Procedural memory (gms_procedures) from procedural/facts.json
4. Consolidated SQLite vectors (gms_embeddings) from episodic.faiss / episodic_meta.json
5. Bi-temporal Knowledge Graph (gms_relationships, gms_entities) with valid_from/valid_to
6. Schema validation audit via Pydantic contracts
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

import memory_mcp_server
import schemas

DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories"))


def _extract_vectors_from_faiss(
    faiss_path: Path, meta_path: Path
) -> Tuple[List[dict], str]:
    """
    Extract existing embeddings and metadata from FAISS index and meta.json.
    Tries native import first, then falls back to conda ml environment or python discovery.
    """
    if not faiss_path.exists() or not meta_path.exists():
        return [], "faiss_or_meta_missing"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not meta:
        return [], "empty_meta"

    # 1. Try direct import
    try:
        import faiss
        import numpy as np

        index = faiss.read_index(str(faiss_path))
        vecs = index.reconstruct_n(0, index.ntotal)
        items = []
        for m, vec in zip(meta, vecs):
            items.append({
                "source": m.get("source", "episodic"),
                "chunk": m.get("chunk", 0),
                "text": m.get("text", ""),
                "embedding": [float(v) for v in vec],
            })
        return items, "native_faiss"
    except ImportError:
        pass

    # 2. Try known conda environment or python binaries with faiss
    candidate_pythons = [
        Path("/opt/homebrew/Caskroom/miniconda/base/envs/ml/bin/python"),
        Path.home() / "miniforge3/envs/ml/bin/python",
        Path.home() / "miniconda3/envs/ml/bin/python",
        Path.home() / "anaconda3/envs/ml/bin/python",
    ]
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidate_pythons.insert(0, Path(conda_prefix) / "bin/python")

    python_bin = os.environ.get("PYTHON_BIN")
    if python_bin:
        candidate_pythons.insert(0, Path(python_bin))

    for py in candidate_pythons:
        if py.exists() and os.access(py, os.X_OK):
            script = f"""
import faiss, json, sys
meta = json.loads(open({repr(str(meta_path))}).read())
index = faiss.read_index({repr(str(faiss_path))})
vecs = index.reconstruct_n(0, index.ntotal)
out = []
for m, vec in zip(meta, vecs):
    out.append({{
        "source": m.get("source", "episodic"),
        "chunk": m.get("chunk", 0),
        "text": m.get("text", ""),
        "embedding": [float(v) for v in vec]
    }})
sys.stdout.write(json.dumps(out))
"""
            try:
                res = subprocess.run(
                    [str(py), "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True
                )
                items = json.loads(res.stdout)
                return items, f"subprocess_{py.name}"
            except Exception:
                continue

    return [], "faiss_not_available"


def _run_backfill_core(
    root: Path,
    db_path: Path,
    dry_run: bool,
    skip_embeddings: bool,
    skip_graph: bool,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "status": "success",
        "mem_root": str(root),
        "db_path": str(db_path),
        "dry_run": dry_run,
        "claims_backfilled": 0,
        "provenance_backfilled": 0,
        "procedures_backfilled": 0,
        "embeddings_backfilled": 0,
        "embeddings_method": "none",
        "relationships_backfilled": 0,
        "schema_audit": {},
    }

    import sqlite3
    conn = sqlite3.connect(str(db_path)) if db_path.exists() else None
    cursor = conn.cursor() if conn else None

    # Gather existing active claims
    existing_claims = set()
    if cursor:
        try:
            cursor.execute("SELECT memory_key FROM gms_claims WHERE status = 'active'")
            existing_claims = {r[0] for r in cursor.fetchall()}
        except Exception:
            pass

    # Gather existing provenance
    existing_provenance = set()
    if cursor:
        try:
            cursor.execute("SELECT fact_key FROM gms_fact_provenance")
            existing_provenance = {r[0] for r in cursor.fetchall()}
        except Exception:
            pass

    # Step 1: Backfill Claims and Provenance for all active facts
    kinds = ["semantic", "operational", "procedural"]
    all_facts: List[Tuple[str, str, Any]] = []

    for kind in kinds:
        facts_file = root / kind / "facts.json"
        if facts_file.exists():
            try:
                data = json.loads(facts_file.read_text(encoding="utf-8"))
                for k, v in data.items():
                    all_facts.append((kind, k, v))
            except Exception as e:
                report.setdefault("warnings", []).append(f"Could not read {facts_file}: {e}")

    for kind, key, val in all_facts:
        val_str = json.dumps(val) if isinstance(val, (dict, list)) else str(val)

        if key not in existing_claims:
            report["claims_backfilled"] += 1
            if not dry_run and cursor:
                cursor.execute(
                    """
                    INSERT INTO gms_claims (memory_kind, memory_key, value, agent_id, status, confidence, created_at)
                    VALUES (?, ?, ?, 'system_backfill', 'active', 1.0, CURRENT_TIMESTAMP)
                    """,
                    (kind, key, val_str)
                )

        if key not in existing_provenance:
            report["provenance_backfilled"] += 1
            if not dry_run and cursor:
                cursor.execute(
                    """
                    INSERT INTO gms_fact_provenance (fact_key, agent_id, branch, quarantined, timestamp)
                    VALUES (?, 'system_backfill', 'main', 0, CURRENT_TIMESTAMP)
                    ON CONFLICT(fact_key) DO UPDATE SET
                        agent_id = excluded.agent_id,
                        branch = excluded.branch,
                        quarantined = 0,
                        timestamp = CURRENT_TIMESTAMP
                    """,
                    (key,)
                )

    if not dry_run and conn:
        conn.commit()

    # Step 2: Backfill Procedural Memory (gms_procedures)
    proc_facts_file = root / "procedural" / "facts.json"
    if proc_facts_file.exists():
        try:
            proc_data = json.loads(proc_facts_file.read_text(encoding="utf-8"))
            for name, content in proc_data.items():
                content_str = str(content)
                # Check if already in gms_procedures
                exists = False
                if cursor:
                    try:
                        cursor.execute("SELECT 1 FROM gms_procedures WHERE name = ?", (name,))
                        if cursor.fetchone():
                            exists = True
                    except Exception:
                        pass

                if not exists:
                    # Find source claim ID
                    cid = None
                    if cursor:
                        try:
                            cursor.execute("SELECT claim_id FROM gms_claims WHERE memory_key = ? AND status = 'active'", (name,))
                            row = cursor.fetchone()
                            if row:
                                cid = row[0]
                        except Exception:
                            pass

                    # Parse trigger/action/context heuristics
                    trigger = f"Trigger for {name}"
                    action = content_str
                    context = "procedural"
                    if "After " in content_str:
                        parts = content_str.split("After ", 1)
                        if len(parts) > 1 and "," in parts[1]:
                            subparts = parts[1].split(",", 1)
                            trigger = f"After {subparts[0].strip()}"
                            action = subparts[1].strip()
                    elif "When " in content_str:
                        parts = content_str.split("When ", 1)
                        if len(parts) > 1 and "," in parts[1]:
                            subparts = parts[1].split(",", 1)
                            trigger = f"When {subparts[0].strip()}"
                            action = subparts[1].strip()

                    report["procedures_backfilled"] += 1
                    if not dry_run and cursor:
                        cursor.execute(
                            """
                            INSERT INTO gms_procedures (name, "trigger", action, context, status, source_claim_id)
                            VALUES (?, ?, ?, ?, 'active', ?)
                            """,
                            (name, trigger, action, context, cid)
                        )
            if not dry_run and conn:
                conn.commit()
        except Exception as e:
            report.setdefault("warnings", []).append(f"Procedure backfill error: {e}")

    # Step 3: Backfill Consolidated SQLite Vector Embeddings (gms_embeddings)
    if not skip_embeddings:
        faiss_path = root / "episodic" / "index" / "episodic.faiss"
        meta_path = root / "episodic" / "index" / "episodic_meta.json"
        items, method = _extract_vectors_from_faiss(faiss_path, meta_path)
        report["embeddings_method"] = method

        if items:
            if not dry_run:
                stored = memory_mcp_server.store_sqlite_embeddings(items, db_path=db_path)
                report["embeddings_backfilled"] = stored
            else:
                report["embeddings_backfilled"] = len(items)

    # Step 4: Backfill Bi-Temporal Knowledge Graph
    if not skip_graph:
        graph_count = 0
        if cursor:
            try:
                # Query active claims for graph extraction
                cursor.execute("SELECT claim_id, memory_key, value FROM gms_claims WHERE status = 'active'")
                claims_rows = cursor.fetchall()
            except Exception:
                claims_rows = []

            for cid, key, val in claims_rows:
                triples = memory_mcp_server.extract_graph_triples(f"{key}: {val}")
                if not triples:
                    triples = [(key, "configured_as", str(val)[:200])]
                for sub, pred, obj in triples:
                    graph_count += 1
                    if not dry_run:
                        memory_mcp_server.record_graph_relationship(
                            sub, pred, obj, source_claim_id=cid
                        )
            report["relationships_backfilled"] = graph_count

    if conn:
        conn.close()

    # Step 5: Schema Validation Audit
    valid_count = 0
    violation_count = 0
    violations = []
    for kind, key, val in all_facts:
        is_valid, res, ns = schemas.validate_fact(key, val)
        if is_valid:
            valid_count += 1
        else:
            violation_count += 1
            violations.append({"key": key, "error": res, "namespace": ns})

    report["schema_audit"] = {
        "total_facts": len(all_facts),
        "valid_count": valid_count,
        "violation_count": violation_count,
        "violations": violations,
    }

    return report


def run_backfill(
    mem_root: Path | None = None,
    dry_run: bool = False,
    skip_embeddings: bool = False,
    skip_graph: bool = False,
) -> Dict[str, Any]:
    root = Path(mem_root) if mem_root else DEFAULT_MEM_ROOT
    db_path = root / "gms_trust.sqlite"

    old_db = memory_mcp_server.DB_PATH
    old_root = memory_mcp_server.MEM_ROOT

    try:
        if not dry_run:
            memory_mcp_server.DB_PATH = db_path
            memory_mcp_server.MEM_ROOT = root
            memory_mcp_server.init_db(db_path=db_path)
        return _run_backfill_core(
            root=root,
            db_path=db_path,
            dry_run=dry_run,
            skip_embeddings=skip_embeddings,
            skip_graph=skip_graph,
        )
    finally:
        memory_mcp_server.DB_PATH = old_db
        memory_mcp_server.MEM_ROOT = old_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill GMS v2.1.0 tables, vectors, claims, and graph.")
    parser.add_argument("--root", default=None, help="Custom memory root directory.")
    parser.add_argument("--dry-run", action="store_true", help="Preview backfill without modifying database.")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip vector embedding backfill.")
    parser.add_argument("--skip-graph", action="store_true", help="Skip knowledge graph relationship backfill.")
    parser.add_argument("--json", action="store_true", help="Output result as JSON.")
    args = parser.parse_args()

    mem_root = Path(args.root).resolve() if args.root else DEFAULT_MEM_ROOT
    report = run_backfill(
        mem_root=mem_root,
        dry_run=args.dry_run,
        skip_embeddings=args.skip_embeddings,
        skip_graph=args.skip_graph,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        prefix = "[DRY-RUN] " if args.dry_run else ""
        print(f"{prefix}GMS v2.1.0 Backfill Report:")
        print(f"  Target DB: {report['db_path']}")
        print(f"  Claims backfilled: {report['claims_backfilled']}")
        print(f"  Provenance backfilled: {report['provenance_backfilled']}")
        print(f"  Procedures backfilled: {report['procedures_backfilled']}")
        print(f"  Embeddings backfilled: {report['embeddings_backfilled']} (method: {report['embeddings_method']})")
        print(f"  Graph relationships backfilled: {report['relationships_backfilled']}")
        audit = report["schema_audit"]
        print(f"  Schema Audit: {audit['valid_count']}/{audit['total_facts']} valid, {audit['violation_count']} violations")
        if audit["violations"]:
            for v in audit["violations"]:
                print(f"    - Violation on {v['key']}: {v['error']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
