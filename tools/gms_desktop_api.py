#!/usr/bin/env python3
"""
tools/gms_desktop_api.py — Backend API Engine for GMS Desktop Application

Provides a unified interface bridging the Electron desktop application to GMS SQLite
databases, markdown stores, schema contracts, agentic sleep harvesting, and Apple Automation.
Can run as a standalone CLI dispatcher or an embedded lightweight HTTP server.

Zero external dependencies (pure Python standard library + existing GMS modules).
Cross-platform: Apple Automation gracefully degrades on Linux/Mini PC.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import gms_inspect
import harvest
import memory_mcp_server
from memory_aliases import alias_inventory, resolve_alias
from memory_authority import validate_authority
from memory_convention_audit import convention_audit, cleanup_preview, migration_inventory, stage_migration, rollback_migration
from context_retrieval_planner import retrieve as retrieve_context
from context_packet import build_context_packet
from memory_lifecycle import lifecycle_history, transition as lifecycle_transition
from schemas import validate_fact, parse_payload, list_contracts
from project_briefing import generate_project_briefing, explain_project_briefing, build_resume_bundle
from project_timeline import get_project_timeline
from decision_intelligence import list_decisions, get_decision, get_decision_impact
from action_inbox import list_inbox_items, preview_inbox_action
from memory_repair import find_repair_evidence, analyze_missing_fields, stage_repair_candidate
from morning_briefing import generate_morning_briefing, list_morning_briefings
from resumption_eval import run_resumption_evaluation

DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")).expanduser()
DB_PATH = DEFAULT_MEM_ROOT / "gms_trust.sqlite"



def _is_literal_like(label: str) -> bool:
    """Classify whether a node label looks like an inline literal rather than an entity."""
    if not label:
        return False
    s = str(label).strip()
    if len(s) > 42:
        return True
    if s.startswith(("{", "[", "http://", "https://", "file://", "ssh://")):
        return True
    if any(c in s for c in ("\n", "\r", "\t")):
        return True
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return True
    if re.match(r"^[\$€£]?\d+(\.\d+)?%?$", s):
        return True
    if len(s.split()) >= 6:
        return True
    return False


class GMSDesktopAPI:
    def __init__(self, mem_root: Path | None = None):
        self.mem_root = Path(mem_root).expanduser() if mem_root else DEFAULT_MEM_ROOT
        self.db_path = self.mem_root / "gms_trust.sqlite"
        # Ensure memory_mcp_server uses the same root
        memory_mcp_server.MEM_ROOT = self.mem_root
        memory_mcp_server.DB_PATH = self.db_path
        gms_inspect.MEM_ROOT = self.mem_root
        gms_inspect.DB_PATH = self.db_path

    # =========================================================================
    # 1. System Snapshot & Health
    # =========================================================================
    def get_snapshot(self) -> dict[str, Any]:
        snapshot = gms_inspect.build_snapshot()
        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        bak_path = self.mem_root / "gms_trust.sqlite.bak"
        bak_size = bak_path.stat().st_size if bak_path.exists() else 0

        # Objective agent contribution activity. Legacy reputation values are
        # deliberately excluded: Mbrain does not compute a global agent score.
        reputations = []
        fleet_metrics = {
            "total_agents": 0,
            "total_claims": 0,
            "quarantine_pending": 0,
        }
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()

                # Precompute active claims count and top namespace per agent
                claims_map: dict[str, dict[str, Any]] = {}
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_claims'")
                if c.fetchone():
                    c.execute("""
                        SELECT agent_id, count(*), substr(memory_key, 1, instr(memory_key || '.', '.') - 1) as ns
                        FROM gms_claims
                        WHERE status = 'active'
                        GROUP BY agent_id, ns
                    """)
                    for a_id, cnt, ns in c.fetchall():
                        if a_id not in claims_map:
                            claims_map[a_id] = {"total": 0, "namespaces": {}}
                        claims_map[a_id]["total"] += cnt
                        claims_map[a_id]["namespaces"][ns or "general"] = cnt

                candidate_map: dict[str, dict[str, int]] = {}
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_context_candidates'")
                if c.fetchone():
                    c.execute("SELECT extractor_agent, review_status, count(*) FROM gms_context_candidates GROUP BY extractor_agent, review_status")
                    for agent_id, review_status, count in c.fetchall():
                        stats = candidate_map.setdefault(agent_id or "unknown", {})
                        stats[review_status or "unknown"] = count

                agent_ids = sorted(set(claims_map) | set(candidate_map))
                for agent_id in agent_ids:
                    a_claims = claims_map.get(agent_id, {"total": 0, "namespaces": {}})
                    claim_count = a_claims["total"]
                    ns_counts = a_claims["namespaces"]
                    specialty = max(ns_counts.items(), key=lambda x: x[1])[0] if ns_counts else "General"
                    if not specialty.strip():
                        specialty = "General"

                    candidate_stats = candidate_map.get(agent_id, {})
                    reputations.append({
                        "agent_id": agent_id,
                        "claim_count": claim_count,
                        "proposed_count": candidate_stats.get("proposed", 0),
                        "accepted_count": candidate_stats.get("accepted", 0) + candidate_stats.get("merged", 0),
                        "rejected_count": candidate_stats.get("rejected", 0),
                        "deferred_count": candidate_stats.get("deferred", 0),
                        "specialty": specialty,
                        "last_updated": None,
                    })

                # Check quarantine count
                c.execute("SELECT count(*) FROM gms_quarantined_facts")
                q_count = c.fetchone()[0]

                # Check total claims
                c.execute("SELECT count(*) FROM gms_claims WHERE status = 'active'")
                tot_claims = c.fetchone()[0]

                fleet_metrics["total_agents"] = len(reputations)
                fleet_metrics["total_claims"] = tot_claims
                fleet_metrics["quarantine_pending"] = q_count

                conn.close()
            except Exception:
                pass

        snapshot["db_size_bytes"] = db_size
        snapshot["backup_size_bytes"] = bak_size
        snapshot["agent_reputations"] = reputations
        snapshot["fleet_metrics"] = fleet_metrics
        snapshot["platform"] = sys.platform
        snapshot["apple_automation_supported"] = (sys.platform == "darwin")
        return snapshot

    def get_memory_quality(self) -> dict[str, Any]:
        return convention_audit(self.mem_root)

    def get_migration_inventory(self) -> dict[str, Any]:
        return migration_inventory(self.mem_root)

    def migration_action(self, payload: dict[str,Any], rollback: bool=False) -> dict[str,Any]:
        fn=rollback_migration if rollback else stage_migration
        kwargs={"actor":str(payload.get("actor","")),"rationale":str(payload.get("rationale","")),"apply":bool(payload.get("apply",False))}
        if not rollback: kwargs["expected_hash"]=str(payload.get("expected_hash",""))
        return fn(self.mem_root,list(payload.get("keys") or []),**kwargs)

    def get_aliases(self, key: str = "") -> dict[str, Any]:
        return resolve_alias(self.mem_root, key) if key else alias_inventory(self.mem_root)

    def get_retrieval_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return retrieve_context(self.mem_root, str(payload.get("query", "")), project=str(payload.get("project", "")),
            as_of=payload.get("as_of"), assurance=str(payload.get("assurance", "standard")),
            token_budget=int(payload.get("token_budget", 2400)))

    def get_context_packet_v1(self, payload: dict[str, Any]) -> dict[str, Any]:
        return build_context_packet(self.mem_root, str(payload.get("query", "")), project=str(payload.get("project", "")),
                                    profile=str(payload.get("profile", "standard")), as_of=payload.get("as_of"))

    def validate_memory_authority(self, payload: dict[str, Any]) -> dict[str, Any]:
        return validate_authority(payload.get("record", payload), bool(payload.get("authenticated_user", False)))

    def preview_lifecycle(self, payload: dict[str, Any], apply: bool = False) -> dict[str, Any]:
        return lifecycle_transition(self.db_path, payload, apply=apply)

    def get_lifecycle_history(self, record_id: str) -> list[dict[str, Any]]:
        return lifecycle_history(self.db_path, record_id)

    # =========================================================================
    # 2. Multi-Tier Memory Exploration & Search
    # =========================================================================
    def get_memories(
        self,
        tier: str = "all",
        namespace: str = "",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
        sort: str = "recent",
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        # Load active metadata (author, created_at) from SQLite in batch
        meta_map: dict[str, dict[str, Any]] = {}
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_fact_provenance'")
                if c.fetchone():
                    c.execute("SELECT fact_key, agent_id, timestamp FROM gms_fact_provenance")
                    for k, aid, ts in c.fetchall():
                        existing = meta_map.setdefault(k, {})
                        existing["agent"] = aid
                        existing["created_at"] = existing.get("created_at") or ts
                        existing["updated_at"] = max(str(existing.get("updated_at") or ""), str(ts or ""))
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_claims'")
                if c.fetchone():
                    c.execute(
                        """
                        SELECT memory_key, MIN(created_at), MAX(created_at)
                        FROM gms_claims
                        GROUP BY memory_key
                        """
                    )
                    for k, first_ts, last_ts in c.fetchall():
                        existing = meta_map.setdefault(k, {})
                        existing["created_at"] = first_ts or existing.get("created_at")
                        existing["updated_at"] = max(str(existing.get("updated_at") or ""), str(last_ts or ""))
                    c.execute("SELECT memory_key, agent_id FROM gms_claims WHERE status = 'active' ORDER BY claim_id ASC")
                    for k, aid in c.fetchall():
                        meta_map.setdefault(k, {})["agent"] = aid
                conn.close()
            except Exception:
                pass

        def infer_ns(key: str, default_tier: str = "general") -> str:
            if "." in key:
                return key.split(".")[0]
            if "_" in key:
                prefix = key.split("_")[0]
                if prefix in ("user", "learning", "alphaos", "apple", "birthday", "task", "work", "active", "system", "infra", "model", "trading", "stock", "crypto"):
                    return prefix
            return default_tier

        def matches_ns(entry_ns: str, entry_key: str, filter_ns: str) -> bool:
            if not filter_ns:
                return True
            clean_filter = filter_ns.rstrip(".").lower()
            entry_ns_clean = entry_ns.rstrip(".").lower()
            key_lower = entry_key.lower()

            if entry_ns_clean == clean_filter:
                return True
            if key_lower.startswith(clean_filter):
                return True
            if clean_filter == "procedural" and entry_ns_clean in ("procedural", "procedures"):
                return True
            if clean_filter == "procedures" and entry_ns_clean in ("procedural", "procedures"):
                return True
            if clean_filter == "episodic" and entry_ns_clean in ("episodic", "history", "journal"):
                return True
            if clean_filter == "operational" and entry_ns_clean == "operational":
                return True
            return False

        # 1. Semantic Facts
        if tier in ("all", "semantic"):
            facts_file = self.mem_root / "semantic" / "facts.json"
            if facts_file.exists():
                try:
                    file_mtime = datetime.fromtimestamp(facts_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    facts = json.loads(facts_file.read_text(errors="replace"))
                    for k, v in facts.items():
                        ns = infer_ns(k, "general")
                        if not matches_ns(ns, k, namespace):
                            continue
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        if query and query.lower() not in k.lower() and query.lower() not in val_str.lower():
                            continue
                        meta = meta_map.get(k, {})
                        results.append({
                            "key": k,
                            "value": parse_payload(v),
                            "tier": "semantic",
                            "namespace": ns,
                            "source": "facts.json",
                            "created_at": meta.get("created_at") or file_mtime,
                            "updated_at": meta.get("updated_at") or meta.get("created_at") or file_mtime,
                            "agent": meta.get("agent") or "system",
                        })
                except Exception:
                    pass

        # 2. Operational Facts
        if tier in ("all", "operational") and (not namespace or matches_ns("operational", "operational", namespace)):
            ops_file = self.mem_root / "operational" / "facts.json"
            if ops_file.exists():
                try:
                    file_mtime = datetime.fromtimestamp(ops_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    facts = json.loads(ops_file.read_text(errors="replace"))
                    for k, v in facts.items():
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        if query and query.lower() not in k.lower() and query.lower() not in val_str.lower():
                            continue
                        meta = meta_map.get(k, {})
                        results.append({
                            "key": k,
                            "value": parse_payload(v),
                            "tier": "operational",
                            "namespace": "operational",
                            "source": "operational/facts.json",
                            "created_at": meta.get("created_at") or file_mtime,
                            "updated_at": meta.get("updated_at") or meta.get("created_at") or file_mtime,
                            "agent": meta.get("agent") or "system",
                        })
                except Exception:
                    pass

        # 3. Procedural Facts & Runbooks
        if tier in ("all", "procedural") and (not namespace or matches_ns("procedural", "procedural", namespace) or matches_ns("procedures", "procedures", namespace)):
            proc_file = self.mem_root / "procedural" / "facts.json"
            if proc_file.exists():
                try:
                    file_mtime = datetime.fromtimestamp(proc_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    facts = json.loads(proc_file.read_text(errors="replace"))
                    for k, v in facts.items():
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        if query and query.lower() not in k.lower() and query.lower() not in val_str.lower():
                            continue
                        meta = meta_map.get(k, {})
                        results.append({
                            "key": k,
                            "value": parse_payload(v),
                            "tier": "procedural",
                            "namespace": "procedural",
                            "source": "procedural/facts.json",
                            "created_at": meta.get("created_at") or file_mtime,
                            "updated_at": meta.get("updated_at") or meta.get("created_at") or file_mtime,
                            "agent": meta.get("agent") or "system",
                        })
                except Exception:
                    pass

            # DB procedures
            if self.db_path.exists() and (not namespace or matches_ns("procedures", "procedures", namespace)):
                try:
                    conn = sqlite3.connect(str(self.db_path))
                    c = conn.cursor()
                    c.execute("SELECT name, \"trigger\", action, context, status, created_at FROM gms_procedures")
                    for name, trigger, action, context, status, created_at in c.fetchall():
                        text_blob = f"{name} {trigger} {action} {context}"
                        if query and query.lower() not in text_blob.lower():
                            continue
                        results.append({
                            "key": f"proc.{name}",
                            "value": {"trigger": trigger, "action": action, "context": context, "status": status},
                            "tier": "procedural",
                            "namespace": "procedures",
                            "source": "gms_procedures",
                            "created_at": str(created_at) if created_at else "",
                            "updated_at": str(created_at) if created_at else "",
                            "agent": "system",
                        })
                    conn.close()
                except Exception:
                    pass

        # 4. Episodic Memories (Journal & History files)
        if tier in ("all", "episodic") and (not namespace or matches_ns("episodic", "episodic", namespace) or matches_ns("journal", "journal", namespace) or matches_ns("history", "history", namespace)):
            journal = self.mem_root / "episodic" / "journal.md"
            if journal.exists() and (not namespace or matches_ns("journal", "journal", namespace) or namespace == "episodic"):
                try:
                    file_mtime = datetime.fromtimestamp(journal.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    lines = journal.read_text(errors="replace").splitlines()
                    current_entry: list[str] = []
                    current_title = "Journal Entry"
                    current_ts = file_mtime

                    def parse_entry_time(title: str, default_ts: str) -> str:
                        m = re.search(r"\b(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)\b", title)
                        return m.group(1) if m else default_ts

                    for line in lines:
                        if line.startswith("## ") or line.startswith("# "):
                            if current_entry:
                                body = "\n".join(current_entry).strip()
                                if not query or query.lower() in current_title.lower() or query.lower() in body.lower():
                                    results.append({
                                        "key": current_title,
                                        "value": body,
                                        "tier": "episodic",
                                        "namespace": "journal",
                                        "source": "journal.md",
                                        "created_at": current_ts,
                                        "updated_at": current_ts,
                                        "agent": "user",
                                    })
                            current_title = line.lstrip("#").strip()
                            current_ts = parse_entry_time(current_title, file_mtime)
                            current_entry = []
                        else:
                            current_entry.append(line)
                    if current_entry:
                        body = "\n".join(current_entry).strip()
                        if not query or query.lower() in current_title.lower() or query.lower() in body.lower():
                            results.append({
                                "key": current_title,
                                "value": body,
                                "tier": "episodic",
                                "namespace": "journal",
                                "source": "journal.md",
                                "created_at": current_ts,
                                "updated_at": current_ts,
                                "agent": "user",
                            })
                except Exception:
                    pass

            history_dir = self.mem_root / "episodic" / "history"
            if history_dir.exists() and (not namespace or matches_ns("history", "history", namespace) or namespace == "episodic"):
                for f in sorted(history_dir.glob("*.md"), reverse=True)[:50]:
                    try:
                        content = f.read_text(errors="replace")
                        if not query or query.lower() in f.stem.lower() or query.lower() in content.lower():
                            f_mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                            m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", f.stem)
                            date_str = m.group(1) if m else f_mtime
                            results.append({
                                "key": f"history/{f.name}",
                                "value": content[:500] + ("..." if len(content) > 500 else ""),
                                "tier": "episodic",
                                "namespace": "history",
                                "source": f.name,
                                "created_at": date_str,
                                "updated_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                                "agent": "system",
                            })
                    except Exception:
                        pass

        # Sort results
        for memory in results:
            memory["activity_at"] = memory.get("updated_at") or memory.get("created_at") or ""

        if sort == "recent":
            results.sort(key=lambda m: (str(m.get("activity_at") or ""), m.get("key", "").lower()), reverse=True)
        elif sort == "newest":
            results.sort(key=lambda m: (str(m.get("created_at") or ""), m.get("key", "").lower()), reverse=True)
        elif sort == "alpha":
            results.sort(key=lambda m: m.get("key", "").lower())
        elif sort == "oldest":
            results.sort(key=lambda m: (str(m.get("created_at") or "9999"), m.get("key", "").lower()))

        total_count = len(results)
        paged = results[offset : offset + limit]
        return {
            "total": total_count,
            "count": len(paged),
            "offset": offset,
            "limit": limit,
            "sort": sort,
            "memories": paged,
        }

    # =========================================================================
    # 3. Steering: Validate, Edit, Save, and Delete Facts
    # =========================================================================
    def validate_memory_payload(self, key: str, value: Any) -> dict[str, Any]:
        is_valid, norm_val, err_msg = validate_fact(key, value)
        return {
            "valid": is_valid,
            "normalized": norm_val,
            "error": err_msg,
            "contracts": list_contracts(),
        }

    def save_fact(
        self,
        key: str,
        value: Any,
        agent: str = "",
        kind: str = "semantic",
    ) -> dict[str, Any]:
        # Validate schema first
        parsed_val = parse_payload(value) if isinstance(value, str) else value
        is_valid, norm_val, err_msg = validate_fact(key, parsed_val)
        if not is_valid:
            return {
                "status": "error",
                "message": f"Schema contract validation failed: {err_msg}",
                "error": err_msg,
            }

        # A browser surface is an origin, never a durable author. Require an
        # explicit registered local identity instead of recording `human-ui`.
        import reviewers
        actor_ok, actor_or_error = reviewers.validate_reviewer_id(agent, mem_root=self.mem_root)
        if not actor_ok:
            return {"status": "error", "message": actor_or_error, "error": actor_or_error}

        # Store via MCP server logic
        val_str = json.dumps(norm_val) if isinstance(norm_val, (dict, list)) else str(norm_val)
        res_str = memory_mcp_server.tool_mem_save_typed({
            "key": key,
            "value": val_str,
            "kind": kind,
            "agent": actor_or_error,
        })
        return {
            "status": "success" if "error" not in res_str.lower() else "warning",
            "message": res_str,
            "key": key,
            "value": norm_val,
        }

    def delete_fact(self, key: str, agent: str = "") -> dict[str, Any]:
        import reviewers
        actor_ok, actor_or_error = reviewers.validate_reviewer_id(agent, mem_root=self.mem_root)
        if not actor_ok:
            return {"status": "error", "message": actor_or_error, "error": actor_or_error}
        # Invalidate across JSON tiers
        deleted = False
        for folder in ("semantic", "operational", "procedural"):
            path = self.mem_root / folder / "facts.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    if key in data:
                        del data[key]
                        path.write_text(json.dumps(data, indent=2))
                        deleted = True
                except Exception:
                    pass

        # Update SQLite claim status to 'retracted'
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute(
                    "UPDATE gms_claims SET status = 'retracted' WHERE memory_key = ? AND status = 'active'",
                    (key,),
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

        return {
            "status": "success" if deleted else "not_found",
            "key": key,
            "message": f"Fact '{key}' removed from memory store." if deleted else f"Fact '{key}' not found in active stores.",
        }

    # =========================================================================
    # 4. Steering: Quarantine Review & Trust Calibration
    # =========================================================================
    def _get_active_fact(self, key: str) -> tuple[Any, str | None, str | None]:
        """Look up active value, owner, and timestamp for a fact key across SQLite and JSON files."""
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute(
                    """
                    SELECT value, agent_id, created_at
                    FROM gms_claims
                    WHERE memory_key = ? AND status = 'active'
                    ORDER BY claim_id DESC LIMIT 1
                    """,
                    (key,)
                )
                row = c.fetchone()
                if row:
                    conn.close()
                    return parse_payload(row[0]), row[1], row[2]

                c.execute("SELECT agent_id, timestamp FROM gms_fact_provenance WHERE fact_key = ?", (key,))
                prov_row = c.fetchone()
                conn.close()
                prov_owner = prov_row[0] if prov_row else None
                prov_ts = prov_row[1] if prov_row else None
            except Exception:
                prov_owner, prov_ts = None, None
        else:
            prov_owner, prov_ts = None, None

        for folder in ("semantic", "operational", "procedural"):
            path = self.mem_root / folder / "facts.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text())
                    if key in data:
                        return data[key], prov_owner or "system", prov_ts
                except Exception:
                    pass

        return None, None, None

    def get_quarantine_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.db_path.exists():
            return items

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()

            contribution_counts: dict[str, int] = {}
            c.execute("SELECT agent_id, count(*) FROM gms_claims GROUP BY agent_id")
            for a_id, count in c.fetchall():
                contribution_counts[a_id or "unknown"] = count

            c.execute(
                """
                SELECT q.fact_key, q.value, q.agent_id, q.branch, q.timestamp
                FROM gms_quarantined_facts q
                ORDER BY q.timestamp DESC
                """
            )
            rows = c.fetchall()
            conn.close()

            for row in rows:
                key, raw_val, agent_id, branch, ts = row
                parsed_val = parse_payload(raw_val)
                current_val, current_owner, current_ts = self._get_active_fact(key)

                if current_val is not None:
                    if current_val != parsed_val:
                        conflict_type = "overwrite_conflict"
                        conflict_badge = "Overwrite Conflict"
                        conflict_reason = f"Overwrites active memory asserted by '{current_owner or 'unknown'}'"
                    else:
                        conflict_type = "duplicate_assertion"
                        conflict_badge = "Duplicate Assertion"
                        conflict_reason = "Identical value is already active in memory"
                else:
                    val_report = self.validate_memory_payload(key, parsed_val)
                    if not val_report.get("valid", True):
                        conflict_type = "schema_drift"
                        conflict_badge = "Schema Drift"
                        conflict_reason = f"Contract mismatch: {val_report.get('error', 'schema validation failed')}"
                    else:
                        conflict_type = "unverified_claim"
                        conflict_badge = "Unverified Claim"
                        conflict_reason = "Awaiting evidence-based operator review"

                prop_stats = {"claim_count": contribution_counts.get(agent_id, 0)}
                curr_stats = {"claim_count": contribution_counts.get(current_owner, 0)} if current_owner else None

                items.append({
                    "fact_key": key,
                    "value": parsed_val,
                    "agent_id": agent_id,
                    "branch": branch,
                    "timestamp": ts,
                    "current_value": current_val,
                    "current_owner": current_owner,
                    "current_timestamp": current_ts,
                    "conflict_type": conflict_type,
                    "conflict_badge": conflict_badge,
                    "conflict_reason": conflict_reason,
                    "agent_stats": prop_stats,
                    "existing_owner_stats": curr_stats,
                })
        except Exception:
            pass
        return items

    def resolve_quarantine(
        self,
        fact_key: str,
        agent_id: str,
        action: str,  # "accept", "promote", "reject", "discard"
        edited_value: Any = None,
        reviewer: str = "",
        rationale: str = "Resolved via GMS Desktop UI",
    ) -> dict[str, Any]:
        if edited_value is not None:
            val_res = self.validate_memory_payload(fact_key, edited_value)
            if not val_res.get("valid", True):
                return {
                    "status": "error",
                    "message": f"Schema validation failed for edited value: {val_res.get('error')}",
                    "fact_key": fact_key,
                }
            if self.db_path.exists():
                try:
                    conn = sqlite3.connect(str(self.db_path))
                    c = conn.cursor()
                    val_str = json.dumps(edited_value) if isinstance(edited_value, (dict, list)) else str(edited_value)
                    c.execute(
                        "UPDATE gms_quarantined_facts SET value = ? WHERE fact_key = ? AND agent_id = ?",
                        (val_str, fact_key, agent_id),
                    )
                    conn.commit()
                    conn.close()
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to persist edited value: {e}",
                        "fact_key": fact_key,
                    }

        import reviewers
        reviewer_ok, reviewer_or_error = reviewers.validate_reviewer_id(reviewer, mem_root=self.mem_root)
        if not reviewer_ok:
            return {"status": "error", "message": reviewer_or_error, "error": reviewer_or_error}

        action_norm = "promote" if action in ("accept", "promote") else "discard"
        res = memory_mcp_server.tool_mem_resolve_quarantine({
            "key": fact_key,
            "agent_id": agent_id,
            "action": action_norm,
            "agent": reviewer_or_error,
            "rationale": rationale,
        })
        is_error = res.startswith("ERROR:")
        return {
            "status": "error" if is_error else "success",
            "message": res,
            "action": action,
            "action_normalized": action_norm,
            "fact_key": fact_key,
            "agent_id": agent_id,
            "reviewer": reviewer_or_error,
        }

    def stage_in_quarantine(
        self,
        fact_key: str,
        value: Any,
        agent_id: str = "daily-note",
        branch: str = "main",
    ) -> dict[str, Any]:
        val_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        memory_mcp_server.quarantine_fact(fact_key, val_str, agent_id, branch)
        return {
            "status": "success",
            "message": f"Fact '{fact_key}' staged in quarantine for operator review.",
            "fact_key": fact_key,
            "agent_id": agent_id,
        }

    def get_triage_history(self, limit: int = 25) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        if not self.db_path.exists():
            return history

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()

            # 1. Quarantine reviews if available
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_quarantine_reviews'")
            if c.fetchone():
                c.execute(
                    """
                    SELECT fact_key, agent_id, reviewer_id, rating, rationale, timestamp
                    FROM gms_quarantine_reviews
                    ORDER BY timestamp DESC LIMIT ?
                    """,
                    (limit,)
                )
                for r in c.fetchall():
                    history.append({
                        "type": "review",
                        "fact_key": r[0],
                        "agent_id": r[1],
                        "reviewer": r[2] or "unattributed",
                        "action": "promoted" if r[3] in ("endorse", "promote") else "discarded",
                        "rationale": r[4] or "Quarantine review",
                        "timestamp": r[5],
                    })

            # 2. Claim transitions (superseded, retracted, active with supersedes)
            c.execute(
                """
                SELECT claim_id, memory_kind, memory_key, agent_id, status, contradiction_type, created_at, supersedes_claim_id
                FROM gms_claims
                WHERE status IN ('superseded', 'retracted', 'discarded') OR supersedes_claim_id IS NOT NULL
                ORDER BY claim_id DESC LIMIT ?
                """,
                (limit,)
            )
            for r in c.fetchall():
                action_str = "promoted" if r[4] == "active" else r[4]
                history.append({
                    "type": "claim_transition",
                    "claim_id": r[0],
                    "fact_key": f"{r[1]}.{r[2]}" if r[1] != "semantic" and not r[2].startswith(f"{r[1]}.") else r[2],
                    "agent_id": r[3],
                    "action": action_str,
                    "reviewer": "system",
                    "rationale": r[5] or "Ledger transition",
                    "timestamp": r[6],
                    "supersedes": r[7],
                })
            conn.close()
        except Exception:
            pass

        history.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)
        return history[:limit]

    # =========================================================================
    # 5. Bi-Temporal Knowledge Graph
    # =========================================================================
    def get_graph_data(
        self,
        as_of: str | None = None,
        include_expired: bool = False,
    ) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        if not self.db_path.exists():
            return {
                "nodes": [],
                "edges": [],
                "facets": {"types": {}, "predicates": {}},
                "totals": {"nodes": 0, "edges": 0},
            }

        as_of_dt = None
        if as_of:
            try:
                as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            except Exception:
                pass

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()

            # Load entities
            raw_entities: dict[int, dict[str, Any]] = {}
            c.execute("SELECT entity_id, name, entity_type, summary, created_at, updated_at FROM gms_entities")
            for eid, name, etype, summary, created_at, updated_at in c.fetchall():
                normalized_type = str(etype or "CONCEPT").strip().upper()
                raw_entities[eid] = {
                    "id": eid,
                    "label": name,
                    "type": normalized_type,
                    "summary": summary or "",
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "active_degree": 0,
                    "historical_degree": 0,
                    "evidence_count": 0,
                    "first_seen": created_at,
                    "last_seen": updated_at or created_at,
                    "literal_like": _is_literal_like(name),
                    "aliases": [],
                }

            # Count evidence from gms_memory_entity_links if table exists
            try:
                c.execute("SELECT entity_id, COUNT(*) FROM gms_memory_entity_links GROUP BY entity_id")
                for eid, count in c.fetchall():
                    if eid in raw_entities:
                        raw_entities[eid]["evidence_count"] += count
            except Exception:
                pass

            # Load relationships
            c.execute(
                """
                SELECT relationship_id, subject_entity_id, predicate, object_entity_id,
                       object_literal, valid_from, valid_to, source_claim_id, created_at
                FROM gms_relationships
                """
            )
            predicate_facets: dict[str, int] = {}

            for rid, subj_id, pred, obj_id, obj_lit, v_from, v_to, source_claim_id, rel_created_at in c.fetchall():
                is_active = (v_to is None)

                # Filter by as_of point in time if provided
                if as_of_dt:
                    try:
                        v_from_dt = datetime.fromisoformat(v_from.replace("Z", "+00:00")) if v_from else None
                        v_to_dt = datetime.fromisoformat(v_to.replace("Z", "+00:00")) if v_to else None
                        if v_from_dt and v_from_dt > as_of_dt:
                            continue
                        if v_to_dt and v_to_dt <= as_of_dt:
                            continue
                    except Exception:
                        pass
                elif not include_expired and not is_active:
                    continue

                if obj_id is not None:
                    provenance = []
                    if source_claim_id:
                        provenance.append({"kind": "claim", "id": source_claim_id})

                    edges.append({
                        "id": rid,
                        "from": subj_id,
                        "to": obj_id,
                        "label": pred,
                        "valid_from": v_from,
                        "valid_to": v_to,
                        "active": is_active,
                        "evidence_count": max(1, len(provenance)),
                        "provenance": provenance,
                    })

                    # Track degrees & timestamps on nodes
                    for nid in (subj_id, obj_id):
                        if nid in raw_entities:
                            if is_active:
                                raw_entities[nid]["active_degree"] += 1
                            else:
                                raw_entities[nid]["historical_degree"] += 1
                            raw_entities[nid]["evidence_count"] += 1
                            if v_from and (not raw_entities[nid]["first_seen"] or v_from < str(raw_entities[nid]["first_seen"])):
                                raw_entities[nid]["first_seen"] = v_from
                            ts_latest = v_to or v_from or rel_created_at
                            if ts_latest and (not raw_entities[nid]["last_seen"] or ts_latest > str(raw_entities[nid]["last_seen"])):
                                raw_entities[nid]["last_seen"] = ts_latest

                    predicate_facets[pred] = predicate_facets.get(pred, 0) + 1

            type_facets: dict[str, int] = {}
            for node in raw_entities.values():
                nodes.append(node)
                t = node["type"]
                type_facets[t] = type_facets.get(t, 0) + 1

            conn.close()
        except Exception:
            pass

        return {
            "nodes": nodes,
            "edges": edges,
            "facets": {
                "types": type_facets,
                "predicates": predicate_facets,
            },
            "totals": {
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

    def get_entity_evidence(self, entity_id: int | str) -> dict[str, Any]:
        eid = int(entity_id) if str(entity_id).isdigit() else None
        if not eid or not self.db_path.exists():
            return {"entity_id": entity_id, "found": False, "evidence": []}

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("SELECT entity_id, name, entity_type, summary, created_at, updated_at FROM gms_entities WHERE entity_id = ?", (eid,))
            row = c.fetchone()
            if not row:
                conn.close()
                return {"entity_id": eid, "found": False}

            _, name, etype, summary, created_at, updated_at = row
            etype_norm = str(etype or "CONCEPT").strip().upper()

            # Linked memories
            links = []
            try:
                c.execute("SELECT memory_ref, relationship, created_at FROM gms_memory_entity_links WHERE entity_id = ?", (eid,))
                for mref, rel, cat in c.fetchall():
                    links.append({"ref": mref, "relationship": rel, "created_at": cat})
            except Exception:
                pass

            # Matching claims
            claims = []
            try:
                c.execute(
                    """
                    SELECT claim_id, memory_kind, memory_key, value, agent_id, status, confidence, created_at
                    FROM gms_claims
                    WHERE memory_key = ? OR memory_key LIKE ? OR value LIKE ?
                    ORDER BY created_at DESC LIMIT 20
                    """,
                    (name, f"%.{name}%", f"%{name}%")
                )
                for cid, kind, mkey, val, agent, status, conf, cat in c.fetchall():
                    claims.append({
                        "claim_id": cid,
                        "kind": kind,
                        "key": mkey,
                        "value": parse_payload(val),
                        "agent": agent,
                        "status": status,
                        "confidence": conf,
                        "created_at": cat,
                    })
            except Exception:
                pass

            # Connected relationships
            relationships = []
            active_rel_count = 0
            historical_rel_count = 0
            c.execute(
                """
                SELECT r.relationship_id, r.predicate, r.valid_from, r.valid_to,
                       r.subject_entity_id, s.name, s.entity_type,
                       r.object_entity_id, o.name, o.entity_type
                FROM gms_relationships r
                LEFT JOIN gms_entities s ON r.subject_entity_id = s.entity_id
                LEFT JOIN gms_entities o ON r.object_entity_id = o.entity_id
                WHERE r.subject_entity_id = ? OR r.object_entity_id = ?
                """,
                (eid, eid)
            )
            for rid, pred, v_from, v_to, s_id, s_name, s_type, o_id, o_name, o_type in c.fetchall():
                is_active = (v_to is None)
                if is_active:
                    active_rel_count += 1
                else:
                    historical_rel_count += 1
                is_subject = (s_id == eid)
                other_id = o_id if is_subject else s_id
                other_name = o_name if is_subject else s_name
                other_type = (o_type or "CONCEPT").upper() if is_subject else (s_type or "CONCEPT").upper()
                relationships.append({
                    "relationship_id": rid,
                    "direction": "outgoing" if is_subject else "incoming",
                    "predicate": pred,
                    "other_entity": {"id": other_id, "name": other_name, "type": other_type},
                    "active": is_active,
                    "valid_from": v_from,
                    "valid_to": v_to,
                })

            conn.close()

            # Determine quality status
            evidence_count = len(links) + len(claims)
            if evidence_count >= 2 and active_rel_count >= 1:
                quality_status = "well_supported"
            elif evidence_count >= 2:
                quality_status = "multiple_references"
            elif evidence_count == 1:
                quality_status = "thin_evidence"
            elif active_rel_count == 0 and historical_rel_count > 0:
                quality_status = "historical_only"
            elif active_rel_count == 0:
                quality_status = "unlinked"
            elif not summary:
                quality_status = "missing_summary"
            else:
                quality_status = "active"

            return {
                "entity_id": eid,
                "found": True,
                "name": name,
                "type": etype_norm,
                "summary": summary or "",
                "created_at": created_at,
                "updated_at": updated_at,
                "quality_status": quality_status,
                "evidence_count": evidence_count,
                "active_relationships_count": active_rel_count,
                "historical_relationships_count": historical_rel_count,
                "claims": claims,
                "links": links,
                "relationships": relationships,
            }
        except Exception as e:
            return {"entity_id": eid, "found": False, "error": str(e)}

    def get_relationship_evidence(self, relationship_id: int | str) -> dict[str, Any]:
        rid = int(relationship_id) if str(relationship_id).isdigit() else None
        if not rid or not self.db_path.exists():
            return {"relationship_id": relationship_id, "found": False}

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute(
                """
                SELECT r.relationship_id, r.subject_entity_id, s.name, s.entity_type,
                       r.predicate, r.object_entity_id, o.name, o.entity_type,
                       r.valid_from, r.valid_to, r.source_claim_id, r.created_at
                FROM gms_relationships r
                LEFT JOIN gms_entities s ON r.subject_entity_id = s.entity_id
                LEFT JOIN gms_entities o ON r.object_entity_id = o.entity_id
                WHERE r.relationship_id = ?
                """,
                (rid,)
            )
            row = c.fetchone()
            if not row:
                conn.close()
                return {"relationship_id": rid, "found": False}

            _, s_id, s_name, s_type, pred, o_id, o_name, o_type, v_from, v_to, claim_id, rel_cat = row

            provenance = []
            claim_detail = None
            if claim_id:
                c.execute("SELECT claim_id, memory_key, value, agent_id, status, created_at FROM gms_claims WHERE claim_id = ?", (claim_id,))
                c_row = c.fetchone()
                if c_row:
                    claim_detail = {
                        "claim_id": c_row[0],
                        "key": c_row[1],
                        "value": parse_payload(c_row[2]),
                        "agent": c_row[3],
                        "status": c_row[4],
                        "created_at": c_row[5],
                    }
                    provenance.append({"kind": "claim", "id": claim_id, "agent": c_row[3], "key": c_row[1]})

            # Supersession timeline (all relationships between same subject & predicate)
            timeline = []
            c.execute(
                """
                SELECT r.relationship_id, r.predicate, o.name, r.valid_from, r.valid_to, r.created_at
                FROM gms_relationships r
                LEFT JOIN gms_entities o ON r.object_entity_id = o.entity_id
                WHERE r.subject_entity_id = ? AND r.predicate = ?
                ORDER BY r.valid_from ASC, r.created_at ASC
                """,
                (s_id, pred)
            )
            for h_rid, h_pred, h_oname, h_vfrom, h_vto, h_cat in c.fetchall():
                timeline.append({
                    "relationship_id": h_rid,
                    "predicate": h_pred,
                    "target": h_oname,
                    "valid_from": h_vfrom,
                    "valid_to": h_vto,
                    "active": (h_vto is None),
                    "created_at": h_cat,
                })

            conn.close()
            return {
                "relationship_id": rid,
                "found": True,
                "subject": {"id": s_id, "name": s_name, "type": (s_type or "CONCEPT").upper()},
                "predicate": pred,
                "object": {"id": o_id, "name": o_name, "type": (o_type or "CONCEPT").upper()},
                "active": (v_to is None),
                "valid_from": v_from,
                "valid_to": v_to,
                "created_at": rel_cat,
                "claim": claim_detail,
                "provenance": provenance,
                "timeline": timeline,
                "evidence_count": len(provenance) if provenance else 1,
            }
        except Exception as e:
            return {"relationship_id": rid, "found": False, "error": str(e)}

    def get_entity_duplicates(self, entity_id: int | str | None = None) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []

        target_id = int(entity_id) if entity_id and str(entity_id).isdigit() else None
        duplicates = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("SELECT entity_id, name, entity_type, summary FROM gms_entities")
            all_entities = c.fetchall()
            conn.close()

            def clean_name(s: str) -> str:
                return re.sub(r"[\W_]+", "", s.lower())

            def tokens(s: str) -> set[str]:
                return set(re.split(r"[\W_]+", s.lower())) - {"", "the", "a", "an", "pool", "node", "server"}

            for i in range(len(all_entities)):
                e1 = all_entities[i]
                if target_id and e1[0] != target_id:
                    continue
                c1 = clean_name(e1[1])
                t1 = tokens(e1[1])

                for j in range(i + 1, len(all_entities)):
                    e2 = all_entities[j]
                    if target_id and e2[0] != target_id and e1[0] != target_id:
                        continue

                    c2 = clean_name(e2[1])
                    t2 = tokens(e2[1])

                    reason = None
                    score = 0.0

                    # Rule 1: exact case-insensitive match
                    if e1[1].lower() == e2[1].lower() and e1[0] != e2[0]:
                        reason = "Exact case-insensitive match"
                        score = 1.0
                    # Rule 2: normalized punctuation/spacing match (e.g. minipc vs mini-pc)
                    elif c1 == c2 and len(c1) >= 3:
                        reason = "Normalized punctuation and spacing match"
                        score = 0.95
                    # Rule 3: high token overlap (Jaccard >= 0.75)
                    elif t1 and t2:
                        intersection = t1 & t2
                        union = t1 | t2
                        jaccard = len(intersection) / len(union) if union else 0
                        if jaccard >= 0.75:
                            reason = f"High token overlap ({round(jaccard * 100)}% match)"
                            score = round(jaccard, 2)

                    if reason:
                        duplicates.append({
                            "entity_a": {"id": e1[0], "name": e1[1], "type": (e1[2] or "CONCEPT").upper()},
                            "entity_b": {"id": e2[0], "name": e2[1], "type": (e2[2] or "CONCEPT").upper()},
                            "reason": reason,
                            "similarity": score,
                        })
        except Exception:
            pass

        return duplicates

    # =========================================================================
    # 6. Concepts & Entity Extraction
    # =========================================================================
    def get_concepts(self) -> dict[str, Any]:
        concepts_by_type: dict[str, list[dict[str, Any]]] = {}
        if not self.db_path.exists():
            return {"groups": {}, "total_entities": 0}

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute(
                """
                SELECT e.entity_id, e.name, e.entity_type, e.summary,
                       (SELECT COUNT(*) FROM gms_relationships r WHERE r.subject_entity_id = e.entity_id OR r.object_entity_id = e.entity_id) as edge_count
                FROM gms_entities e
                ORDER BY edge_count DESC, e.name ASC
                """
            )
            for eid, name, etype, summary, edge_count in c.fetchall():
                t = etype or "CONCEPT"
                if t not in concepts_by_type:
                    concepts_by_type[t] = []
                concepts_by_type[t].append({
                    "id": eid,
                    "name": name,
                    "type": t,
                    "summary": summary,
                    "edge_count": edge_count,
                })
            conn.close()
        except Exception:
            pass

        total = sum(len(items) for items in concepts_by_type.values())
        return {"groups": concepts_by_type, "total_entities": total}

    def extract_from_text(self, text: str) -> dict[str, Any]:
        """Extract candidate facts and graph triples from text without persisting."""
        candidates = harvest._extract_candidate_facts(text)
        validated_candidates = []
        for k, v, kind in candidates:
            is_valid, norm, err = validate_fact(k, v)
            validated_candidates.append({
                "key": k,
                "value": norm,
                "valid": is_valid,
                "error": err,
                "kind": kind,
            })

        triples = memory_mcp_server.extract_graph_triples(text)
        known_entities: dict[str, dict[str, Any]] = {}
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT entity_id, name, entity_type FROM gms_entities")
                known_entities = {
                    str(name).strip().casefold(): {"id": eid, "name": name, "type": etype or "CONCEPT"}
                    for eid, name, etype in c.fetchall()
                }
                conn.close()
            except Exception:
                pass

        mentioned: dict[str, dict[str, Any]] = {}
        for subject, _predicate, obj in triples:
            for name, role in ((subject, "subject"), (obj, "object")):
                normalized = str(name).strip().casefold()
                if not normalized:
                    continue
                existing = known_entities.get(normalized)
                if normalized not in mentioned:
                    mentioned[normalized] = {
                        "name": existing["name"] if existing else str(name).strip(),
                        "status": "existing" if existing else "new",
                        "entity_id": existing["id"] if existing else None,
                        "type": existing["type"] if existing else "UNCLASSIFIED",
                        "roles": [],
                        "mentions": len(re.findall(re.escape(str(name).strip()), text, flags=re.IGNORECASE)),
                    }
                if role not in mentioned[normalized]["roles"]:
                    mentioned[normalized]["roles"].append(role)
        return {
            "candidate_facts": validated_candidates,
            "extracted_triples": [{"subject": s, "predicate": p, "object": o} for s, p, o in triples],
            "entity_candidates": list(mentioned.values()),
            "review_required": any(item["status"] == "new" for item in mentioned.values()),
        }

    # =========================================================================
    # 7. Daily Notes & Memory Consolidation ("Agentic Sleep")
    # =========================================================================
    def get_daily_note(self, date_str: str | None = None) -> dict[str, Any]:
        dt = date_str or datetime.now().strftime("%Y-%m-%d")
        daily_dir = self.mem_root / "episodic" / "history"
        daily_file = daily_dir / f"{dt}.md"

        content = ""
        exists = daily_file.exists()
        if exists:
            try:
                content = daily_file.read_text(errors="replace")
            except Exception:
                pass
        else:
            journal_file = self.mem_root / "episodic" / "journal.md"
            if journal_file.exists():
                try:
                    j_text = journal_file.read_text(errors="replace")
                    pattern = rf"(###\s+{re.escape(dt)}[\s\S]*?)(?=\n###|\Z)"
                    matched_entries = [m.group(1).strip() for m in re.finditer(pattern, j_text)]
                    if matched_entries:
                        content = f"# Daily Note — {dt} (Archived Journal)\n\n" + "\n\n".join(matched_entries)
                        exists = True
                except Exception:
                    pass
            if not exists:
                content = f"# Daily Note — {dt}\n\n- Quick notes, observations, or facts here...\n"

        return {
            "date": dt,
            "path": str(daily_file) if not exists and not content.startswith("# Daily Note —") else (str(journal_file) if exists and not daily_file.exists() else str(daily_file)),
            "exists": exists,
            "content": content,
        }

    def save_daily_note(self, date_str: str, content: str) -> dict[str, Any]:
        clean_date = str(date_str).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", clean_date):
            raise ValueError(f"Invalid date format: '{date_str}'. Expected YYYY-MM-DD.")

        daily_dir = self.mem_root / "episodic" / "history"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_file = (daily_dir / f"{clean_date}.md").resolve()
        if daily_dir.resolve() not in daily_file.parents and daily_file != daily_dir.resolve():
            raise ValueError("Path traversal detected in date parameter.")

        daily_file.write_text(content, encoding="utf-8")

        # Also append milestone summary to journal.md if relevant
        journal_file = self.mem_root / "episodic" / "journal.md"
        if journal_file.exists():
            try:
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(journal_file, "a", encoding="utf-8") as jf:
                    jf.write(f"\n\n<!-- Desktop Note Auto-Sync {stamp} -->\n")
            except Exception:
                pass

        return {
            "status": "success",
            "date": date_str,
            "path": str(daily_file),
            "size_bytes": len(content.encode("utf-8")),
        }

    def harvest_daily_note(self, date_str: str, content: str | None = None) -> dict[str, Any]:
        """Consolidate a daily note into facts, graph relationships, and vectors."""
        if content is not None:
            self.save_daily_note(date_str, content)

        daily_file = self.mem_root / "episodic" / "history" / f"{date_str}.md"
        text = ""
        if daily_file.exists():
            text = daily_file.read_text(errors="replace")

        report = harvest.harvest_session(
            # The desktop requested the harvest; the deterministic harvest
            # worker is the extractor. It is not a claim that a person wrote
            # every source sentence.
            agent="system",
            summary=f"Daily Note Consolidation ({date_str})",
            text=text,
            incremental_index=True,
            mem_root=self.mem_root,
        )
        report["total_extracted"] = len(report.get("facts_saved", [])) + len(report.get("facts_rejected", []))
        report["saved_facts"] = report.get("facts_saved", [])
        report["rejected_facts"] = report.get("facts_rejected", [])
        return report

    # =========================================================================
    # 8. Apple Reminders Integration (macOS Safe Mode)
    # =========================================================================
    def get_reminders(self) -> dict[str, Any]:
        if sys.platform != "darwin":
            return {
                "supported": False,
                "message": "Apple Reminders is only available on macOS.",
                "reminders": [],
            }

        # Fast, targeted one-liner fetching incomplete reminder names separated by newline to preserve commas in titles
        script = '''tell application "Reminders"
            set remList to {}
            repeat with r in (every reminder of default list whose completed is false)
                set end of remList to (name of r)
            end repeat
            set AppleScript's text item delimiters to linefeed
            return remList as text
        end tell'''
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=6,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return {"supported": True, "reminders": []}

            raw_names = [n.strip() for n in res.stdout.strip().splitlines() if n.strip()]
            reminders = [{"title": name, "completed": False} for name in raw_names]
            return {"supported": True, "reminders": reminders}
        except Exception as e:
            return {"supported": True, "error": str(e), "reminders": []}

    def create_reminder(self, title: str, notes: str = "", due_date: str = "") -> dict[str, Any]:
        if sys.platform != "darwin":
            return {
                "supported": False,
                "message": "Apple Reminders is only available on macOS.",
            }

        safe_title = title.replace('"', '\\"')
        safe_notes = notes.replace('"', '\\"')
        if due_date:
            safe_notes = f"{safe_notes} (Due: {due_date})".strip() if safe_notes else f"Due: {due_date}"
        props = f'name:"{safe_title}", body:"{safe_notes}"'
        script = f'tell application "Reminders" to make new reminder with properties {{{props}}}'
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=6,
            )
            if res.returncode == 0:
                return {"status": "success", "title": title}
            return {"status": "error", "message": res.stderr.strip()}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # =========================================================================
    # 7. Project Context Workspace & Context Packets
    # =========================================================================
    def _sanitize_project_id(self, project_id: str) -> str:
        if not project_id or not str(project_id).strip():
            raise ValueError("Project ID cannot be empty")
        clean = str(project_id).strip()
        if any(c in clean for c in ("/\\")):
            raise ValueError("Path traversal detected: slashes not allowed in project ID")
        if ".." in clean:
            raise ValueError("Path traversal detected: '..' not allowed in project ID")
        if any(ord(c) < 32 for c in clean):
            raise ValueError("Control characters not allowed in project ID")
        if not re.match(r"^[A-Za-z0-9_.-]+$", clean):
            raise ValueError(f"Invalid characters in project ID '{clean}'")
        return clean

    def _discover_projects(self) -> list[str]:
        projects = set()
        proj_dir = self.mem_root / "projects"
        if proj_dir.exists():
            for d in proj_dir.iterdir():
                if d.is_dir() and not d.name.startswith("."):
                    projects.add(d.name)
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_tasks'")
                if c.fetchone():
                    c.execute("SELECT DISTINCT project FROM gms_tasks WHERE project IS NOT NULL AND project != ''")
                    for row in c.fetchall():
                        if row[0]:
                            projects.add(row[0].strip())
                conn.close()
            except Exception:
                pass
        merged: dict[str, str] = {}
        for p in sorted(projects):
            k = p.lower()
            if k not in merged:
                merged[k] = p
        return sorted(merged.values(), key=lambda s: s.lower())

    def _parse_project_brief(self, content: str) -> dict[str, Any]:
        if not content or not content.strip():
            return {"purpose_status": "missing", "purpose": "", "overview": "", "requirements": []}

        cleaned = re.sub(r"\[Core goals and project scope\]|\[Key requirement \d+\]", "", content).strip()
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
        substantive = [l for l in lines if not l.startswith("#") and not l.startswith("- [") and len(l) > 15]

        if not substantive or len(cleaned) < 50:
            return {"purpose_status": "placeholder", "purpose": "", "overview": "", "requirements": []}

        overview = ""
        matches = re.findall(r"##\s+Overview\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
        for m in matches:
            c = re.sub(r"\[Core goals and project scope\]", "", m).strip()
            if len(c) > 20:
                overview = c
                break
        if not overview and substantive:
            overview = substantive[0]

        purpose = overview.splitlines()[0].strip() if overview else (substantive[0] if substantive else "")

        reqs: list[str] = []
        req_m = re.search(r"##\s+(?:Key\s+)?Requirements\s*\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
        if req_m:
            for line in req_m.group(1).strip().splitlines():
                line = line.strip().lstrip("-*").strip()
                if line and not line.startswith("[Key requirement"):
                    reqs.append(line)

        return {
            "purpose_status": "present",
            "purpose": purpose,
            "overview": overview,
            "requirements": reqs,
        }

    def _redact_secrets(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r'(Bearer\s+)[A-Za-z0-9_\-\.]{15,}', r'\1[REDACTED_TOKEN]', text)
        text = re.sub(r'\b(sk-[A-Za-z0-9]{20,})\b', '[REDACTED_API_KEY]', text)
        text = re.sub(r'\b(gh[ospr]_[A-Za-z0-9]{20,})\b', '[REDACTED_GITHUB_TOKEN]', text)
        text = re.sub(r'\b(glpat-[A-Za-z0-9_\-]{20,})\b', '[REDACTED_GITLAB_TOKEN]', text)
        text = re.sub(r'\b(AKIA[0-9A-Z]{16})\b', '[REDACTED_AWS_KEY]', text)
        text = re.sub(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]', text)
        text = re.sub(r'(api[_-]?key\s*[:=]\s*["\']?)[A-Za-z0-9_\-]{16,}(["\']?)', r'\1[REDACTED_API_KEY]\2', text, flags=re.IGNORECASE)
        text = re.sub(r'(password\s*[:=]\s*["\']?)[^"\'\s]{8,}(["\']?)', r'\1[REDACTED_PASSWORD]\2', text, flags=re.IGNORECASE)
        return text

    def _extract_structured_decisions(self, project_id: str) -> list[dict[str, Any]]:
        decisions: list[dict[str, Any]] = []
        superseded_keys: set[str] = set()
        facts_file = self.mem_root / "semantic" / "facts.json"
        if facts_file.exists():
            try:
                facts = json.loads(facts_file.read_text(errors="replace"))
                for k, v in facts.items():
                    parsed = parse_payload(v)
                    if isinstance(parsed, dict):
                        is_decision = (
                            parsed.get("record_type") in ("decision", "policy")
                            or "decision" in parsed
                            or "rationale" in parsed
                            or (parsed.get("status") in ("accepted", "proposed", "superseded", "retired", "rejected", "specified") and ("implications" in parsed or "scope" in parsed))
                        )
                        if is_decision:
                            clean_pid = project_id.lower()
                            key_lower = k.lower()
                            scope_val = parsed.get("scope", "")
                            scope_str = json.dumps(scope_val).lower() if isinstance(scope_val, (dict, list)) else str(scope_val).lower()
                            prov = parsed.get("provenance", {})
                            prov_agent = prov.get("agent") or (prov.get("observed_agents", [None])[0] if isinstance(prov, dict) and prov.get("observed_agents") else None)
                            prov_date = prov.get("date") or (prov.get("extracted_at") if isinstance(prov, dict) else None)

                            tag = "inferred"
                            if key_lower.startswith(clean_pid + ".") or key_lower.startswith(clean_pid + "_"):
                                tag = "explicit"
                            elif clean_pid in ("global-memory", "mbrain") and (key_lower.startswith("mbrain.") or key_lower.startswith("gms.")):
                                tag = "explicit"
                            elif clean_pid in scope_str or parsed.get("project") == project_id or (isinstance(scope_val, dict) and scope_val.get("project") == project_id):
                                tag = "explicit"
                            elif clean_pid == "global-memory" and k in ("mbrain.agent_trust_ui", "mbrain.pass3_project_context"):
                                tag = "explicit"
                            else:
                                if "global" in scope_str or "universal" in scope_str or (isinstance(scope_val, dict) and scope_val.get("level") == "system"):
                                    tag = "global"

                            if tag in ("explicit", "global") or clean_pid in key_lower or clean_pid in str(parsed).lower():
                                dec_text = parsed.get("statement") or parsed.get("decision") or k
                                raw_status = parsed.get("status")
                                if not raw_status and isinstance(parsed.get("review"), dict):
                                    raw_status = parsed["review"].get("status")
                                if not raw_status:
                                    raw_status = "accepted"

                                impls = parsed.get("implications") or []
                                if isinstance(impls, str):
                                    impls = [impls]

                                for sup in parsed.get("freshness", {}).get("supersedes", []):
                                    superseded_keys.add(sup.lower())

                                decisions.append({
                                    "key": k,
                                    "decision": dec_text,
                                    "statement": dec_text,
                                    "status": raw_status,
                                    "rationale": parsed.get("rationale") or "",
                                    "implications": impls,
                                    "scope": scope_val,
                                    "author": prov_agent or "system",
                                    "effective_date": prov_date or "",
                                    "provenance_tag": tag,
                                    "provenance": prov,
                                    "schema_version": parsed.get("schema_version"),
                                    "record_type": parsed.get("record_type", "decision"),
                                    "raw": parsed,
                                })
            except Exception:
                pass

        if superseded_keys:
            decisions = [d for d in decisions if d["key"].lower() not in superseded_keys]

        bank_pat = self.mem_root / "projects" / project_id / "systemPatterns.md"
        if bank_pat.exists():
            try:
                txt = bank_pat.read_text(errors="replace")
                m = re.search(r"##\s+Key\s+Decisions\s*\n(.*?)(?=\n##|\Z)", txt, re.DOTALL)
                if m:
                    for line in m.group(1).strip().splitlines():
                        line = line.strip().lstrip("-*").strip()
                        if line and not line.startswith("[Design decision"):
                            if not any(d["decision"] == line for d in decisions):
                                decisions.append({
                                    "key": f"{project_id}.pattern",
                                    "decision": line,
                                    "status": "accepted",
                                    "rationale": "Extracted from systemPatterns.md",
                                    "implications": [],
                                    "scope": project_id,
                                    "author": "project-bank",
                                    "effective_date": datetime.fromtimestamp(bank_pat.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d"),
                                    "provenance_tag": "inferred",
                                    "raw": {"decision": line},
                                })
            except Exception:
                pass

        return decisions

    def get_projects(self, sort: str = "recent", q: str = "") -> dict[str, Any]:
        project_ids = self._discover_projects()
        projects_summary = []

        task_counts: dict[str, dict[str, int]] = {}
        task_activity: dict[str, str] = {}
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_tasks'")
                if c.fetchone():
                    c.execute("""
                        SELECT project, status, count(*)
                        FROM gms_tasks
                        WHERE project IS NOT NULL AND project != ''
                        GROUP BY project, status
                    """)
                    for proj, status, cnt in c.fetchall():
                        p_clean = proj.lower()
                        if p_clean not in task_counts:
                            task_counts[p_clean] = {"open_tasks": 0, "blocked": 0, "pending_handoffs": 0}
                        if status in ("open", "in_progress", "blocked", "handed_off"):
                            task_counts[p_clean]["open_tasks"] += cnt
                        if status == "blocked":
                            task_counts[p_clean]["blocked"] += cnt

                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_handoffs'")
                    if c.fetchone():
                        c.execute("""
                            SELECT t.project, count(*)
                            FROM gms_handoffs h
                            JOIN gms_tasks t ON h.task_id = t.task_id
                            WHERE h.acknowledged_at IS NULL
                            GROUP BY t.project
                        """)
                        for proj, cnt in c.fetchall():
                            p_clean = proj.lower()
                            if p_clean not in task_counts:
                                task_counts[p_clean] = {"open_tasks": 0, "blocked": 0, "pending_handoffs": 0}
                            task_counts[p_clean]["pending_handoffs"] += cnt

                    c.execute("""
                        SELECT project, max(updated_at)
                        FROM gms_tasks
                        WHERE project IS NOT NULL AND project != ''
                        GROUP BY project
                    """)
                    for proj, ts in c.fetchall():
                        if ts:
                            task_activity[proj.lower()] = str(ts)

                conn.close()
            except Exception:
                pass

        now = datetime.now(timezone.utc)
        expected_bank_files = (
            "projectBrief.md", "activeContext.md", "systemPatterns.md", "progress.md", "techContext.md"
        )
        for pid in project_ids:
            clean_id = self._sanitize_project_id(pid)
            proj_folder = self.mem_root / "projects" / clean_id
            brief_file = proj_folder / "projectBrief.md"
            active_file = proj_folder / "activeContext.md"

            brief_raw = brief_file.read_text(errors="replace") if brief_file.exists() else ""
            brief_parsed = self._parse_project_brief(brief_raw)

            timestamps: list[datetime] = []
            present_bank_files: list[str] = []
            nonempty_bank_files: list[str] = []
            total_bank_bytes = 0
            if proj_folder.exists():
                for filename in expected_bank_files:
                    f = proj_folder / filename
                    if not f.exists():
                        continue
                    present_bank_files.append(filename)
                    try:
                        size = f.stat().st_size
                        total_bank_bytes += size
                        if size > 0 and f.read_text(errors="replace").strip():
                            nonempty_bank_files.append(filename)
                        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                        if size > 0:
                            timestamps.append(mtime)
                    except Exception:
                        pass

            latest_task_ts = task_activity.get(clean_id.lower())
            if latest_task_ts:
                try:
                    t_dt = datetime.fromisoformat(latest_task_ts.replace(" ", "T")).replace(tzinfo=timezone.utc)
                    timestamps.append(t_dt)
                except Exception:
                    pass

            last_dt = max(timestamps) if timestamps else now
            last_activity_str = last_dt.strftime("%Y-%m-%d %H:%M:%S")
            stale_days = max(0, (now - last_dt).days)
            missing_bank_files = [f for f in expected_bank_files if f not in nonempty_bank_files]
            completion_ratio = round(len(nonempty_bank_files) / len(expected_bank_files), 2)

            counts = task_counts.get(clean_id.lower(), {"open_tasks": 0, "blocked": 0, "pending_handoffs": 0})

            attention: list[str] = []
            if brief_parsed["purpose_status"] == "placeholder":
                attention.append("Placeholder project brief")
            elif brief_parsed["purpose_status"] == "missing":
                attention.append("Missing project brief")

            if counts["blocked"] > 0:
                attention.append(f"{counts['blocked']} blocked task(s)")
            if counts["pending_handoffs"] > 0:
                attention.append(f"{counts['pending_handoffs']} pending handoff(s)")

            if active_file.exists():
                active_age_days = (now - datetime.fromtimestamp(active_file.stat().st_mtime, tz=timezone.utc)).days
                if active_age_days > 14:
                    attention.append(f"Active context stale ({active_age_days}d)")
            if missing_bank_files:
                attention.append(f"Memory bank incomplete ({len(nonempty_bank_files)}/{len(expected_bank_files)})")

            if q:
                query_l = q.lower()
                matches_q = (
                    query_l in clean_id.lower()
                    or query_l in brief_parsed["purpose"].lower()
                    or query_l in brief_parsed["overview"].lower()
                )
                if not matches_q:
                    continue

            projects_summary.append({
                "project_id": clean_id,
                "name": clean_id,
                "purpose": brief_parsed["purpose"],
                "purpose_status": brief_parsed["purpose_status"],
                "last_activity_at": last_activity_str,
                "last_activity": last_activity_str,
                "stale_days": stale_days,
                "freshness": "fresh" if stale_days <= 7 else ("aging" if stale_days <= 30 else "stale"),
                "counts": counts,
                **counts,
                "attention": attention,
                "attention_count": len(attention),
                "bank_completeness": {
                    "expected_files": list(expected_bank_files),
                    "present_files": present_bank_files,
                    "nonempty_files": nonempty_bank_files,
                    "missing_files": missing_bank_files,
                    "completion_ratio": completion_ratio,
                    "total_bytes": total_bank_bytes,
                },
            })

        if sort == "recent":
            projects_summary.sort(key=lambda p: p["last_activity_at"], reverse=True)
        elif sort == "name":
            projects_summary.sort(key=lambda p: p["name"].lower())
        elif sort == "attention":
            projects_summary.sort(key=lambda p: (len(p["attention"]), p["counts"]["open_tasks"]), reverse=True)
        elif sort == "stale":
            projects_summary.sort(key=lambda p: p["last_activity_at"])

        return {
            "projects": projects_summary,
            "total": len(projects_summary),
            "sort": sort,
        }

    def get_project_detail(self, project_id: str) -> dict[str, Any]:
        clean_id = self._sanitize_project_id(project_id)
        proj_folder = self.mem_root / "projects" / clean_id

        # 1. Brief
        brief_file = proj_folder / "projectBrief.md"
        brief_raw = brief_file.read_text(errors="replace") if brief_file.exists() else ""
        brief = self._parse_project_brief(brief_raw)

        # 2. Active Context
        active_file = proj_folder / "activeContext.md"
        active_raw = active_file.read_text(errors="replace") if active_file.exists() else ""

        current_focus = ""
        f_m = re.search(r"##\s+Current\s+Focus\s*\n(.*?)(?=\n##|\Z)", active_raw, re.DOTALL)
        if f_m:
            current_focus = f_m.group(1).strip()
        if not current_focus or "[Active task" in current_focus:
            for line in active_raw.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "[Active" not in line and len(line) > 10:
                    current_focus = line
                    break

        constraints = []
        c_m = re.search(r"##\s+(?:(?:Active\s+)?Constraints(?:\s*&\s*Boundaries)?|Boundaries|Do\s+Not\s+Touch)\s*\n(.*?)(?=\n##|\Z)", active_raw, re.IGNORECASE | re.DOTALL)
        if c_m:
            for l in c_m.group(1).strip().splitlines():
                l = l.strip().lstrip("-*").strip()
                if l and not l.startswith("["):
                    constraints.append(l)

        known_gaps = []
        g_m = re.search(r"##\s+(?:(?:Known|Context|Open)\s+Gaps(?:\s*&\s*(?:Open\s+Items|Blockers|Ambiguities))?|Gaps|Issues|Blockers)\s*\n(.*?)(?=\n##|\Z)", active_raw, re.IGNORECASE | re.DOTALL)
        if g_m:
            for l in g_m.group(1).strip().splitlines():
                l = l.strip().lstrip("-*").strip()
                if l and not l.startswith("["):
                    known_gaps.append(l)

        verification_state = ""
        v_m = re.search(r"##\s+(?:Verification(?:\s+State|\s*&\s*Acceptance)?)\s*\n(.*?)(?=\n##|\Z)", active_raw, re.IGNORECASE | re.DOTALL)
        if v_m:
            verification_state = v_m.group(1).strip()

        active_updates = []
        raw_updates = re.split(r"###\s+Update\s+\((.*?)\)", active_raw)
        for i in range(1, len(raw_updates), 2):
            ts = raw_updates[i].strip()
            body = raw_updates[i+1].strip() if i+1 < len(raw_updates) else ""
            summary = body.splitlines()[0].strip() if body else ""
            active_updates.append({
                "timestamp": ts,
                "summary": summary,
                "content": body,
            })

        active_context = {
            "current_focus": current_focus,
            "constraints": constraints,
            "known_gaps": known_gaps,
            "verification_state": verification_state,
            "updates": active_updates,
            "raw": active_raw,
            "mtime": datetime.fromtimestamp(active_file.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if active_file.exists() else None,
        }

        # 3. Patterns, Tech, Progress
        patterns_file = proj_folder / "systemPatterns.md"
        patterns_raw = patterns_file.read_text(errors="replace") if patterns_file.exists() else ""

        tech_file = proj_folder / "techContext.md"
        tech_raw = tech_file.read_text(errors="replace") if tech_file.exists() else ""

        progress_file = proj_folder / "progress.md"
        progress_raw = progress_file.read_text(errors="replace") if progress_file.exists() else ""

        expected_bank_files = ("projectBrief.md", "activeContext.md", "systemPatterns.md", "progress.md", "techContext.md")
        nonempty_bank_files = []
        total_bank_bytes = 0
        substantive_mtimes = []
        for filename in expected_bank_files:
            bank_file = proj_folder / filename
            if not bank_file.exists():
                continue
            try:
                total_bank_bytes += bank_file.stat().st_size
                if bank_file.read_text(errors="replace").strip():
                    nonempty_bank_files.append(filename)
                    substantive_mtimes.append(datetime.fromtimestamp(bank_file.stat().st_mtime, tz=timezone.utc))
            except Exception:
                pass
        last_activity = max(substantive_mtimes).strftime("%Y-%m-%d %H:%M:%S") if substantive_mtimes else None
        bank_completeness = {
            "expected_files": list(expected_bank_files),
            "nonempty_files": nonempty_bank_files,
            "missing_files": [f for f in expected_bank_files if f not in nonempty_bank_files],
            "completion_ratio": round(len(nonempty_bank_files) / len(expected_bank_files), 2),
            "total_bytes": total_bank_bytes,
        }

        # 4. Tasks from SQLite
        tasks_grouped: dict[str, list[dict[str, Any]]] = {
            "in_progress": [],
            "needs_review": [],
            "open": [],
            "completed": [],
        }
        total_tasks = 0
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_tasks'")
                if c.fetchone():
                    c.execute("""
                        SELECT task_id, project, title, objective, status, owner_agent, lease_expires_at,
                               revision, parent_task_id, created_by, created_at, updated_at, completed_at
                        FROM gms_tasks
                        WHERE project = ? OR lower(project) = ?
                        ORDER BY updated_at DESC, task_id ASC
                    """, (clean_id, clean_id.lower()))
                    rows = c.fetchall()
                    total_tasks = len(rows)
                    for r in rows:
                        t = {
                            "task_id": r[0],
                            "project": r[1],
                            "title": r[2],
                            "objective": r[3],
                            "status": r[4],
                            "owner_agent": r[5],
                            "lease_expires_at": r[6],
                            "revision": r[7],
                            "parent_task_id": r[8],
                            "created_by": r[9],
                            "created_at": str(r[10]),
                            "updated_at": str(r[11]),
                            "completed_at": str(r[12]) if r[12] else None,
                        }
                        c.execute("""
                            SELECT checkpoint_id, revision, agent_id, label, state_json, artifact_refs_json, created_at
                            FROM gms_task_checkpoints
                            WHERE task_id = ?
                            ORDER BY checkpoint_id DESC LIMIT 1
                        """, (t["task_id"],))
                        cp_row = c.fetchone()
                        t["latest_checkpoint"] = {
                            "checkpoint_id": cp_row[0],
                            "revision": cp_row[1],
                            "agent_id": cp_row[2],
                            "label": cp_row[3],
                            "state": json.loads(cp_row[4]) if cp_row[4] else {},
                            "artifact_refs": json.loads(cp_row[5]) if cp_row[5] else [],
                            "created_at": str(cp_row[6]),
                        } if cp_row else None

                        c.execute("""
                            SELECT handoff_id, revision, source_agent, target_agent, objective, completed_work, next_action, acknowledged_at, created_at
                            FROM gms_handoffs
                            WHERE task_id = ?
                            ORDER BY handoff_id DESC LIMIT 1
                        """, (t["task_id"],))
                        h_row = c.fetchone()
                        t["latest_handoff"] = {
                            "handoff_id": h_row[0],
                            "revision": h_row[1],
                            "source_agent": h_row[2],
                            "target_agent": h_row[3],
                            "objective": h_row[4],
                            "completed_work": h_row[5],
                            "next_action": h_row[6],
                            "acknowledged_at": str(h_row[7]) if h_row[7] else None,
                            "created_at": str(h_row[8]),
                        } if h_row else None

                        st = t["status"].lower()
                        if st == "in_progress":
                            tasks_grouped["in_progress"].append(t)
                        elif st in ("handed_off", "needs_review"):
                            tasks_grouped["needs_review"].append(t)
                        elif st in ("completed", "cancelled"):
                            tasks_grouped["completed"].append(t)
                        else:
                            tasks_grouped["open"].append(t)

                conn.close()
            except Exception:
                pass

        # 5. Decisions
        decisions = self._extract_structured_decisions(clean_id)

        # 6. Attention Cards
        attention_cards = []
        if brief["purpose_status"] == "placeholder":
            attention_cards.append({
                "title": "Placeholder Project Brief",
                "why": "The brief contains scaffold placeholders. Agents lack authoritative project goals.",
                "action": "Add project brief with clear overview and requirements",
                "source": f"projects/{clean_id}/projectBrief.md",
            })
        elif brief["purpose_status"] == "missing":
            attention_cards.append({
                "title": "Missing Project Brief",
                "why": "No projectBrief.md found for this project.",
                "action": "Initialize memory bank and provide project brief",
                "source": f"projects/{clean_id}/",
            })

        for t in tasks_grouped["needs_review"]:
            attention_cards.append({
                "title": f"Task Awaiting Review: {t['title']}",
                "why": f"Handed off by {t.get('latest_handoff', {}).get('source_agent', 'agent')}; pending acknowledgement.",
                "action": t.get("latest_handoff", {}).get("next_action") or "Review and acknowledge handoff",
                "source": f"task:{t['task_id']}",
            })

        # 7. Metadata
        repo_path = None
        host_identity = "local"
        facts_file = self.mem_root / "semantic" / "facts.json"
        if facts_file.exists():
            try:
                facts = json.loads(facts_file.read_text(errors="replace"))
                repo_path = facts.get(f"project.{clean_id}.repo_path") or facts.get(f"{clean_id}.repo_path")
                host_identity = facts.get(f"project.{clean_id}.host") or "local"
            except Exception:
                pass

        if clean_id == "global-memory" and not repo_path:
            repo_path = str(REPO_ROOT)

        return {
            "project_id": clean_id,
            "name": clean_id,
            "brief": brief,
            "active_context": active_context,
            "system_patterns": {"raw": patterns_raw},
            "tech_context": {"raw": tech_raw},
            "progress": {"raw": progress_raw},
            "tasks": tasks_grouped,
            "total_tasks": total_tasks,
            "decisions": decisions,
            "attention_cards": attention_cards,
            "attention_items": attention_cards,
            "repo_path": repo_path,
            "host": host_identity,
            "last_activity": last_activity,
            "bank_completeness": bank_completeness,
        }

    def get_project_activity(self, project_id: str, limit: int = 50, before: str | None = None) -> list[dict[str, Any]]:
        clean_id = self._sanitize_project_id(project_id)
        events: list[dict[str, Any]] = []

        # Bank updates
        proj_folder = self.mem_root / "projects" / clean_id
        if proj_folder.exists():
            for fname in ("activeContext.md", "progress.md"):
                f = proj_folder / fname
                if f.exists():
                    try:
                        content = f.read_text(errors="replace")
                        raw_updates = re.split(r"###\s+Update\s+\((.*?)\)", content)
                        for i in range(1, len(raw_updates), 2):
                            ts = raw_updates[i].strip()
                            body = raw_updates[i+1].strip() if i+1 < len(raw_updates) else ""
                            summary = body.splitlines()[0].strip() if body else ""
                            agent = "agent"
                            for cand in ("Codex", "Antigravity", "Gemini", "Mihir", "system"):
                                if cand.lower() in summary.lower() or cand.lower() in ts.lower():
                                    agent = cand
                                    break
                            events.append({
                                "timestamp": ts,
                                "summary": summary,
                                "detail": body,
                                "agent": agent,
                                "source_type": "evidence" if ("test" in summary.lower() or "pass" in summary.lower()) else "claim",
                                "source_ref": f"projects/{clean_id}/{fname}",
                            })
                    except Exception:
                        pass

        # Tasks activity from SQLite
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_tasks'")
                if c.fetchone():
                    # Checkpoints
                    c.execute("""
                        SELECT cp.checkpoint_id, cp.task_id, cp.revision, cp.agent_id, cp.label, cp.created_at, t.title
                        FROM gms_task_checkpoints cp
                        JOIN gms_tasks t ON cp.task_id = t.task_id
                        WHERE t.project = ? OR lower(t.project) = ?
                    """, (clean_id, clean_id.lower()))
                    for cpid, tid, rev, aid, lbl, ts, title in c.fetchall():
                        events.append({
                            "timestamp": str(ts),
                            "summary": f"Checkpoint '{lbl}' on task {tid}: {title}",
                            "detail": f"Revision {rev} recorded by {aid}",
                            "agent": aid,
                            "source_type": "evidence",
                            "source_ref": f"task:{tid}#checkpoint:{cpid}",
                        })

                    # Handoffs
                    c.execute("""
                        SELECT h.handoff_id, h.task_id, h.revision, h.source_agent, h.target_agent, h.next_action, h.created_at, t.title
                        FROM gms_handoffs h
                        JOIN gms_tasks t ON h.task_id = t.task_id
                        WHERE t.project = ? OR lower(t.project) = ?
                    """, (clean_id, clean_id.lower()))
                    for hid, tid, rev, s_agent, t_agent, next_act, ts, title in c.fetchall():
                        events.append({
                            "timestamp": str(ts),
                            "summary": f"Handoff from {s_agent} to {t_agent or 'next agent'}: {next_act}",
                            "detail": f"Task {tid}: {title}",
                            "agent": s_agent,
                            "source_type": "claim",
                            "source_ref": f"task:{tid}#handoff:{hid}",
                        })
                conn.close()
            except Exception:
                pass

        # Sort descending by timestamp
        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)

        if before:
            events = [e for e in events if (e.get("timestamp") or "") < before]

        return events[:limit]

    def get_project_knowledge(self, project_id: str, kind: str = "all", limit: int = 50) -> dict[str, Any]:
        clean_id = self._sanitize_project_id(project_id)
        memories = []
        entities = []
        artifacts = []

        # 1. Scoped memories
        mem_res = self.get_memories(limit=100)
        for m in mem_res.get("memories", []):
            k = m["key"].lower()
            tag = None
            reason = ""
            if k.startswith(clean_id.lower() + ".") or k.startswith(clean_id.lower() + "_"):
                tag = "explicit"
                reason = f"Directly prefixed with project namespace '{clean_id}'"
            elif clean_id.lower() in ("global-memory", "mbrain") and (k.startswith("mbrain.") or k.startswith("gms.")):
                tag = "explicit"
                reason = "Authoritative Mbrain/GMS system fact"
            elif clean_id.lower() in str(m.get("value", "")).lower():
                tag = "inferred"
                reason = f"Contains reference to project '{clean_id}'"

            if tag:
                m_copy = dict(m)
                m_copy["provenance_tag"] = tag
                m_copy["why_here"] = reason
                memories.append(m_copy)

        # 2. Scoped entities from SQLite
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_entities'")
                if c.fetchone():
                    c.execute("""
                        SELECT entity_id, name, type, summary, confidence, created_at
                        FROM gms_entities
                        WHERE lower(name) LIKE ? OR lower(summary) LIKE ?
                        LIMIT ?
                    """, (f"%{clean_id.lower()}%", f"%{clean_id.lower()}%", limit))
                    for eid, name, etype, summary, conf, ts in c.fetchall():
                        entities.append({
                            "entity_id": eid,
                            "name": name,
                            "type": etype,
                            "summary": summary,
                            "confidence": conf,
                            "provenance_tag": "linked" if clean_id.lower() in name.lower() else "inferred",
                            "why_here": f"Entity matching project '{clean_id}'",
                        })

                    # Task checkpoints artifact references
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_task_checkpoints'")
                    if c.fetchone():
                        c.execute("""
                            SELECT cp.artifact_refs_json, t.task_id, t.title
                            FROM gms_task_checkpoints cp
                            JOIN gms_tasks t ON cp.task_id = t.task_id
                            WHERE t.project = ? OR lower(t.project) = ?
                        """, (clean_id, clean_id.lower()))
                        for art_json, tid, title in c.fetchall():
                            if art_json:
                                try:
                                    arts = json.loads(art_json)
                                    for a in arts:
                                        artifacts.append({
                                            "path": a,
                                            "task_id": tid,
                                            "task_title": title,
                                            "provenance_tag": "linked",
                                            "why_here": f"Artifact registered by task checkpoint in {tid}",
                                        })
                                except Exception:
                                    pass
                conn.close()
            except Exception:
                pass

        return {
            "project_id": clean_id,
            "memories": memories[:limit],
            "entities": entities[:limit],
            "artifacts": artifacts[:limit],
        }

    def get_task_resume(self, task_id: str) -> dict[str, Any]:
        clean_tid = str(task_id).strip()
        if not clean_tid:
            return {"error": "task_id is required"}

        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("""
                    SELECT task_id, project, title, objective, status, owner_agent, lease_expires_at,
                           revision, parent_task_id, created_by, created_at, updated_at, completed_at
                    FROM gms_tasks WHERE task_id = ?
                """, (clean_tid,))
                row = c.fetchone()
                if not row:
                    conn.close()
                    return {"error": f"Task '{clean_tid}' not found"}

                task = {
                    "task_id": row[0],
                    "project": row[1],
                    "title": row[2],
                    "objective": row[3],
                    "status": row[4],
                    "owner_agent": row[5],
                    "lease_expires_at": row[6],
                    "revision": row[7],
                    "parent_task_id": row[8],
                    "created_by": row[9],
                    "created_at": str(row[10]),
                    "updated_at": str(row[11]),
                    "completed_at": str(row[12]) if row[12] else None,
                }

                c.execute("""
                    SELECT checkpoint_id, revision, agent_id, label, state_json, artifact_refs_json, claim_refs_json, episode_refs_json, created_at
                    FROM gms_task_checkpoints WHERE task_id = ? ORDER BY checkpoint_id DESC LIMIT 1
                """, (clean_tid,))
                cp = c.fetchone()
                checkpoint_payload = None
                if cp:
                    checkpoint_payload = {
                        "checkpoint_id": cp[0],
                        "revision": cp[1],
                        "agent_id": cp[2],
                        "label": cp[3],
                        "state": json.loads(cp[4]) if cp[4] else {},
                        "artifact_refs": json.loads(cp[5]) if cp[5] else [],
                        "claim_refs": json.loads(cp[6]) if cp[6] else [],
                        "episode_refs": json.loads(cp[7]) if cp[7] else [],
                        "created_at": str(cp[8]),
                    }

                c.execute("""
                    SELECT handoff_id, revision, source_agent, target_agent, objective, completed_work, next_action, blockers, acceptance_criteria, context_json, artifact_refs_json, acknowledged_at, created_at
                    FROM gms_handoffs WHERE task_id = ? ORDER BY handoff_id DESC LIMIT 1
                """, (clean_tid,))
                ho = c.fetchone()
                handoff_payload = None
                if ho:
                    handoff_payload = {
                        "handoff_id": ho[0],
                        "revision": ho[1],
                        "source_agent": ho[2],
                        "target_agent": ho[3],
                        "objective": ho[4],
                        "completed_work": ho[5],
                        "next_action": ho[6],
                        "blockers": ho[7],
                        "acceptance_criteria": ho[8],
                        "context": json.loads(ho[9]) if ho[9] else {},
                        "artifact_refs": json.loads(ho[10]) if ho[10] else [],
                        "acknowledged_at": str(ho[11]) if ho[11] else None,
                        "created_at": str(ho[12]),
                    }

                conn.close()
                resume_context = {
                    "task": task,
                    "checkpoint": checkpoint_payload,
                    "handoff": handoff_payload,
                }
                canonical = json.dumps(resume_context, sort_keys=True, separators=(",", ":"), default=str)
                context_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                objective = (handoff_payload or {}).get("objective") or task.get("objective") or task.get("title")
                next_action = (handoff_payload or {}).get("next_action") or "Inspect the latest checkpoint and continue toward the acceptance criteria."
                base_prompt = (
                    f"Resume task {task['task_id']} for project {task.get('project') or 'unscoped'}. "
                    f"Goal: {objective}. Next action: {next_action}. "
                    f"Use the attached structured context and preserve context hash {context_hash}."
                )
                resume_context["resume_with_context"] = {
                    "context_packet_hash": context_hash,
                    "producer": (handoff_payload or {}).get("source_agent") or task.get("owner_agent") or task.get("created_by"),
                    "intended_consumer": (handoff_payload or {}).get("target_agent") or "any compatible agent",
                    "prompts": {agent: base_prompt + f" Target runtime: {agent}." for agent in ("codex", "antigravity", "gemini_cli", "terminal")},
                    "bundle": resume_context.copy(),
                }
                return resume_context
            except Exception as e:
                return {"error": str(e)}

        return {"error": "Database not initialized"}

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_task_create(data)
        try:
            return json.loads(res)
        except Exception:
            return {"status": "error", "message": res}

    def claim_task(self, data: dict[str, Any]) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_task_claim(data)
        try:
            return json.loads(res)
        except Exception:
            return {"status": "error", "message": res}

    def checkpoint_task(self, data: dict[str, Any]) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_task_checkpoint(data)
        try:
            return json.loads(res)
        except Exception:
            return {"status": "error", "message": res}

    def handoff_task(self, data: dict[str, Any]) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_handoff_create(data)
        try:
            return json.loads(res)
        except Exception:
            return {"status": "error", "message": res}

    def complete_task(self, data: dict[str, Any]) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_task_complete(data)
        try:
            return json.loads(res)
        except Exception:
            return {"status": "error", "message": res}

    def record_quarantine_review(self, data: dict[str, Any]) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_record_review(data)
        return {"status": "success" if "SUCCESS" in res else "error", "message": res}

    def get_retrieval_benchmarks(self, mode: str = "synthetic") -> dict[str, Any]:
        try:
            import eval_retrieval_benchmark
            import dataclasses
            report = eval_retrieval_benchmark.run_benchmark(engine_mode=mode)
            return dataclasses.asdict(report)
        except Exception as e:
            return {"error": f"Failed to run retrieval benchmark: {e}"}

    def preview_context_packet(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = self._sanitize_project_id(payload.get("project_id", ""))
        profile = str(payload.get("profile", "standard")).lower()
        if profile not in ("small", "standard", "deep"):
            profile = "standard"
        task_id = payload.get("task_id")
        target = payload.get("target") or {"agent": "Antigravity", "harness": "Antigravity IDE", "host": "local"}

        detail = self.get_project_detail(project_id)
        brief = detail.get("brief", {})
        active = detail.get("active_context", {})

        objective = brief.get("purpose") or detail.get("name")
        current_state = active.get("current_focus") or "No active focus specified."
        constraints = active.get("constraints") or []
        known_gaps = active.get("known_gaps") or []
        verification = [active.get("verification_state")] if active.get("verification_state") else []

        include_proposed = bool(payload.get("include_proposed", False))
        decisions_raw = list(detail.get("decisions", []))

        # If include_proposed is True, load proposed candidates from gms_context_candidates for this project
        if include_proposed and self.db_path.exists():
            try:
                cand_list = memory_mcp_server.get_context_candidates(
                    project=project_id,
                    record_type="decision",
                    status="proposed",
                    db_path=self.db_path,
                )
                for c in cand_list:
                    cp = c.get("payload", {})
                    dec_text = cp.get("statement") or cp.get("decision") or c.get("canonical_key")
                    decisions_raw.append({
                        "key": c.get("canonical_key"),
                        "decision": dec_text,
                        "statement": dec_text,
                        "status": "proposed",
                        "rationale": cp.get("rationale", ""),
                        "implications": cp.get("implications", []),
                        "scope": cp.get("scope", {}),
                        "author": c.get("extractor_agent", "llm-proposed"),
                        "provenance_tag": "explicit",
                        "provenance": cp.get("provenance", {}),
                        "schema_version": c.get("schema_version"),
                        "record_type": "decision",
                        "is_proposed_candidate": True,
                        "raw": cp,
                    })
            except Exception:
                pass

        decisions_formatted = []
        for d in decisions_raw:
            st = d.get("status", "accepted")
            # Exclude proposed candidates by default unless explicitly included
            if st == "proposed" and not include_proposed:
                continue
            if st in ("superseded", "retired") and profile == "small":
                continue

            dec_item = {
                "decision": d.get("decision") or d.get("statement"),
                "statement": d.get("statement") or d.get("decision"),
                "rationale": d.get("rationale", ""),
                "status": st,
                "source_ref": d.get("key"),
                "implications": d.get("implications") if isinstance(d.get("implications"), list) else ([d.get("implications")] if d.get("implications") else []),
                "scope": d.get("scope", {}),
                "why_included": {
                    "project_linkage": "Explicit project scope" if d.get("provenance_tag") == "explicit" else "Global architectural policy",
                    "authority": (d.get("provenance", {}).get("provider") if isinstance(d.get("provenance"), dict) else None) or d.get("author") or "verified_review",
                    "freshness": "stale" if st in ("superseded", "retired") else "fresh",
                    "relevance": "Core decision for active project context",
                }
            }
            if d.get("is_proposed_candidate") or st == "proposed":
                dec_item["warning"] = "PROPOSED CANDIDATE — NOT CANONICAL TRUTH. Requires review before acceptance."
            decisions_formatted.append(dec_item)

        recent_work = []
        for u in active.get("updates", [])[:5]:
            recent_work.append(f"[{u['timestamp']}] {u['summary']}")

        files = []
        proj_folder = self.mem_root / "projects" / project_id
        if proj_folder.exists():
            for f in sorted(proj_folder.glob("*.md")):
                files.append(f"projects/{project_id}/{f.name}")

        relevant_memories = []
        if profile in ("standard", "deep"):
            for d in decisions_raw:
                relevant_memories.append(f"{d['key']}: {d['decision']}")

        if profile == "deep":
            sys_pat = detail.get("system_patterns", {}).get("raw", "")
            if sys_pat:
                for line in sys_pat.splitlines():
                    if line.startswith("-") or line.startswith("##"):
                        recent_work.append(line)

        mtime_str = active.get("mtime")
        freshness_status = "fresh"
        freshness_reasons = []
        if not mtime_str:
            freshness_status = "possibly_stale"
            freshness_reasons.append("No active context timestamp found.")
        else:
            try:
                m_dt = datetime.fromisoformat(mtime_str.replace(" ", "T")).replace(tzinfo=timezone.utc)
                age_days = (datetime.now(timezone.utc) - m_dt).days
                if age_days > 14:
                    freshness_status = "stale"
                    freshness_reasons.append(f"Active context is {age_days} days old (>14d).")
                elif age_days > 3:
                    freshness_status = "possibly_stale"
                    freshness_reasons.append(f"Active context is {age_days} days old.")
                else:
                    freshness_reasons.append(f"Updated {age_days}d ago.")
            except Exception:
                freshness_status = "fresh"
                freshness_reasons.append("Recent activity.")

        # Secret redaction
        objective = self._redact_secrets(objective)
        current_state = self._redact_secrets(current_state)
        constraints = [self._redact_secrets(c) for c in constraints]
        known_gaps = [self._redact_secrets(g) for g in known_gaps]
        recent_work = [self._redact_secrets(w) for w in recent_work]
        verification = [self._redact_secrets(v) for v in verification]
        relevant_memories = [self._redact_secrets(m) for m in relevant_memories]
        for d in decisions_formatted:
            d["decision"] = self._redact_secrets(d["decision"])
            d["rationale"] = self._redact_secrets(d["rationale"])

        # Deterministic hashing payload
        hash_payload = {
            "budget_profile": profile,
            "constraints": sorted(constraints),
            "current_state": current_state,
            "decisions": sorted(decisions_formatted, key=lambda x: x["decision"]),
            "files": sorted(files),
            "known_gaps": sorted(known_gaps),
            "objective": objective,
            "packet_version": "gms-context-v1",
            "project": project_id,
            "recent_work": recent_work,
            "relevant_memories": sorted(relevant_memories),
            "source_refs": sorted(files),
            "target": target,
            "task_id": task_id,
            "verification": verification,
        }
        canonical_bytes = json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        content_hash = f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        packet_id = f"ctx_{project_id}_{content_hash[7:19]}"

        char_count = len(canonical_bytes)
        estimated_tokens = math.ceil(char_count / 4)

        packet = {
            "packet_version": "gms-context-v1",
            "packet_id": packet_id,
            "created_at": now_iso,
            "project": project_id,
            "task_id": task_id,
            "target": target,
            "objective": objective,
            "current_state": current_state,
            "decisions": decisions_formatted,
            "constraints": constraints,
            "known_gaps": known_gaps,
            "recent_work": recent_work,
            "verification": verification,
            "files": files,
            "relevant_memories": relevant_memories,
            "open_questions": [],
            "excluded": ["secrets", "cross-project-personal"],
            "source_refs": files,
            "freshness": {"status": freshness_status, "reasons": freshness_reasons},
            "budget": {"profile": profile, "estimated_tokens": estimated_tokens, "char_count": char_count},
            "content_hash": content_hash,
        }

        md_lines = [
            f"# Context Packet: {project_id} ({profile.capitalize()})",
            f"**Packet ID:** `{packet_id}` · **Target:** {target.get('agent', 'Agent')} ({target.get('harness', 'Harness')}) · **Hash:** `{content_hash}`",
            "",
            "## 1. Objective",
            objective or "No objective specified.",
            "",
            "## 2. Current State",
            current_state or "No current focus specified.",
            "",
            "## 3. Active Decisions & Rationale",
        ]
        if decisions_formatted:
            for d in decisions_formatted:
                warn_prefix = "⚠️ [PROPOSED CANDIDATE] " if d.get("warning") else ""
                md_lines.append(f"- {warn_prefix}**{d['decision']}** (`{d.get('status', 'accepted')}`)")
                if d.get("rationale"):
                    md_lines.append(f"  *Rationale:* {d['rationale']}")
                if d.get("implications"):
                    impls_str = "; ".join(d["implications"]) if isinstance(d["implications"], list) else str(d["implications"])
                    md_lines.append(f"  *Implications:* {impls_str}")
                why = d.get("why_included")
                if why:
                    md_lines.append(f"  *Why Included:* Linkage: {why.get('project_linkage')} · Authority: {why.get('authority')} · Freshness: {why.get('freshness')}")
                if d.get("warning"):
                    md_lines.append(f"  *Warning:* {d['warning']}")
        else:
            md_lines.append("- No active decisions recorded.")

        md_lines.extend([
            "",
            "## 4. Constraints & Do-Not-Touch Boundaries",
        ])
        if constraints:
            for c in constraints:
                md_lines.append(f"- {c}")
        else:
            md_lines.append("- None recorded.")

        md_lines.extend([
            "",
            "## 5. Recent Work & Updates",
        ])
        if recent_work:
            for w in recent_work:
                md_lines.append(f"- {w}")
        else:
            md_lines.append("- None recorded.")

        md_lines.extend([
            "",
            "## 6. Known Gaps & Blockers",
        ])
        if known_gaps:
            for g in known_gaps:
                md_lines.append(f"- {g}")
        else:
            md_lines.append("- None recorded.")

        md_lines.extend([
            "",
            "## 7. Verification State",
            "\n".join(verification) if verification else "No verification state recorded.",
            "",
            "## 8. Essential Files",
        ])
        if files:
            for f in files:
                md_lines.append(f"- `{f}`")
        else:
            md_lines.append("- None.")

        md_lines.extend([
            "",
            "## 9. Freshness & Budget",
            f"- **Freshness:** {freshness_status} ({', '.join(freshness_reasons)})",
            f"- **Budget:** ~{estimated_tokens} tokens ({char_count} chars)",
        ])

        markdown_text = "\n".join(md_lines)

        return {
            "packet": packet,
            "markdown": markdown_text,
            "content_hash": content_hash,
            "character_count": char_count,
            "estimated_tokens": estimated_tokens,
            "raw_payload": packet,
        }

    def export_context_packet(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = self.preview_context_packet(payload)
        packet = preview["packet"]
        packet_id = packet["packet_id"]

        out_dir = self.mem_root / "context_packets"
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / f"{packet_id}.json"
        md_path = out_dir / f"{packet_id}.md"

        json_path.write_text(json.dumps(packet, indent=2))
        md_path.write_text(preview["markdown"])

        return {
            "status": "success",
            "packet_id": packet_id,
            "filename": f"{packet_id}.md",
            "content_hash": preview["content_hash"],
            "json_path": str(json_path),
            "md_path": str(md_path),
            "character_count": preview["character_count"],
            "estimated_tokens": preview["estimated_tokens"],
            "budget": packet["budget"],
        }

    # =========================================================================
    # 8. Cross-View Hybrid Search & Entity Operations
    # =========================================================================
    def get_dream_cycle_status(self) -> dict[str, Any]:
        status_file = self.mem_root / "logs" / "dream_cycle_status.json"
        if status_file.exists():
            try:
                return json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"status": "idle", "message": "No dream cycle run recorded yet."}

    def merge_entities(self, source_id: int, target_id: int, reason: str = "") -> dict[str, Any]:
        if not self.db_path.exists():
            raise ValueError("Database does not exist")
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        try:
            c.execute("SELECT name, summary FROM gms_entities WHERE entity_id = ?", (source_id,))
            src_row = c.fetchone()
            c.execute("SELECT name, summary FROM gms_entities WHERE entity_id = ?", (target_id,))
            tgt_row = c.fetchone()
            if not src_row or not tgt_row:
                raise ValueError("Source or target entity does not exist")

            # Point relationships to target entity
            c.execute("UPDATE gms_relationships SET subject_entity_id = ? WHERE subject_entity_id = ?", (target_id, source_id))
            c.execute("UPDATE gms_relationships SET object_entity_id = ? WHERE object_entity_id = ?", (target_id, source_id))
            # Delete source entity
            c.execute("DELETE FROM gms_entities WHERE entity_id = ?", (source_id,))
            conn.commit()
            return {
                "status": "success",
                "source_id": source_id,
                "target_id": target_id,
                "target_name": tgt_row[0],
                "merged_source_name": src_row[0],
            }
        finally:
            conn.close()

    def search_hybrid(self, query: str, limit: int = 15) -> dict[str, Any]:
        query = (query or "").strip()
        if not query:
            return {"query": "", "memories": [], "entities": [], "triples": [], "projects": [], "vector_hits": []}

        # 1. Matching memories (facts.json)
        memories = []
        try:
            mem_res = self.get_memories(tier="all", query=query, limit=8)
            memories = mem_res.get("memories", [])[:8]
        except Exception:
            pass

        # 2. Matching entities & triples from SQLite
        entities = []
        triples = []
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                q_like = f"%{query}%"
                c.execute(
                    """
                    SELECT entity_id, name, entity_type, summary
                    FROM gms_entities
                    WHERE name LIKE ? OR summary LIKE ?
                    LIMIT 8
                    """,
                    (q_like, q_like)
                )
                for eid, name, etype, summary in c.fetchall():
                    entities.append({
                        "entity_id": eid,
                        "name": name,
                        "entity_type": etype,
                        "summary": summary or ""
                    })

                # 3. Matching triples
                c.execute(
                    """
                    SELECT r.relationship_id, s.name, r.predicate, COALESCE(o.name, r.object_literal)
                    FROM gms_relationships r
                    LEFT JOIN gms_entities s ON r.subject_entity_id = s.entity_id
                    LEFT JOIN gms_entities o ON r.object_entity_id = o.entity_id
                    WHERE s.name LIKE ? OR o.name LIKE ? OR r.predicate LIKE ? OR r.object_literal LIKE ?
                    LIMIT 8
                    """,
                    (q_like, q_like, q_like, q_like)
                )
                for rid, sname, pred, obj in c.fetchall():
                    triples.append({
                        "relationship_id": rid,
                        "subject": sname or "Unknown",
                        "predicate": pred,
                        "object": obj or "Unknown"
                    })
                conn.close()
            except Exception:
                pass

        # 4. Matching projects
        projects = []
        try:
            proj_res = self.get_projects(q=query)
            projects = proj_res.get("projects", [])[:5]
        except Exception:
            pass

        # 5. Vector / Episodic retrieval via memoryctl
        vector_hits = []
        try:
            script_path = Path(__file__).resolve().parent / "memoryctl.py"
            res = subprocess.run(
                [sys.executable, str(script_path), "index-query", query, "-k", "5", "--no-decay"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout:
                blocks = res.stdout.strip().split("\n\n")
                for block in blocks:
                    lines = [b.strip() for b in block.splitlines() if b.strip()]
                    if lines:
                        header = lines[0]
                        body = " ".join(lines[1:]) if len(lines) > 1 else ""
                        file_match = re.search(r'src=([^\s]+)', header)
                        hit_file = file_match.group(1) if file_match else ""
                        date_match = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', header + " " + body)
                        hit_date = date_match.group(1) if date_match else None
                        vector_hits.append({
                            "header": header,
                            "snippet": body,
                            "date": hit_date,
                            "file": hit_file,
                        })
        except Exception:
            pass

        return {
            "query": query,
            "memories": memories,
            "entities": entities,
            "triples": triples,
            "projects": projects,
            "vector_hits": vector_hits,
        }

    def get_effective_launchd_schedule(self, plist_path: Path | str | None = None) -> str:
        """Read effective launchd schedule from installed/checked-in plist or return 'Unavailable'."""
        import plistlib
        paths = []
        if plist_path:
            paths.append(Path(plist_path))
        paths.extend([
            Path.home() / "Library" / "LaunchAgents" / "com.user.gms-dream-cycle.plist",
            Path(__file__).resolve().parent.parent / "deploy" / "com.user.gms-dream-cycle.plist",
        ])
        for p in paths:
            if p.exists():
                try:
                    data = plistlib.loads(p.read_bytes())
                    interval = data.get("StartCalendarInterval")
                    if isinstance(interval, dict):
                        hour = interval.get("Hour", 0)
                        minute = interval.get("Minute", 0)
                        am_pm = "AM" if hour < 12 else "PM"
                        display_hour = hour if hour in (12, 0) else (hour % 12)
                        if display_hour == 0:
                            display_hour = 12
                        return f"{display_hour:02d}:{minute:02d} {am_pm} (Launchd Nightly)"
                except Exception:
                    pass
        return "Unavailable"

    # =========================================================================
    # 7. Context Harvesting & Review API (Pass 5)
    # =========================================================================
    def get_harvest_status(self) -> dict[str, Any]:
        """Aggregate queue counts and status for harvest review."""
        decisions_pending = 0
        project_state_pending = 0
        merge_suggestions = 0
        deferred_count = 0
        total_awaiting = 0

        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gms_context_candidates'")
                if c.fetchone():
                    c.execute("SELECT count(*) FROM gms_context_candidates WHERE review_status = 'proposed' AND record_type IN ('decision', 'policy')")
                    decisions_pending = c.fetchone()[0]

                    c.execute("SELECT count(*) FROM gms_context_candidates WHERE review_status = 'proposed' AND record_type = 'project_state'")
                    project_state_pending = c.fetchone()[0]

                    c.execute("SELECT count(*) FROM gms_context_candidates WHERE review_status = 'deferred'")
                    deferred_count = c.fetchone()[0]

                    c.execute("SELECT count(*) FROM gms_context_candidates WHERE review_status = 'proposed'")
                    total_awaiting = c.fetchone()[0]
                conn.close()
            except Exception:
                pass

        dream_status = self.get_dream_cycle_status()
        validation_failures = dream_status.get("candidates_rejected", 0)

        return {
            "status": "success",
            "decisions_policies_pending": decisions_pending,
            "project_state_pending": project_state_pending,
            "merge_suggestions": merge_suggestions,
            "validation_failures": validation_failures,
            "deferred_count": deferred_count,
            "total_awaiting_review": total_awaiting,
            "last_run": dream_status,
            "next_scheduled_run": self.get_effective_launchd_schedule(),
        }

    def get_harvest_candidates(
        self,
        project: str | None = None,
        record_type: str | None = None,
        status: str = "proposed",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return candidate cards with field diffs against active memory."""
        candidates = memory_mcp_server.get_context_candidates(
            project=project,
            record_type=record_type,
            status=None if status == "all" else status,
            limit=limit,
            offset=offset,
            db_path=self.db_path,
        )
        for cand in candidates:
            cand["diff"] = memory_mcp_server.get_candidate_diff(
                cand["canonical_key"],
                cand.get("payload", {}),
                db_path=self.db_path,
            )

        return {
            "status": "success",
            "total": len(candidates),
            "candidates": candidates,
        }

    def get_harvest_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Fetch single candidate card with diff."""
        cand = memory_mcp_server.get_context_candidate_by_id(candidate_id, db_path=self.db_path)
        if not cand:
            return {"status": "error", "error": f"Candidate '{candidate_id}' not found"}
        return {"status": "success", "candidate": cand}

    def review_harvest_candidate(self, candidate_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Perform review action on staged candidate."""
        action = data.get("action", "accept")
        reviewer = data.get("reviewer", "")
        rationale = data.get("rationale", "")
        edited_payload = data.get("edited_payload")
        merge_with_claim_id = data.get("merge_with_claim_id")
        expected_content_hash = data.get("expected_content_hash")

        res = memory_mcp_server.review_context_candidate(
            candidate_id=candidate_id,
            action=action,
            reviewer=reviewer,
            rationale=rationale,
            edited_payload=edited_payload,
            merge_with_claim_id=merge_with_claim_id,
            expected_content_hash=expected_content_hash,
            db_path=self.db_path,
        )
        if res.get("status") == "error":
            return res
        review_status = res.get("status")
        return {
            **res,
            "status": "success",
            "review_status": review_status,
        }

    def curate_harvest_candidates(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Preview or run evidence-gated system adjudication."""
        from autonomous_curation import curate_pending
        payload = data or {}
        return curate_pending(
            self.mem_root,
            apply=bool(payload.get("apply", False)),
            limit=int(payload.get("limit", 100)),
        )

    def contest_harvest_candidate(self, candidate_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Preview or apply an owner contest of a system decision."""
        from autonomous_curation import contest_candidate
        return contest_candidate(
            self.mem_root,
            candidate_id,
            str(data.get("rationale", "")),
            apply=bool(data.get("apply", False)),
        )

    def get_harvest_reviewers(self) -> dict[str, Any]:
        """Fetch list of valid registered reviewers."""
        import reviewers
        revs = reviewers.get_registered_reviewers(mem_root=self.mem_root)
        return {"status": "success", "reviewers": revs}

    def get_harvest_audit_history(self, candidate_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Fetch review audit trail."""
        history = memory_mcp_server.get_review_audit_history(candidate_id=candidate_id, limit=limit, db_path=self.db_path)
        return {"status": "success", "audit_history": history}

    def get_pollution_audit(self) -> dict[str, Any]:
        """Read-only scan of suspected test fixtures and synthetic pollution."""
        import pollution_audit
        findings = pollution_audit.run_pollution_audit(db_path=self.db_path, mem_root=self.mem_root)
        return {"status": "success", "audit": findings}

    def run_pollution_cleanup(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Surgically clean test fixtures and synthetic pollution."""
        import pollution_audit
        apply = bool(data.get("apply", False)) if data else False
        operator = str(data.get("operator", "mihir")) if data else "mihir"
        res = pollution_audit.run_pollution_cleanup(apply=apply, db_path=self.db_path, mem_root=self.mem_root, operator=operator)
        return {"status": "success", **res}

    def preview_migrate_flat(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dry-run or apply migration of legacy flat records."""
        import migrate_flat_records
        apply = bool(data.get("apply", False)) if data else False
        return migrate_flat_records.run_migration(apply=apply, mem_root=self.mem_root)

    def get_model_harvest_eval(self, live: bool = False) -> dict[str, Any]:
        """Evaluate local model harvesting performance."""
        import eval_model_harvesting
        return eval_model_harvesting.run_evaluation(run_live=live)

    # =========================================================================
    # Pass 8: Project Intelligence & Agent Continuity
    # =========================================================================
    def get_project_briefing(self, project_id: str, as_of: str | None = None, profile: str = "standard") -> dict[str, Any]:
        return generate_project_briefing(self.mem_root, project_id, as_of=as_of, profile=profile)

    def explain_project_briefing(self, project_id: str, as_of: str | None = None, profile: str = "standard") -> dict[str, Any]:
        briefing = self.get_project_briefing(project_id, as_of=as_of, profile=profile)
        return explain_project_briefing(briefing)

    def get_project_timeline(self, project_id: str, event_type: str | None = None, agent: str | None = None, limit: int = 50) -> dict[str, Any]:
        return get_project_timeline(self.mem_root, project_id, event_type=event_type, agent=agent, limit=limit)

    def get_resume_bundle(self, project_id: str, target_format: str = "antigravity", as_of: str | None = None, task_id: str | None = None) -> dict[str, Any]:
        return build_resume_bundle(self.mem_root, project_id, target_format=target_format, as_of=as_of, task_id=task_id)

    def get_decisions(self, project: str = "", include_superseded: bool = False) -> dict[str, Any]:
        return list_decisions(self.mem_root, project=project, include_superseded=include_superseded)

    def get_decision_detail(self, decision_id: str) -> dict[str, Any]:
        d = get_decision(self.mem_root, decision_id)
        if not d:
            return {"error": "DECISION_NOT_FOUND", "decision_id": decision_id}
        return d

    get_decision = get_decision_detail

    def get_decision_impact_analysis(self, decision_id: str) -> dict[str, Any]:
        return get_decision_impact(self.mem_root, decision_id)

    get_decision_impact = get_decision_impact_analysis

    def get_action_inbox(self, project: str = "", category: str | None = None) -> dict[str, Any]:
        res = list_inbox_items(self.mem_root, project=project)
        if category:
            res["items"] = [it for it in res.get("items", []) if it.get("category") == category]
            res["total_count"] = len(res["items"])
        return res

    def preview_inbox_action(self, inbox_id: str, action: str = "accept", project: str = "", reviewer: str = "mihir", rationale: str = "") -> dict[str, Any]:
        return preview_inbox_action(self.mem_root, inbox_id=inbox_id, action=action, project=project, reviewer=reviewer, rationale=rationale)

    def apply_inbox_action(self, inbox_id: str, project: str = "", reviewer: str = "", rationale: str = "", expected_hash: str | None = None) -> dict[str, Any]:
        import reviewers
        valid, normalized = reviewers.validate_reviewer_id(reviewer, mem_root=self.mem_root)
        if not valid:
            return {"status": "error", "error": normalized}
        preview = self.preview_inbox_action(inbox_id, project=project)
        if not preview.get("executable"):
            return {"status": "blocked", "error": preview.get("consequence", "Action not executable directly"), "preview": preview}
        if preview.get("target_type") == "candidate":
            from harvest import review_candidate
            candidate_id = preview.get("target_id")
            review_action = preview.get("suggested_action", "defer")
            return review_candidate(
                root=self.mem_root,
                candidate_id=candidate_id,
                action=review_action,
                reviewer=normalized,
                rationale=rationale or "Applied from action inbox",
                expected_hash=expected_hash
            )
        return {"status": "preview_only", "preview": preview}

    def get_repair_evidence(self, key: str) -> dict[str, Any]:
        return find_repair_evidence(self.mem_root, key)

    def analyze_repair_record(self, key: str) -> dict[str, Any]:
        return analyze_missing_fields(self.mem_root, key)

    def stage_repair_record(self, key: str, payload: dict[str, Any], apply: bool = False, actor: str = "", rationale: str = "Repaired from UI") -> dict[str, Any]:
        import reviewers
        valid, normalized = reviewers.validate_reviewer_id(actor, mem_root=self.mem_root)
        if not valid:
            return {"status": "error", "error": normalized}
        return stage_repair_candidate(self.mem_root, legacy_key=key, repaired_payload=payload, apply=apply, actor=normalized, rationale=rationale)

    def get_morning_briefing(self, project_id: str, as_of: str | None = None) -> dict[str, Any]:
        return generate_morning_briefing(self.mem_root, project_id, as_of=as_of)

    def list_morning_briefings(self) -> dict[str, Any]:
        return list_morning_briefings(self.mem_root)

    def get_resumption_evaluation(self) -> dict[str, Any]:
        return run_resumption_evaluation(self.mem_root)

# HTTP Server Handler
# =============================================================================
class GMSHTTPHandler(BaseHTTPRequestHandler):
    api = GMSDesktopAPI()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        if path == "/api/snapshot":
            self._send_json(self.api.get_snapshot())
        elif path == "/api/memories":
            tier = qs.get("tier", ["all"])[0]
            ns = qs.get("namespace", [""])[0]
            query = qs.get("q", [""])[0]
            sort = qs.get("sort", ["recent"])[0]
            limit = int(qs.get("limit", [100])[0])
            offset = int(qs.get("offset", [0])[0])
            self._send_json(self.api.get_memories(tier, ns, query, limit, offset, sort))
        elif path == "/api/quarantine":
            self._send_json(self.api.get_quarantine_items())
        elif path in ("/api/quarantine/history", "/api/triage/history"):
            limit = int(qs.get("limit", [25])[0])
            self._send_json(self.api.get_triage_history(limit))
        elif path == "/api/graph":
            as_of = qs.get("as_of", [None])[0]
            inc_exp = qs.get("include_expired", ["false"])[0].lower() == "true"
            self._send_json(self.api.get_graph_data(as_of, inc_exp))
        elif path == "/api/concepts":
            self._send_json(self.api.get_concepts())
        elif path in ("/api/entities/evidence", "/api/entity/evidence"):
            eid = qs.get("id", [""])[0] or qs.get("entity_id", [""])[0]
            self._send_json(self.api.get_entity_evidence(eid))
        elif path in ("/api/relationships/evidence", "/api/relationship/evidence"):
            rid = qs.get("id", [""])[0] or qs.get("relationship_id", [""])[0]
            self._send_json(self.api.get_relationship_evidence(rid))
        elif path in ("/api/entities/duplicates", "/api/entity/duplicates"):
            eid = qs.get("id", [None])[0]
            self._send_json(self.api.get_entity_duplicates(eid))
        elif path == "/api/daily_note":
            date_str = qs.get("date", [None])[0]
            self._send_json(self.api.get_daily_note(date_str))
        elif path == "/api/reminders":
            self._send_json(self.api.get_reminders())
        elif path == "/api/contracts":
            self._send_json(list_contracts())
        elif path == "/api/projects":
            sort = qs.get("sort", ["recent"])[0]
            query = qs.get("q", [""])[0]
            self._send_json(self.api.get_projects(sort=sort, q=query))
        elif path.startswith("/api/projects/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                pid = parts[2]
                try:
                    self._send_json(self.api.get_project_detail(pid))
                except ValueError as e:
                    self._send_json({"error": str(e)}, status=400)
            elif len(parts) == 4 and parts[3] == "briefing":
                pid = parts[2]
                as_of = qs.get("as_of", [None])[0]
                profile = qs.get("profile", ["standard"])[0]
                self._send_json(self.api.get_project_briefing(pid, as_of=as_of, profile=profile))
            elif len(parts) == 5 and parts[3] == "briefing" and parts[4] == "explain":
                pid = parts[2]
                as_of = qs.get("as_of", [None])[0]
                profile = qs.get("profile", ["standard"])[0]
                self._send_json(self.api.explain_project_briefing(pid, as_of=as_of, profile=profile))
            elif len(parts) == 4 and parts[3] == "timeline":
                pid = parts[2]
                ev_type = qs.get("type", [None])[0] or qs.get("event_type", [None])[0]
                agent = qs.get("agent", [None])[0]
                limit = int(qs.get("limit", [50])[0])
                self._send_json(self.api.get_project_timeline(pid, event_type=ev_type, agent=agent, limit=limit))
            elif len(parts) == 4 and parts[3] == "morning-briefing":
                pid = parts[2]
                as_of = qs.get("as_of", [None])[0]
                self._send_json(self.api.get_morning_briefing(pid, as_of=as_of))
            elif len(parts) == 4 and parts[3] == "activity":
                pid = parts[2]
                limit = int(qs.get("limit", [50])[0])
                before = qs.get("before", [None])[0]
                try:
                    self._send_json(self.api.get_project_activity(pid, limit=limit, before=before))
                except ValueError as e:
                    self._send_json({"error": str(e)}, status=400)
            elif len(parts) == 4 and parts[3] == "knowledge":
                pid = parts[2]
                kind = qs.get("kind", ["all"])[0]
                limit = int(qs.get("limit", [50])[0])
                try:
                    self._send_json(self.api.get_project_knowledge(pid, kind=kind, limit=limit))
                except ValueError as e:
                    self._send_json({"error": str(e)}, status=400)
            else:
                self._send_json({"error": "Endpoint not found"}, status=404)
        elif path.startswith("/api/tasks/") and path.endswith("/resume"):
            parts = path.strip("/").split("/")
            tid = parts[2] if len(parts) >= 3 else ""
            self._send_json(self.api.get_task_resume(tid))
        elif path == "/api/decisions":
            proj = qs.get("project", [""])[0]
            inc_sup = qs.get("include_superseded", ["false"])[0].lower() in ("true", "1")
            self._send_json(self.api.get_decisions(project=proj, include_superseded=inc_sup))
        elif path.startswith("/api/decisions/"):
            parts = path.strip("/").split("/")
            did = parts[2] if len(parts) >= 3 else ""
            if len(parts) == 4 and parts[3] == "impact":
                self._send_json(self.api.get_decision_impact_analysis(did))
            else:
                self._send_json(self.api.get_decision_detail(did))
        elif path == "/api/inbox":
            proj = qs.get("project", [""])[0]
            cat = qs.get("category", [None])[0]
            self._send_json(self.api.get_action_inbox(project=proj, category=cat))
        elif path.startswith("/api/repair/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "evidence":
                self._send_json(self.api.get_repair_evidence(parts[2]))
            elif len(parts) == 4 and parts[3] == "analyze":
                self._send_json(self.api.analyze_repair_record(parts[2]))
            else:
                self._send_json({"error": "Endpoint not found"}, status=404)
        elif path in ("/api/morning-briefings", "/api/morning_briefings"):
            self._send_json(self.api.list_morning_briefings())
        elif path in ("/api/eval/resumption", "/api/eval_resumption"):
            self._send_json(self.api.get_resumption_evaluation())
        elif path == "/api/search":
            q = qs.get("q", [""])[0]
            limit = int(qs.get("limit", [15])[0])
            self._send_json(self.api.search_hybrid(q, limit=limit))
        elif path in ("/api/dream-cycle/status", "/api/dream_cycle/status"):
            self._send_json(self.api.get_dream_cycle_status())
        elif path in ("/api/benchmarks", "/api/benchmarks/latest"):
            mode = qs.get("mode", ["synthetic"])[0]
            self._send_json(self.api.get_retrieval_benchmarks(mode=mode))
        elif path == "/api/harvest/status":
            self._send_json(self.api.get_harvest_status())
        elif path == "/api/harvest/candidates":
            proj = qs.get("project", [None])[0]
            rec_type = qs.get("type", [None])[0] or qs.get("record_type", [None])[0]
            st = qs.get("status", ["proposed"])[0]
            lim = int(qs.get("limit", [50])[0])
            off = int(qs.get("offset", [0])[0])
            self._send_json(self.api.get_harvest_candidates(project=proj, record_type=rec_type, status=st, limit=lim, offset=off))
        elif path.startswith("/api/harvest/candidates/"):
            cid = path[len("/api/harvest/candidates/"):].strip("/")
            self._send_json(self.api.get_harvest_candidate(cid))
        elif path == "/api/harvest/reviewers":
            self._send_json(self.api.get_harvest_reviewers())
        elif path == "/api/harvest/audit":
            cid = qs.get("candidate_id", [None])[0]
            lim = int(qs.get("limit", [50])[0])
            self._send_json(self.api.get_harvest_audit_history(candidate_id=cid, limit=lim))
        elif path == "/api/harvest/pollution/audit":
            self._send_json(self.api.get_pollution_audit())
        elif path == "/api/v1/memory-quality":
            self._send_json(self.api.get_memory_quality())
        elif path == "/api/v1/migration/inventory":
            self._send_json(self.api.get_migration_inventory())
        elif path == "/api/v1/aliases":
            self._send_json(self.api.get_aliases(qs.get("key", [""])[0]))
        elif path == "/api/v1/lifecycle/history":
            self._send_json(self.api.get_lifecycle_history(qs.get("record_id", [""])[0]))
        elif path == "/api/harvest/eval/model":
            run_live = qs.get("live", ["false"])[0].lower() in ("true", "1")
            self._send_json(self.api.get_model_harvest_eval(live=run_live))
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length)
        data = {}
        if body_bytes:
            try:
                data = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                pass

        if path == "/api/validate":
            key = data.get("key", "")
            val = data.get("value", "")
            self._send_json(self.api.validate_memory_payload(key, val))
        elif path == "/api/memories/fact":
            key = data.get("key", "")
            val = data.get("value", "")
            agent = data.get("agent", "")
            kind = data.get("kind", "semantic")
            self._send_json(self.api.save_fact(key, val, agent, kind))
        elif path == "/api/memories/delete":
            key = data.get("key", "")
            agent = data.get("agent", "")
            self._send_json(self.api.delete_fact(key, agent))
        elif path == "/api/quarantine/resolve":
            key = data.get("fact_key", "") or data.get("key", "")
            agent = data.get("agent_id", "") or data.get("agent", "")
            action = data.get("action", "accept")
            reviewer = data.get("reviewer", "")
            edited = data.get("edited_value", None)
            rationale = data.get("rationale", "Resolved via GMS Desktop UI")
            self._send_json(self.api.resolve_quarantine(key, agent, action, edited_value=edited, reviewer=reviewer, rationale=rationale))
        elif path == "/api/quarantine/stage":
            key = data.get("fact_key", "") or data.get("key", "")
            val = data.get("value", "")
            agent = data.get("agent_id", "") or data.get("agent", "daily-note")
            branch = data.get("branch", "main")
            self._send_json(self.api.stage_in_quarantine(key, val, agent, branch))
        elif path == "/api/quarantine/review":
            self._send_json(self.api.record_quarantine_review(data))
        elif path == "/api/tasks/create":
            self._send_json(self.api.create_task(data))
        elif path == "/api/tasks/claim":
            self._send_json(self.api.claim_task(data))
        elif path == "/api/tasks/checkpoint":
            self._send_json(self.api.checkpoint_task(data))
        elif path == "/api/tasks/handoff":
            self._send_json(self.api.handoff_task(data))
        elif path == "/api/tasks/complete":
            self._send_json(self.api.complete_task(data))
        elif path == "/api/daily_note":
            dt = data.get("date", datetime.now().strftime("%Y-%m-%d"))
            content = data.get("content", "")
            self._send_json(self.api.save_daily_note(dt, content))
        elif path == "/api/daily_note/harvest":
            dt = data.get("date", datetime.now().strftime("%Y-%m-%d"))
            content = data.get("content", None)
            self._send_json(self.api.harvest_daily_note(dt, content))
        elif path == "/api/concepts/extract":
            text = data.get("text", "")
            self._send_json(self.api.extract_from_text(text))
        elif path == "/api/reminders":
            title = data.get("title", "")
            notes = data.get("notes", "")
            due = data.get("due_date", "")
            self._send_json(self.api.create_reminder(title, notes, due))
        elif path == "/api/context-packets/preview":
            try:
                self._send_json(self.api.preview_context_packet(data))
            except ValueError as e:
                self._send_json({"error": str(e)}, status=400)
        elif path == "/api/context-packets/export":
            try:
                self._send_json(self.api.export_context_packet(data))
            except ValueError as e:
                self._send_json({"error": str(e)}, status=400)
        elif path == "/api/entities/merge":
            src = int(data.get("source_id", 0))
            tgt = int(data.get("target_id", 0))
            reason = data.get("reason", "")
            try:
                self._send_json(self.api.merge_entities(src, tgt, reason=reason))
            except Exception as e:
                self._send_json({"error": str(e)}, status=400)
        elif path in ("/api/dream-cycle/trigger", "/api/dream_cycle/trigger"):
            cmd = [sys.executable, str(Path(__file__).resolve().parent / "dream_cycle.py")]
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._send_json({"status": "started", "message": "Dream cycle consolidation triggered in background."})
        elif path.startswith("/api/harvest/candidates/") and path.endswith("/review"):
            cid = path[len("/api/harvest/candidates/"): -len("/review")].strip("/")
            self._send_json(self.api.review_harvest_candidate(cid, data))
        elif path == "/api/harvest/curate":
            self._send_json(self.api.curate_harvest_candidates(data))
        elif path.startswith("/api/harvest/candidates/") and path.endswith("/contest"):
            cid = path[len("/api/harvest/candidates/"): -len("/contest")].strip("/")
            self._send_json(self.api.contest_harvest_candidate(cid, data))
        elif path == "/api/harvest/migrate-flat/preview":
            self._send_json(self.api.preview_migrate_flat(data))
        elif path == "/api/harvest/pollution/cleanup":
            self._send_json(self.api.run_pollution_cleanup(data))
        elif path == "/api/v1/retrieval/plan":
            self._send_json(self.api.get_retrieval_plan(data))
        elif path == "/api/v1/context-packet":
            self._send_json(self.api.get_context_packet_v1(data))
        elif path == "/api/v1/authority/validate":
            self._send_json(self.api.validate_memory_authority(data))
        elif path == "/api/v1/lifecycle/preview":
            self._send_json(self.api.preview_lifecycle(data, apply=False))
        elif path == "/api/v1/lifecycle/apply":
            self._send_json(self.api.preview_lifecycle(data, apply=True))
        elif path == "/api/v1/convention/cleanup-preview":
            self._send_json(cleanup_preview(self.api.mem_root))
        elif path == "/api/v1/migration/stage":
            self._send_json(self.api.migration_action(data, rollback=False))
        elif path == "/api/v1/migration/rollback":
            self._send_json(self.api.migration_action(data, rollback=True))
        elif path.startswith("/api/projects/") and path.endswith("/resume"):
            parts = path.strip("/").split("/")
            pid = parts[2]
            target_format = data.get("target_format", "antigravity")
            as_of = data.get("as_of", None)
            task_id = data.get("task_id", None)
            self._send_json(self.api.get_resume_bundle(pid, target_format=target_format, as_of=as_of, task_id=task_id))
        elif path == "/api/inbox/preview":
            inbox_id = data.get("inbox_id", "")
            action = data.get("action", "accept")
            proj = data.get("project", "")
            reviewer = data.get("reviewer", "mihir")
            rationale = data.get("rationale", "")
            self._send_json(self.api.preview_inbox_action(inbox_id, action=action, project=proj, reviewer=reviewer, rationale=rationale))
        elif path == "/api/inbox/apply":
            inbox_id = data.get("inbox_id", "")
            proj = data.get("project", "")
            reviewer = data.get("reviewer", "")
            rationale = data.get("rationale", "")
            exp_hash = data.get("expected_hash")
            self._send_json(self.api.apply_inbox_action(inbox_id, project=proj, reviewer=reviewer, rationale=rationale, expected_hash=exp_hash))
        elif path.startswith("/api/repair/") and path.endswith("/stage"):
            parts = path.strip("/").split("/")
            key = parts[2]
            payload = data.get("payload", {})
            apply = bool(data.get("apply", False))
            actor = data.get("actor", "")
            rationale = data.get("rationale", "Repaired from UI")
            self._send_json(self.api.stage_repair_record(key, payload=payload, apply=apply, actor=actor, rationale=rationale))
        else:
            self._send_json({"error": "Endpoint not found"}, status=404)


# =============================================================================
# CLI Dispatcher
# =============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="GMS Desktop Backend Engine")
    parser.add_argument("--root", default=None, help="Custom MEMORY_ROOT directory")
    parser.add_argument("--serve", action="store_true", help="Run HTTP server mode")
    parser.add_argument("--port", type=int, default=28765, help="HTTP server port (default: 28765)")
    parser.add_argument("--action", default=None, help="CLI action to invoke")
    parser.add_argument("--args", default="{}", help="JSON string arguments for action")
    args = parser.parse_args()

    api = GMSDesktopAPI(mem_root=args.root)

    if args.serve:
        GMSHTTPHandler.api = api
        server_address = ("127.0.0.1", args.port)
        httpd = HTTPServer(server_address, GMSHTTPHandler)
        print(f"GMS Desktop API Server running on http://127.0.0.1:{args.port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down GMS Desktop API Server.")
            httpd.server_close()
        return 0

    if args.action:
        payload = json.loads(args.args)
        if args.action == "snapshot":
            res = api.get_snapshot()
        elif args.action == "memories":
            res = api.get_memories(**payload)
        elif args.action == "save_fact":
            res = api.save_fact(**payload)
        elif args.action == "delete_fact":
            res = api.delete_fact(**payload)
        elif args.action == "validate":
            res = api.validate_memory_payload(**payload)
        elif args.action == "quarantine":
            res = api.get_quarantine_items()
        elif args.action in ("triage_history", "quarantine_history"):
            res = api.get_triage_history(**payload)
        elif args.action == "resolve_quarantine":
            res = api.resolve_quarantine(**payload)
        elif args.action == "graph":
            res = api.get_graph_data(**payload)
        elif args.action == "concepts":
            res = api.get_concepts()
        elif args.action == "entity_evidence":
            res = api.get_entity_evidence(**payload)
        elif args.action == "relationship_evidence":
            res = api.get_relationship_evidence(**payload)
        elif args.action == "entity_duplicates":
            res = api.get_entity_duplicates(**payload)
        elif args.action == "extract":
            res = api.extract_from_text(**payload)
        elif args.action == "daily_note":
            res = api.get_daily_note(**payload)
        elif args.action == "save_daily_note":
            res = api.save_daily_note(**payload)
        elif args.action == "harvest_daily_note":
            res = api.harvest_daily_note(**payload)
        elif args.action == "reminders":
            res = api.get_reminders()
        elif args.action == "create_reminder":
            res = api.create_reminder(**payload)
        elif args.action == "projects":
            res = api.get_projects(**payload)
        elif args.action == "project_detail":
            res = api.get_project_detail(**payload)
        elif args.action == "project_activity":
            res = api.get_project_activity(**payload)
        elif args.action == "project_knowledge":
            res = api.get_project_knowledge(**payload)
        elif args.action == "task_resume":
            res = api.get_task_resume(**payload)
        elif args.action == "context_packet_preview":
            res = api.preview_context_packet(payload)
        elif args.action == "context_packet_export":
            res = api.export_context_packet(payload)
        elif args.action == "harvest_reviewers":
            res = api.get_harvest_reviewers()
        elif args.action == "harvest_audit":
            res = api.get_harvest_audit_history(**payload)
        elif args.action == "pollution_audit":
            res = api.get_pollution_audit()
        elif args.action == "pollution_cleanup":
            res = api.run_pollution_cleanup(payload)
        elif args.action == "eval_model_harvesting":
            res = api.get_model_harvest_eval(**payload)
        else:
            print(json.dumps({"error": f"Unknown action: {args.action}"}))
            return 1

        print(json.dumps(res, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
