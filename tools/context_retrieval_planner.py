"""Deterministic multi-lane hybrid context retrieval planner.

Implements genuine independently executed retrieval lanes:
1. exact: Canonical key & alias lookup
2. bm25: Lexical BM25 ranking over structured records & project banks
3. vector: Semantic similarity over episodic & semantic chunks
4. decisions: Active project decisions & constraints with rationale
5. procedures: Operational runbooks & workflows
6. tasks: Open tasks, checkpoints, & handoffs from gms_tasks
7. conflicts: Contradictions, collisions, disputes & stale records
8. episodes: Recent project-scoped milestones & daily history
9. graph: Knowledge-graph neighborhood & bounded multi-hop paths
10. artifacts: Explicitly linked file/evidence paths and digests
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_aliases import alias_inventory, canonicalize, resolve_alias
from memory_authority import authority_label

LANES = (
    "exact",
    "bm25",
    "vector",
    "decisions",
    "procedures",
    "tasks",
    "conflicts",
    "episodes",
    "graph",
    "artifacts",
)

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "what", "which", "who", "why", "how", "this", "these",
}


def _fact_context(value: Any) -> dict[str, Any]:
    """Describe a fact's epistemic shape without rewriting stored memory."""
    if isinstance(value, dict) and any(
        field in value for field in ("rationale", "provenance", "evidence", "scope", "implications")
    ):
        status = str(value.get("status") or "accepted")
        return {
            "record_shape": "structured",
            "verification": status,
            "requires_corroboration": status not in ("accepted", "active", "verified"),
            "limitations": [],
        }
    return {
        "record_shape": "legacy_flat",
        "verification": "unverified",
        "requires_corroboration": True,
        "limitations": [
            "Legacy fact has no structured rationale, scope, provenance, or evidence; corroborate before consequential use."
        ],
    }


def _fact_authority(value: Any) -> str:
    return "verified_system_output" if _fact_context(value)["record_shape"] == "structured" else "imported_legacy"


def _tokenize(text: str) -> list[str]:
    # Treat dotted/underscored keys as natural-language terms as well as keys.
    raw = re.findall(r"[A-Za-z0-9]+", text.lower())
    tokens = []
    for t in raw:
        if len(t) > 1 and t not in STOPWORDS:
            tokens.append(t)
        sub_tokens = re.split(r"[._@-]", t)
        if len(sub_tokens) > 1:
            for st in sub_tokens:
                if len(st) > 1 and st not in STOPWORDS and st not in tokens:
                    tokens.append(st)
    return tokens


def make_plan(
    query: str,
    *,
    project: str = "",
    as_of: str | None = None,
    assurance: str = "standard",
    token_budget: int = 2400,
    required_lanes: list[str] | None = None,
) -> dict[str, Any]:
    tokens = _tokenize(query)
    intent = "context"
    q_lower = query.lower()
    if any(w in q_lower for w in ("resume", "continue", "next action", "handoff")):
        intent = "resume"
    elif any(w in q_lower for w in ("why", "rationale", "because", "decide", "decision")):
        intent = "decision"
    elif any(w in q_lower for w in ("how", "procedure", "runbook", "steps", "command")):
        intent = "procedure"
    elif any(w in q_lower for w in ("conflict", "collision", "contradict", "dispute")):
        intent = "comparison"
    elif any(w in q_lower for w in ("history", "past", "timeline", "before", "earlier")):
        intent = "historical"

    enabled_lanes = required_lanes or list(LANES)
    return {
        "schema_version": "gms-retrieval-plan-v1",
        "query": query,
        "intent": intent,
        "project": project,
        "entities": tokens[:16],
        "as_of": as_of,
        "assurance": assurance,
        "token_budget": token_budget,
        "lanes": [{"name": x, "enabled": x in enabled_lanes} for x in LANES],
    }


