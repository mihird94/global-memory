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
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
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
from schemas import validate_fact, parse_payload, list_contracts

DEFAULT_MEM_ROOT = Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories")).expanduser()
DB_PATH = DEFAULT_MEM_ROOT / "gms_trust.sqlite"


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

        # Agent reputation count
        reputations = []
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                c = conn.cursor()
                c.execute("SELECT agent_id, alpha, beta, last_updated FROM gms_agent_reputation")
                for agent_id, alpha, beta, updated in c.fetchall():
                    total = alpha + beta
                    trust = alpha / total if total > 0 else 0.5
                    reputations.append({
                        "agent_id": agent_id,
                        "alpha": round(alpha, 2),
                        "beta": round(beta, 2),
                        "trust": round(trust, 3),
                        "last_updated": updated,
                    })
                conn.close()
            except Exception:
                pass

        snapshot["db_size_bytes"] = db_size
        snapshot["backup_size_bytes"] = bak_size
        snapshot["agent_reputations"] = reputations
        snapshot["platform"] = sys.platform
        snapshot["apple_automation_supported"] = (sys.platform == "darwin")
        return snapshot

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
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        # 1. Semantic Facts
        if tier in ("all", "semantic"):
            facts_file = self.mem_root / "semantic" / "facts.json"
            if facts_file.exists():
                try:
                    facts = json.loads(facts_file.read_text(errors="replace"))
                    for k, v in facts.items():
                        ns = k.split(".")[0] if "." in k else "general"
                        if namespace and not k.startswith(namespace):
                            continue
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        if query and query.lower() not in k.lower() and query.lower() not in val_str.lower():
                            continue
                        results.append({
                            "key": k,
                            "value": v,
                            "tier": "semantic",
                            "namespace": ns,
                            "source": "facts.json",
                        })
                except Exception:
                    pass

        # 2. Operational Facts
        if tier in ("all", "operational") and (not namespace or namespace.startswith("operational")):
            ops_file = self.mem_root / "operational" / "facts.json"
            if ops_file.exists():
                try:
                    facts = json.loads(ops_file.read_text(errors="replace"))
                    for k, v in facts.items():
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        if query and query.lower() not in k.lower() and query.lower() not in val_str.lower():
                            continue
                        results.append({
                            "key": k,
                            "value": v,
                            "tier": "operational",
                            "namespace": "operational",
                            "source": "operational/facts.json",
                        })
                except Exception:
                    pass

        # 3. Procedural Facts & Runbooks
        if tier in ("all", "procedural") and (not namespace or namespace.startswith("procedural")):
            proc_file = self.mem_root / "procedural" / "facts.json"
            if proc_file.exists():
                try:
                    facts = json.loads(proc_file.read_text(errors="replace"))
                    for k, v in facts.items():
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        if query and query.lower() not in k.lower() and query.lower() not in val_str.lower():
                            continue
                        results.append({
                            "key": k,
                            "value": v,
                            "tier": "procedural",
                            "namespace": "procedural",
                            "source": "procedural/facts.json",
                        })
                except Exception:
                    pass

            # DB procedures
            if self.db_path.exists():
                try:
                    conn = sqlite3.connect(str(self.db_path))
                    c = conn.cursor()
                    c.execute("SELECT name, \"trigger\", action, context, status FROM gms_procedures")
                    for name, trigger, action, context, status in c.fetchall():
                        text_blob = f"{name} {trigger} {action} {context}"
                        if query and query.lower() not in text_blob.lower():
                            continue
                        results.append({
                            "key": f"proc.{name}",
                            "value": {"trigger": trigger, "action": action, "context": context, "status": status},
                            "tier": "procedural",
                            "namespace": "procedures",
                            "source": "gms_procedures",
                        })
                    conn.close()
                except Exception:
                    pass

        # 4. Episodic Memories (Journal & History files)
        if tier in ("all", "episodic") and (not namespace or namespace.startswith("episodic") or namespace.startswith("journal")):
            journal = self.mem_root / "episodic" / "journal.md"
            if journal.exists():
                try:
                    lines = journal.read_text(errors="replace").splitlines()
                    current_entry: list[str] = []
                    current_title = "Journal Entry"
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
                                    })
                            current_title = line.lstrip("#").strip()
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
                            })
                except Exception:
                    pass

            history_dir = self.mem_root / "episodic" / "history"
            if history_dir.exists():
                for f in sorted(history_dir.glob("*.md"), reverse=True)[:15]:
                    try:
                        content = f.read_text(errors="replace")
                        if not query or query.lower() in f.stem.lower() or query.lower() in content.lower():
                            results.append({
                                "key": f"history/{f.name}",
                                "value": content[:500] + ("..." if len(content) > 500 else ""),
                                "tier": "episodic",
                                "namespace": "history",
                                "source": f.name,
                            })
                    except Exception:
                        pass

        total_count = len(results)
        paged = results[offset : offset + limit]
        return {
            "total": total_count,
            "count": len(paged),
            "offset": offset,
            "limit": limit,
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
        agent: str = "human-ui",
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

        # Store via MCP server logic
        val_str = json.dumps(norm_val) if isinstance(norm_val, (dict, list)) else str(norm_val)
        res_str = memory_mcp_server.tool_mem_save_typed({
            "key": key,
            "value": val_str,
            "kind": kind,
            "agent": agent,
        })
        return {
            "status": "success" if "error" not in res_str.lower() else "warning",
            "message": res_str,
            "key": key,
            "value": norm_val,
        }

    def delete_fact(self, key: str, agent: str = "human-ui") -> dict[str, Any]:
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
    def get_quarantine_items(self) -> list[dict[str, Any]]:
        items = []
        if not self.db_path.exists():
            return items

        try:
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute(
                """
                SELECT q.fact_key, q.value, q.agent_id, q.branch, q.timestamp
                FROM gms_quarantined_facts q
                ORDER BY q.timestamp DESC
                """
            )
            for row in c.fetchall():
                items.append({
                    "fact_key": row[0],
                    "value": parse_payload(row[1]),
                    "agent_id": row[2],
                    "branch": row[3],
                    "timestamp": row[4],
                })
            conn.close()
        except Exception:
            pass
        return items

    def resolve_quarantine(
        self,
        fact_key: str,
        agent_id: str,
        action: str,  # "accept" or "reject"
        reviewer: str = "human",
        rationale: str = "Resolved via GMS Desktop UI",
    ) -> dict[str, Any]:
        res = memory_mcp_server.tool_mem_resolve_quarantine({
            "fact_key": fact_key,
            "agent_id": agent_id,
            "action": action,
            "reviewer": reviewer,
            "rationale": rationale,
        })
        return {
            "status": "success",
            "message": res,
            "action": action,
            "fact_key": fact_key,
        }

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
            return {"nodes": [], "edges": []}

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
            c.execute("SELECT entity_id, name, entity_type, summary FROM gms_entities")
            for eid, name, etype, summary in c.fetchall():
                nodes.append({
                    "id": eid,
                    "label": name,
                    "type": etype or "CONCEPT",
                    "summary": summary or "",
                })

            # Load relationships
            c.execute(
                """
                SELECT relationship_id, subject_entity_id, predicate, object_entity_id,
                       object_literal, valid_from, valid_to
                FROM gms_relationships
                """
            )
            for rid, subj_id, pred, obj_id, obj_lit, v_from, v_to in c.fetchall():
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
                    edges.append({
                        "id": rid,
                        "from": subj_id,
                        "to": obj_id,
                        "label": pred,
                        "valid_from": v_from,
                        "valid_to": v_to,
                        "active": is_active,
                    })

            conn.close()
        except Exception:
            pass

        return {"nodes": nodes, "edges": edges}

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
        return {
            "candidate_facts": validated_candidates,
            "extracted_triples": [{"subject": s, "predicate": p, "object": o} for s, p, o in triples],
        }

    # =========================================================================
    # 7. Daily Notes & Memory Sucking / Harvesting ("Agentic Sleep")
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
            content = f"# Daily Note — {dt}\n\n- Quick notes, observations, or facts here...\n"

        return {
            "date": dt,
            "path": str(daily_file),
            "exists": exists,
            "content": content,
        }

    def save_daily_note(self, date_str: str, content: str) -> dict[str, Any]:
        daily_dir = self.mem_root / "episodic" / "history"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_file = daily_dir / f"{date_str}.md"
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
        """Sucks the daily note into GMS (fact extraction, schema validation, graph triples, SQLite vectors)."""
        if content is not None:
            self.save_daily_note(date_str, content)

        daily_file = self.mem_root / "episodic" / "history" / f"{date_str}.md"
        text = ""
        if daily_file.exists():
            text = daily_file.read_text(errors="replace")

        report = harvest.harvest_session(
            agent="human-ui",
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

        # Fast, targeted one-liner fetching incomplete reminder names of default list
        script = 'tell application "Reminders" to get name of every reminder of default list whose completed is false'
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=6,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return {"supported": True, "reminders": []}

            raw_names = [n.strip() for n in res.stdout.strip().split(",") if n.strip()]
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


# =============================================================================
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
            limit = int(qs.get("limit", [100])[0])
            offset = int(qs.get("offset", [0])[0])
            self._send_json(self.api.get_memories(tier, ns, query, limit, offset))
        elif path == "/api/quarantine":
            self._send_json(self.api.get_quarantine_items())
        elif path == "/api/graph":
            as_of = qs.get("as_of", [None])[0]
            inc_exp = qs.get("include_expired", ["false"])[0].lower() == "true"
            self._send_json(self.api.get_graph_data(as_of, inc_exp))
        elif path == "/api/concepts":
            self._send_json(self.api.get_concepts())
        elif path == "/api/daily_note":
            date_str = qs.get("date", [None])[0]
            self._send_json(self.api.get_daily_note(date_str))
        elif path == "/api/reminders":
            self._send_json(self.api.get_reminders())
        elif path == "/api/contracts":
            self._send_json(list_contracts())
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
            agent = data.get("agent", "human-ui")
            kind = data.get("kind", "semantic")
            self._send_json(self.api.save_fact(key, val, agent, kind))
        elif path == "/api/memories/delete":
            key = data.get("key", "")
            agent = data.get("agent", "human-ui")
            self._send_json(self.api.delete_fact(key, agent))
        elif path == "/api/quarantine/resolve":
            key = data.get("fact_key", "")
            agent = data.get("agent_id", "")
            action = data.get("action", "accept")
            reviewer = data.get("reviewer", "human")
            self._send_json(self.api.resolve_quarantine(key, agent, action, reviewer))
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
        elif args.action == "resolve_quarantine":
            res = api.resolve_quarantine(**payload)
        elif args.action == "graph":
            res = api.get_graph_data(**payload)
        elif args.action == "concepts":
            res = api.get_concepts()
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
        else:
            print(json.dumps({"error": f"Unknown action: {args.action}"}))
            return 1

        print(json.dumps(res, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