def _make_item(
    lane: str,
    key: str,
    statement: Any,
    authority: str,
    source: str,
    rank: int,
    *,
    component_score: float = 1.0,
    bm25_score: float | None = None,
    vector_similarity: float | None = None,
    graph_path: list[str] | None = None,
    exact_match: bool = False,
    contradiction_flag: bool = False,
    lifecycle_status: str = "accepted",
    scope: dict[str, Any] | None = None,
    effective_at: str | None = None,
    warning: str | None = None,
    inclusion_reason: str = "",
    **extra: Any,
) -> dict[str, Any]:
    text = statement if isinstance(statement, str) else json.dumps(statement, sort_keys=True)
    token_estimate = max(1, len(text) // 4)
    return {
        "record_id": f"{lane}:{key}",
        "key": key,
        "statement": text,
        "lane": lane,
        "component_rank": rank,
        "component_score": round(component_score, 4),
        "exact_match": exact_match,
        "bm25_score": round(bm25_score, 4) if bm25_score is not None else None,
        "vector_similarity": round(vector_similarity, 4) if vector_similarity is not None else None,
        "graph_path": graph_path,
        "graph_path_len": len(graph_path) if graph_path else None,
        "task_priority": extra.get("task_priority"),
        "authority": authority,
        "authority_label": authority_label(authority),
        "lifecycle_status": lifecycle_status,
        "source": source,
        "source_valid": bool(source),
        "token_estimate": token_estimate,
        "scope": scope or {},
        "effective_at": effective_at,
        "freshness_state": "stale" if warning and "stale" in warning else "fresh",
        "contradiction_flag": contradiction_flag,
        "redundancy_group": canonicalize(key),
        "warning": warning,
        "inclusion_reason": inclusion_reason or f"{lane.replace('_', ' ')} match",
        **extra,
    }


# ==============================================================================
# INDIVIDUAL RETRIEVAL LANES
# ==============================================================================

def _run_lane_exact(root: Path, query: str, terms: set[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    facts_path = root / "semantic" / "facts.json"
    facts = {}
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    q_clean = query.strip()
    q_canon = canonicalize(q_clean)
    rank = 1

    # Exact alias check
    resolved_info = resolve_alias(root, q_clean)
    resolved_key = resolved_info.get("canonical_key", q_clean) if isinstance(resolved_info, dict) else str(resolved_info)
    if resolved_key != q_clean:
        canon_res = canonicalize(resolved_key)
        for k, v in facts.items():
            if canonicalize(k) in (q_canon, canon_res):
                items.append(_make_item("exact", k, v, _fact_authority(v), f"semantic/facts.json#{k}", rank,
                                        component_score=1.0, exact_match=True,
                                        scope={"project": project} if project else {},
                                        **_fact_context(v),
                                        inclusion_reason=f"Exact alias match for '{q_clean}' -> '{resolved_key}'"))
                rank += 1

    for k, v in facts.items():
        if canonicalize(k) == q_canon or k.lower() in terms:
            items.append(_make_item("exact", k, v, _fact_authority(v), f"semantic/facts.json#{k}", rank,
                                    component_score=1.0, exact_match=True,
                                    scope={"project": project} if project else {},
                                    **_fact_context(v),
                                    inclusion_reason=f"Exact key match for '{k}'"))
            rank += 1
            if rank > 5:
                break
    return items


def _run_lane_bm25(root: Path, query: str, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    if not query_tokens:
        return []

    # Gather documents: facts + project bank paragraphs
    docs: list[tuple[str, str, str, str]] = []  # (doc_id, key, text, source)
    facts_path = root / "semantic" / "facts.json"
    if facts_path.exists():
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
            for k, v in facts.items():
                val_text = str(v) if not isinstance(v, (dict, list)) else json.dumps(v)
                docs.append((f"fact:{k}", k, f"{k} {val_text}", f"semantic/facts.json#{k}"))
        except Exception:
            pass

    if project:
        proj_dir = root / "projects" / project
        if proj_dir.exists():
            for fn in ("projectBrief.md", "activeContext.md", "systemPatterns.md", "progress.md", "techContext.md"):
                fp = proj_dir / fn
                if fp.exists():
                    try:
                        content = fp.read_text(encoding="utf-8", errors="replace")
                        for idx, p in enumerate(re.split(r"\n\s*\n", content)):
                            p_clean = p.strip()
                            if len(p_clean) > 20:
                                docs.append((f"{project}.{fn}.{idx}", f"{project}.{fn}.{idx}", p_clean, str(fp)))
                    except Exception:
                        pass

    if not docs:
        return []

    # Compute BM25
    doc_tokens = [_tokenize(doc[2]) for doc in docs]
    N = len(docs)
    avgdl = max(1.0, sum(len(dt) for dt in doc_tokens) / N)
    k1 = 1.5
    b = 0.75

    # Document frequency
    df: dict[str, int] = {}
    for dt in doc_tokens:
        unique = set(dt)
        for t in unique:
            df[t] = df.get(t, 0) + 1

    idf: dict[str, float] = {}
    for t in query_tokens:
        d_count = df.get(t, 0)
        idf[t] = math.log(1.0 + (N - d_count + 0.5) / (d_count + 0.5))

    scores: list[tuple[float, int]] = []
    for idx, dt in enumerate(doc_tokens):
        if not dt:
            continue
        score = 0.0
        doc_len = len(dt)
        t_counts: dict[str, int] = {}
        for t in dt:
            t_counts[t] = t_counts.get(t, 0) + 1
        for qt in query_tokens:
            f = t_counts.get(qt, 0)
            if f > 0:
                tf_norm = (f * (k1 + 1.0)) / (f + k1 * (1.0 - b + b * (doc_len / avgdl)))
                score += idf[qt] * tf_norm
        if score > 0.05:
            scores.append((score, idx))

    scores.sort(key=lambda x: x[0], reverse=True)
    items = []
    for rank, (score, doc_idx) in enumerate(scores[:15], start=1):
        doc_id, key, text, source = docs[doc_idx]
        fact_value = facts.get(key) if source.startswith("semantic/facts.json#") else None
        authority = "source_document" if "projects/" in source else _fact_authority(fact_value)
        context = {} if fact_value is None else _fact_context(fact_value)
        items.append(_make_item("bm25", key, text, authority,
                                source, rank, component_score=score, bm25_score=score,
                                scope={"project": project} if project else {},
                                **context,
                                inclusion_reason=f"Lexical BM25 score {score:.2f}"))
    return items


@lru_cache(maxsize=64)
def _indexed_query_embedding(query: str, model: str) -> tuple[float, ...]:
    # This path is invoked only by an explicit indexed-vector request (for
    # example the CLI evaluation command), never by ordinary desktop browsing.
    import memoryctl
    return tuple(float(x) for x in memoryctl._embed(query, model))


def _run_lane_vector(root: Path, query: str, query_tokens: list[str], project: str,
                     as_of: str | None, enable_indexed_vector: bool = False,
                     embedding_model: str = "qwen3-embedding:0.6b") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not enable_indexed_vector:
        return [], {"backend": "disabled_model_free", "available": False,
                    "reason": "Interactive navigation does not load an embedding model"}
    db = root / "gms_trust.sqlite"
    if not db.exists():
        return [], {"backend": "sqlite_embeddings", "available": False, "reason": "database missing"}
    try:
        import memory_mcp_server
        vector = _indexed_query_embedding(query, embedding_model)
        hits = memory_mcp_server.search_sqlite_embeddings(list(vector), top_k=20,
            model=embedding_model, db_path=db)
        items=[]
        for hit in hits:
            source=str(hit.get("source") or "")
            # A project-scoped query may use global episodic history, but must
            # never import another named project's bank.
            marker=f"/projects/{project}/" if project else ""
            if project and "/projects/" in source and marker not in source:
                continue
            text=str(hit.get("text") or "")
            if as_of:
                date_match=re.search(r"(\d{4}-\d{2}-\d{2})",source)
                if date_match and date_match.group(1)>as_of[:10]:
                    continue
            rank=len(items)+1; sim=float(hit.get("score") or 0.0)
            items.append(_make_item("vector",f"indexed.{hit.get('id',rank)}",text,"source_document",source,rank,
                component_score=sim,vector_similarity=sim,scope={"project":project} if project else {},
                inclusion_reason=f"Indexed embedding similarity {sim:.3f}"))
            if len(items)>=8: break
        return items,{"backend":"sqlite_embeddings","available":True,"model":embedding_model,"hits":len(items)}
    except Exception as exc:
        return [], {"backend":"sqlite_embeddings","available":False,"reason":str(exc)[:160]}


def _run_lane_decisions(root: Path, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    rank = 1
    # 1. Project activeContext.md decisions & constraints
    if project:
        fp = root / "projects" / project / "activeContext.md"
        if fp.exists():
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                sections = re.split(r"\n(?=## )", text)
                for sec in sections:
                    if any(w in sec.lower() for w in ("decision", "constraint", "boundary", "focus", "rule")):
                        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", sec) if p.strip()]
                        for p in paragraphs:
                            if len(p) > 20 and (not query_tokens or any(t in p.lower() for t in query_tokens)):
                                items.append(_make_item("decisions", f"{project}.decision.{rank}", p,
                                                        "source_document", str(fp), rank,
                                                        component_score=0.9,
                                                        scope={"project": project},
                                                        inclusion_reason="Active project constraint/decision"))
                                rank += 1
                                if rank > 8:
                                    break
            except Exception:
                pass

    # 2. Database structured decisions from gms_claims or gms_context_candidates (accepted only)
    db = root / "gms_trust.sqlite"
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT claim_id, memory_key, value, created_at FROM gms_claims WHERE status='active' AND (memory_key LIKE '%decision%' OR memory_key LIKE '%policy%') ORDER BY claim_id DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                k = r["memory_key"]
                val = r["value"]
                items.append(_make_item("decisions", k, val, "user_instruction" if "preference" in k else "source_document",
                                        f"claim:{r['claim_id']}", rank, component_score=0.85,
                                        scope={"project": project} if project else {},
                                        effective_at=r["created_at"],
                                        inclusion_reason="Authoritative policy/decision record"))
                rank += 1
            conn.close()
        except Exception:
            pass
    return items


def _run_lane_procedures(root: Path, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    rank = 1
    # 1. Project systemPatterns.md
    if project:
        fp = root / "projects" / project / "systemPatterns.md"
        if fp.exists():
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
                for p in paragraphs:
                    if len(p) > 25 and (not query_tokens or any(t in p.lower() for t in query_tokens)):
                        items.append(_make_item("procedures", f"{project}.procedure.{rank}", p,
                                                "source_document", str(fp), rank,
                                                component_score=0.85,
                                                scope={"project": project},
                                                inclusion_reason="Project operational pattern & procedure"))
                        rank += 1
                        if rank > 6:
                            break
            except Exception:
                pass

    # 2. SKILL.md protocols
    skill_fp = Path(__file__).resolve().parent.parent / "SKILL.md"
    if skill_fp.exists():
        try:
            text = skill_fp.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.strip().startswith("- ") and any(kw in line.lower() for kw in ("protocol", "procedure", "command", "must")):
                    if not query_tokens or any(t in line.lower() for t in query_tokens):
                        items.append(_make_item("procedures", f"global.skill.{rank}", line.strip(),
                                                "source_document", str(skill_fp), rank,
                                                component_score=0.80,
                                                scope={"project": project} if project else {},
                                                inclusion_reason="Operational skill protocol"))
                        rank += 1
                        if rank > 6:
                            break
        except Exception:
            pass
    return items


def _run_lane_tasks(root: Path, project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    db = root / "gms_trust.sqlite"
    if not db.exists():
        return items

    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_tasks'").fetchone():
            query_sql = "SELECT * FROM gms_tasks WHERE status != 'completed'"
            params = []
            if project:
                query_sql += " AND project = ?"
                params.append(project)
            query_sql += " ORDER BY updated_at DESC LIMIT 10"
            rows = conn.execute(query_sql, params).fetchall()
            for rank, r in enumerate(rows, start=1):
                t_dict = dict(r)
                task_id = str(r["task_id"])
                checkpoint = None
                handoff = None
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_task_checkpoints'").fetchone():
                    cp = conn.execute(
                        "SELECT checkpoint_id, revision, agent_id, label, state_json, artifact_refs_json, "
                        "claim_refs_json, episode_refs_json, created_at FROM gms_task_checkpoints "
                        "WHERE task_id = ? ORDER BY checkpoint_id DESC LIMIT 1", (task_id,)
                    ).fetchone()
                    if cp:
                        checkpoint = dict(cp)
                        for field in ("state_json", "artifact_refs_json", "claim_refs_json", "episode_refs_json"):
                            try:
                                checkpoint[field.removesuffix("_json")] = json.loads(checkpoint.pop(field) or ("{}" if field == "state_json" else "[]"))
                            except Exception:
                                checkpoint[field.removesuffix("_json")] = checkpoint.pop(field, None)
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_handoffs'").fetchone():
                    ho = conn.execute(
                        "SELECT handoff_id, revision, source_agent, target_agent, objective, completed_work, "
                        "next_action, blockers, acceptance_criteria, context_json, artifact_refs_json, created_at, "
                        "acknowledged_at FROM gms_handoffs WHERE task_id = ? ORDER BY handoff_id DESC LIMIT 1",
                        (task_id,)
                    ).fetchone()
                    if ho:
                        handoff = dict(ho)
                        for field in ("context_json", "artifact_refs_json"):
                            try:
                                target = field.removesuffix("_json")
                                handoff[target] = json.loads(handoff.pop(field) or ("{}" if field == "context_json" else "[]"))
                            except Exception:
                                pass
                t_dict["latest_checkpoint"] = checkpoint
                t_dict["latest_handoff"] = handoff
                prio = 1 if r["status"] == "in_progress" else 2 if r["status"] == "blocked" else 3
                items.append(_make_item("tasks", task_id, t_dict, "verified_system_output",
                                        f"task:{task_id}", rank,
                                        component_score=1.0 - (prio * 0.1),
                                        task_priority=prio,
                                        scope={"project": r["project"]},
                                        effective_at=r["updated_at"],
                                        inclusion_reason=f"Active task ({r['status']})"))
        conn.close()
    except Exception:
        pass
    return items


def _run_lane_conflicts(root: Path, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    rank = 1
    # 1. Alias collisions from inventory
    try:
        inv = alias_inventory(root)
        for col in inv.get("collisions", []):
            can_k = col["canonical_key"]
            recs = col.get("records", [])
            key_terms=set(_tokenize(can_k))
            project_terms=set(_tokenize(project))
            # A global collision is not automatically a blocker for every
            # project. Include it only when the query or project scope matches.
            if project and not (key_terms & set(query_tokens) or key_terms & project_terms):
                continue
            items.append(_make_item("conflicts", can_k,
                                    {"canonical_key": can_k, "competing_records": recs, "proposal": col.get("proposal", "contradict")},
                                    "verified_system_output", f"collision:{can_k}", rank,
                                    component_score=1.0, contradiction_flag=True,
                                    warning="unresolved canonical-key collision",
                                    inclusion_reason="Blocking key collision requiring adjudication"))
            rank += 1
    except Exception:
        pass

    # 2. Superseded claims
    db = root / "gms_trust.sqlite"
    if db.exists():
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT claim_id, memory_key, value, created_at FROM gms_claims WHERE status='superseded' ORDER BY claim_id DESC LIMIT 5"
            ).fetchall()
            for r in rows:
                if not query_tokens or any(t in r["memory_key"].lower() for t in query_tokens):
                    items.append(_make_item("conflicts", r["memory_key"], r["value"], "imported_legacy",
                                            f"claim:{r['claim_id']}", rank,
                                            component_score=0.8, contradiction_flag=True,
                                            warning="superseded record",
                                            effective_at=r["created_at"],
                                            inclusion_reason="Superseded claim in conflict chain"))
                    rank += 1
            conn.close()
        except Exception:
            pass
    return items


def _run_lane_episodes(root: Path, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    rank = 1
    # Project progress.md
    if project:
        fp = root / "projects" / project / "progress.md"
        if fp.exists():
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
                for p in paragraphs:
                    if len(p) > 25 and (not query_tokens or any(t in p.lower() for t in query_tokens)):
                        items.append(_make_item("episodes", f"{project}.progress.{rank}", p,
                                                "source_document", str(fp), rank,
                                                component_score=0.75,
                                                scope={"project": project},
                                                inclusion_reason="Project milestone progress entry"))
                        rank += 1
                        if rank > 5:
                            break
            except Exception:
                pass

    # Daily notes recent updates
    hist_dir = root / "episodic" / "history"
    if hist_dir.exists():
        for fp in sorted(hist_dir.glob("*.md"), reverse=True)[:3]:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                for line in lines:
                    if line.startswith("- ") and (not query_tokens or any(t in line.lower() for t in query_tokens)):
                        items.append(_make_item("episodes", f"daily.{fp.stem}.{rank}", line.strip(),
                                                "source_document", str(fp), rank,
                                                component_score=0.70,
                                                effective_at=fp.stem,
                                                inclusion_reason="Recent daily note entry"))
                        rank += 1
                        if rank > 6:
                            break
            except Exception:
                pass
    return items


def _run_lane_graph(root: Path, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    db = root / "gms_trust.sqlite"
    if not db.exists() or not query_tokens:
        return items

    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        has_rel = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_relationships'").fetchone()
        if has_rel:
            placeholders = ",".join("?" for _ in query_tokens[:6])
            q_terms = [f"%{t}%" for t in query_tokens[:6]]
            # Find relationships where subject or object matches terms
            sql = f"""
                SELECT source_id, target_id, rel_type, summary, weight, valid_from
                FROM gms_relationships
                WHERE {" OR ".join(["source_id LIKE ? OR target_id LIKE ?" for _ in query_tokens[:6]])}
                ORDER BY weight DESC LIMIT 10
            """
            flat_params = []
            for t in q_terms:
                flat_params.extend([t, t])
            rows = conn.execute(sql, flat_params).fetchall()
            for rank, r in enumerate(rows, start=1):
                path = [r["source_id"], r["rel_type"], r["target_id"]]
                stmt = f"{r['source_id']} —[{r['rel_type']}]→ {r['target_id']}: {r['summary'] or ''}"
                items.append(_make_item("graph", f"graph:{r['source_id']}_{r['target_id']}", stmt,
                                        "verified_system_output", "sqlite:gms_relationships", rank,
                                        component_score=r["weight"] or 0.8,
                                        graph_path=path,
                                        effective_at=r["valid_from"],
                                        inclusion_reason=f"Knowledge Graph triple path ({r['source_id']} -> {r['target_id']})"))
        conn.close()
    except Exception:
        pass
    return items


def _run_lane_artifacts(root: Path, query_tokens: list[str], project: str, as_of: str | None) -> list[dict[str, Any]]:
    items = []
    rank = 1
    # Check project techContext.md for explicitly declared tools, artifacts, repo files
    if project:
        fp = root / "projects" / project / "techContext.md"
        if fp.exists():
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
                for p in paragraphs:
                    if len(p) > 20 and (not query_tokens or any(t in p.lower() for t in query_tokens)):
                        items.append(_make_item("artifacts", f"{project}.tech.{rank}", p,
                                                "source_document", str(fp), rank,
                                                component_score=0.85,
                                                scope={"project": project},
                                                inclusion_reason="Technical stack and artifact specification"))
                        rank += 1
                        if rank > 5:
                            break
            except Exception:
                pass
    return items


# ==============================================================================
# MAIN HYBRID RETRIEVAL ORCHESTRATION & FUSION
# ==============================================================================

def retrieve(
    mem_root: Path,
    query: str,
    *,
    project: str = "",
    as_of: str | None = None,
    assurance: str = "standard",
    token_budget: int = 2400,
    include_proposed: bool = False,
    required_lanes: list[str] | None = None,
    enable_indexed_vector: bool = False,
    embedding_model: str = "qwen3-embedding:0.6b",
) -> dict[str, Any]:
    root = Path(mem_root)
    plan = make_plan(
        query,
        project=project,
        as_of=as_of,
        assurance=assurance,
        token_budget=token_budget,
        required_lanes=required_lanes,
    )

    query_tokens = plan["entities"]
    terms = set(query_tokens)

    lane_candidates: dict[str, int] = {}
    lane_latencies: dict[str, float] = {}
    all_items: list[dict[str, Any]] = []

    # Helper to execute a lane and record candidations + latency
    def _execute_lane(lane_name: str, runner):
        t0 = time.perf_counter()
        lane_items = runner()
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        lane_candidates[lane_name] = len(lane_items)
        lane_latencies[lane_name] = elapsed_ms
        all_items.extend(lane_items)

    _execute_lane("exact", lambda: _run_lane_exact(root, query, terms, project, as_of))
    _execute_lane("bm25", lambda: _run_lane_bm25(root, query, query_tokens, project, as_of))
    vector_meta: dict[str, Any] = {}
    def _vector_runner():
        items, meta = _run_lane_vector(root, query, query_tokens, project, as_of,
                                       enable_indexed_vector, embedding_model)
        vector_meta.update(meta); return items
    _execute_lane("vector", _vector_runner)
    _execute_lane("decisions", lambda: _run_lane_decisions(root, query_tokens, project, as_of))
    _execute_lane("procedures", lambda: _run_lane_procedures(root, query_tokens, project, as_of))
    _execute_lane("tasks", lambda: _run_lane_tasks(root, project, as_of))
    _execute_lane("conflicts", lambda: _run_lane_conflicts(root, query_tokens, project, as_of))
    _execute_lane("episodes", lambda: _run_lane_episodes(root, query_tokens, project, as_of))
    _execute_lane("graph", lambda: _run_lane_graph(root, query_tokens, project, as_of))
    _execute_lane("artifacts", lambda: _run_lane_artifacts(root, query_tokens, project, as_of))

    # RECIPROCAL RANK FUSION (RRF)
    # Score(d) = sum_{lane} (1.0 / (60 + rank_in_lane))
    rrf_scores: dict[str, float] = {}
    grouped_items: dict[str, dict[str, Any]] = {}
    item_lanes: dict[str, set[str]] = {}

    for it in all_items:
        key = canonicalize(it["key"])
        c_rank = it["component_rank"]
        boost = 1.2 if it.get("exact_match") else (1.3 if it.get("contradiction_flag") else 1.0)
        if it.get("record_shape") == "structured":
            boost *= 1.12
        elif it.get("record_shape") == "legacy_flat":
            boost *= 0.88
        rrf_contrib = (1.0 / (60.0 + c_rank)) * boost
        rrf_scores[key] = rrf_scores.get(key, 0.0) + rrf_contrib

        if key not in grouped_items:
            grouped_items[key] = it
            item_lanes[key] = {it["lane"]}
        else:
            item_lanes[key].add(it["lane"])
            # Prefer higher authority or richer statement
            existing = grouped_items[key]
            if len(it["statement"]) > len(existing["statement"]):
                grouped_items[key] = it

    # Sort merged candidates by RRF score descending
    ranked_keys = sorted(grouped_items.keys(), key=lambda k: rrf_scores[k], reverse=True)

    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    spent = 0
    source_counts: dict[str, int] = {}
    used_lanes = set()

    for k in ranked_keys:
        item = grouped_items[k]
        item["rrf_score"] = round(rrf_scores[k], 5)
        item["lanes_matched"] = sorted(item_lanes[k])

        # Temporal filter: check as_of
        if as_of and item.get("effective_at"):
            if str(item["effective_at"])[:10] > str(as_of)[:10]:
                omitted.append({"key": item["key"], "reason": f"Created after as_of ({item['effective_at']} > {as_of})"})
                continue

        # Check source validity
        if not item.get("source_valid"):
            omitted.append({"key": item["key"], "reason": "Invalid or missing source evidence"})
            continue

        # Per-source diversity cap (max 3 items per exact source file)
        src = item["source"]
        src_count = source_counts.get(src, 0)
        if src_count >= 3 and not item.get("contradiction_flag") and not item.get("exact_match"):
            omitted.append({"key": item["key"], "reason": f"Per-source cap exceeded for {src}"})
            continue

        # Budget check (allow conflicts to bypass budget slightly)
        if spent + item["token_estimate"] > token_budget:
            if not item.get("contradiction_flag"):
                omitted.append({"key": item["key"], "reason": "Token budget exceeded"})
                continue

        selected.append(item)
        used_lanes.add(item["lane"])
        source_counts[src] = src_count + 1
        spent += item["token_estimate"]

    # Only report lanes that returned at least 1 candidate in lane_candidates
    real_lanes_used = sorted([lane for lane, count in lane_candidates.items() if count > 0])

    manifest = {
        "item_count": len(selected),
        "token_estimate": spent,
        "lanes_used": real_lanes_used,
        "lane_candidates": lane_candidates,
        "proposed_included": False if not include_proposed else "separate_debug_only",
        "source_counts": source_counts,
        "dominant_source_share": round(max(source_counts.values(), default=0) / max(1, len(selected)), 3),
        "diversity_applied": any("Per-source cap exceeded" in x["reason"] for x in omitted),
        "suppressed_redundant_hits": sum("Per-source cap exceeded" in x["reason"] for x in omitted),
        "legacy_items_requiring_corroboration": sum(
            item.get("record_shape") == "legacy_flat" for item in selected
        ),
    }

    return {
        "plan": plan,
        "items": selected,
        "manifest": manifest,
        "lane_latencies_ms": lane_latencies,
        "vector_backend": vector_meta,
        "omission_manifest": omitted,
    }
