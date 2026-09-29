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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Sequence

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

DEFAULT_LANE_WEIGHTS: dict[str, float] = {lane: 1.0 for lane in LANES}
DEFAULT_CANDIDATE_LIMITS: dict[str, int] = {
    "exact": 5,
    "bm25": 15,
    "vector": 8,
    "decisions": 10,
    "procedures": 6,
    "tasks": 10,
    "conflicts": 5,
    "episodes": 6,
    "graph": 10,
    "artifacts": 5,
}


@dataclass
class RetrievalConfig:
    """Typed configuration object governing multi-lane retrieval and fusion."""
    rrf_k: int = 60
    lane_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LANE_WEIGHTS))
    lane_candidate_limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CANDIDATE_LIMITS))
    graph_hops: int = 1
    vector_similarity_cutoff: float = 0.0
    rerank_policy: str = "never"  # never, always, assurance, intent, ambiguity, conditional
    rerank_k: int = 25
    rerank_model: str = "ms-marco-TinyBERT-L-2-v2"
    rerank_margin_threshold: float = 0.05
    minimum_top1_term_coverage: float = 0.60
    profile: str = "custom"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.rrf_k <= 0:
            raise ValueError(f"rrf_k must be positive, got {self.rrf_k}")
        if not (1 <= self.graph_hops <= 3):
            raise ValueError(f"graph_hops must be in 1..3, got {self.graph_hops}")
        if not (1 <= self.rerank_k <= 100):
            raise ValueError(f"rerank_k must be in 1..100, got {self.rerank_k}")
        if not (0.0 <= self.rerank_margin_threshold <= 1.0):
            raise ValueError(f"rerank_margin_threshold must be in [0.0, 1.0], got {self.rerank_margin_threshold}")
        if not (0.0 <= self.minimum_top1_term_coverage <= 1.0):
            raise ValueError(f"minimum_top1_term_coverage must be in [0.0, 1.0], got {self.minimum_top1_term_coverage}")
        if not (-1.0 <= self.vector_similarity_cutoff <= 1.0):
            raise ValueError(f"vector_similarity_cutoff must be in [-1.0, 1.0], got {self.vector_similarity_cutoff}")
        allowed_policies = {"never", "always", "assurance", "intent", "ambiguity", "conditional"}
        if self.rerank_policy not in allowed_policies:
            raise ValueError(f"rerank_policy must be one of {sorted(allowed_policies)}, got '{self.rerank_policy}'")
        for lane, w in self.lane_weights.items():
            if lane not in LANES:
                raise ValueError(f"Unknown lane '{lane}' in lane_weights")
            if not math.isfinite(w) or w < 0:
                raise ValueError(f"Lane weight for '{lane}' must be non-negative and finite, got {w}")
        for lane, lim in self.lane_candidate_limits.items():
            if lane not in LANES:
                raise ValueError(f"Unknown lane '{lane}' in lane_candidate_limits")
            if not isinstance(lim, int) or lim <= 0 or lim > 100:
                raise ValueError(f"Candidate limit for '{lane}' must be integer in 1..100, got {lim}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rrf_k": self.rrf_k,
            "lane_weights": dict(self.lane_weights),
            "lane_candidate_limits": dict(self.lane_candidate_limits),
            "graph_hops": self.graph_hops,
            "vector_similarity_cutoff": self.vector_similarity_cutoff,
            "rerank_policy": self.rerank_policy,
            "rerank_k": self.rerank_k,
            "rerank_model": self.rerank_model,
            "rerank_margin_threshold": self.rerank_margin_threshold,
            "minimum_top1_term_coverage": self.minimum_top1_term_coverage,
            "profile": self.profile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalConfig:
        weights = dict(DEFAULT_LANE_WEIGHTS)
        if "lane_weights" in data and isinstance(data["lane_weights"], dict):
            weights.update(data["lane_weights"])
        limits = dict(DEFAULT_CANDIDATE_LIMITS)
        if "lane_candidate_limits" in data and isinstance(data["lane_candidate_limits"], dict):
            limits.update(data["lane_candidate_limits"])
        return cls(
            rrf_k=int(data.get("rrf_k", 60)),
            lane_weights=weights,
            lane_candidate_limits=limits,
            graph_hops=int(data.get("graph_hops", 1)),
            vector_similarity_cutoff=float(data.get("vector_similarity_cutoff", 0.0)),
            rerank_policy=str(data.get("rerank_policy", "never")),
            rerank_k=int(data.get("rerank_k", 25)),
            rerank_model=str(data.get("rerank_model", "ms-marco-TinyBERT-L-2-v2")),
            rerank_margin_threshold=float(data.get("rerank_margin_threshold", 0.05)),
            minimum_top1_term_coverage=float(data.get("minimum_top1_term_coverage", 0.60)),
            profile=str(data.get("profile", "custom")),
        )

    @classmethod
    def from_profile(cls, profile: str) -> RetrievalConfig:
        p = profile.lower().strip()
        if p == "fast":
            return cls(
                rrf_k=60,
                lane_weights=dict(DEFAULT_LANE_WEIGHTS),
                lane_candidate_limits={
                    "exact": 5, "bm25": 10, "vector": 8, "decisions": 10,
                    "procedures": 6, "tasks": 10, "conflicts": 5, "episodes": 5,
                    "graph": 5, "artifacts": 5,
                },
                graph_hops=1,
                vector_similarity_cutoff=0.0,
                rerank_policy="never",
                rerank_k=25,
                rerank_margin_threshold=0.05,
                minimum_top1_term_coverage=0.60,
                profile="fast",
            )
        elif p == "standard":
            return cls(
                rrf_k=60,
                lane_weights=dict(DEFAULT_LANE_WEIGHTS),
                lane_candidate_limits=dict(DEFAULT_CANDIDATE_LIMITS),
                graph_hops=1,
                vector_similarity_cutoff=0.0,
                rerank_policy="conditional",
                rerank_k=25,
                rerank_margin_threshold=0.05,
                minimum_top1_term_coverage=0.60,
                profile="standard",
            )
        elif p in ("high", "high_assurance"):
            return cls(
                rrf_k=60,
                lane_weights={
                    "exact": 1.25, "bm25": 1.0, "vector": 1.0, "decisions": 1.25,
                    "procedures": 1.25, "tasks": 1.0, "conflicts": 1.5, "episodes": 0.9,
                    "graph": 1.25, "artifacts": 1.0,
                },
                lane_candidate_limits={
                    "exact": 5, "bm25": 20, "vector": 12, "decisions": 15,
                    "procedures": 8, "tasks": 10, "conflicts": 8, "episodes": 8,
                    "graph": 10, "artifacts": 6,
                },
                graph_hops=2,
                vector_similarity_cutoff=0.0,
                rerank_policy="always",
                rerank_k=25,
                rerank_margin_threshold=0.05,
                minimum_top1_term_coverage=0.60,
                profile="high_assurance",
            )
        else:
            raise ValueError(f"Unknown retrieval profile '{profile}'. Choose from: fast, standard, high_assurance")


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "he",
    "in", "is", "it", "its", "of", "on", "that", "the", "to", "was", "were",
    "will", "with", "what", "which", "who", "why", "how", "this", "these",
    "using", "only", "recorded", "evidence", "check", "guess", "within", "do", "not", "use",
    "did", "does", "or", "if", "than", "before", "after", "between", "about", "into",
    "then", "occur", "happened", "when", "where",
}


def _fact_context(value: Any) -> dict[str, Any]:
    """Describe a fact's epistemic shape without rewriting stored memory."""
    if isinstance(value, dict) and any(
        field in value for field in ("rationale", "provenance", "evidence", "scope", "implications")
    ):
        status = str(value.get("status") or "accepted").lower()
        lifecycle_status = status if status in {
            "active", "accepted", "archived", "superseded", "quarantined",
            "contested", "discarded", "expired",
        } else "accepted"
        eff_at = value.get("effective_at")
        if not eff_at:
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", str(value.get("provenance") or ""))
            if m:
                eff_at = m.group(1)
        return {
            "record_shape": "structured",
            "verification": status,
            "requires_corroboration": status not in ("accepted", "active", "verified"),
            "lifecycle_status": lifecycle_status,
            "effective_at": eff_at,
            "limitations": [],
        }
    text = str(value).strip().lower()
    lifecycle_status = "accepted"
    if re.match(r"^(archived|superseded|discarded|expired)\b", text):
        lifecycle_status = text.split(None, 1)[0]
    return {
        "record_shape": "legacy_flat",
        "verification": "unverified",
        "requires_corroboration": True,
        "lifecycle_status": lifecycle_status,
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
    if project:
        project_terms = set(_tokenize(project))
        tokens = [token for token in tokens if token not in project_terms]
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

    enabled_lanes = list(LANES) if required_lanes is None else list(dict.fromkeys(required_lanes))
    unknown_lanes = sorted(set(enabled_lanes) - set(LANES))
    if unknown_lanes:
        raise ValueError(f"Unknown retrieval lane(s): {', '.join(unknown_lanes)}")
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


def _run_lane_bm25(root: Path, query: str, query_tokens: list[str], project: str, as_of: str | None, candidate_limit: int = 15) -> list[dict[str, Any]]:
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
                                date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", p_clean)
                                if as_of and date_match and date_match.group(1) > str(as_of)[:10]:
                                    continue
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
    for rank, (score, doc_idx) in enumerate(scores[:max(1, candidate_limit)], start=1):
        doc_id, key, text, source = docs[doc_idx]
        fact_value = facts.get(key) if source.startswith("semantic/facts.json#") else None
        authority = "source_document" if "projects/" in source else _fact_authority(fact_value)
        context = {} if fact_value is None else _fact_context(fact_value)
        doc_eff_at = context.pop("effective_at", None)
        if not doc_eff_at:
            date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
            if date_match:
                doc_eff_at = date_match.group(1)
        items.append(_make_item("bm25", key, text, authority,
                                source, rank, component_score=score, bm25_score=score,
                                scope={"project": project} if project else {},
                                effective_at=doc_eff_at,
                                **context,
                                inclusion_reason=f"Lexical BM25 score {score:.2f}"))
    return items


@lru_cache(maxsize=64)
def _indexed_query_embedding(query: str, model: str) -> tuple[float, ...]:
    # This path is invoked only by an explicit indexed-vector request (for
    # example the CLI evaluation command), never by ordinary desktop browsing.
    import memoryctl
    return tuple(float(x) for x in memoryctl._embed(query, model))


def _run_lane_vector(
    root: Path,
    query: str,
    query_tokens: list[str],
    project: str,
    as_of: str | None,
    enable_indexed_vector: bool = False,
    embedding_model: str = "qwen3-embedding:0.6b",
    query_embedding: Sequence[float] | None = None,
    similarity_cutoff: float = 0.0,
    candidate_limit: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not enable_indexed_vector:
        return [], {"backend": "disabled_model_free", "available": False,
                    "reason": "Interactive navigation does not load an embedding model"}
    db = root / "gms_trust.sqlite"
    if not db.exists():
        return [], {"backend": "sqlite_embeddings", "available": False, "reason": "database missing"}
    try:
        conn = sqlite3.connect(str(db))
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT dim, model FROM gms_embeddings")
        stored_entries = cur.fetchall()
        conn.close()

        if not stored_entries:
            return [], {"backend": "sqlite_embeddings", "available": False,
                        "reason": "No embeddings stored in database"}

        stored_models = {row[1] for row in stored_entries}
        if embedding_model and embedding_model not in stored_models:
            return [], {
                "backend": "sqlite_embeddings",
                "available": False,
                "model": embedding_model,
                "reason": f"Model mismatch: requested '{embedding_model}' not found in gms_embeddings (available: {sorted(stored_models)})",
            }

        model_dims = {row[0] for row in stored_entries if row[1] == embedding_model}
        stored_dim = next(iter(model_dims)) if model_dims else stored_entries[0][0]

        vector = tuple(query_embedding) if query_embedding is not None else _indexed_query_embedding(query, embedding_model)
        if len(vector) != stored_dim:
            return [], {
                "backend": "sqlite_embeddings",
                "available": False,
                "model": embedding_model,
                "reason": f"Dimension mismatch: query dimension {len(vector)} != stored dimension {stored_dim}",
            }

        import memory_mcp_server
        hits = memory_mcp_server.search_sqlite_embeddings(
            list(vector), top_k=max(20, candidate_limit * 2), model=embedding_model, db_path=db
        )
        items = []
        for hit in hits:
            sim = float(hit.get("score") or 0.0)
            if sim < similarity_cutoff:
                continue
            source = str(hit.get("source") or "")
            # A project-scoped query may use global episodic history, but must
            # never import another named project's bank.
            marker = f"/projects/{project}/" if project else ""
            if project and "/projects/" in source and marker not in source:
                continue
            text = str(hit.get("text") or "")
            if as_of:
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", source)
                if date_match and date_match.group(1) > as_of[:10]:
                    continue
            rank = len(items) + 1
            items.append(_make_item(
                "vector", f"indexed.{hit.get('id', rank)}", text, "source_document", source, rank,
                component_score=sim, vector_similarity=sim, scope={"project": project} if project else {},
                inclusion_reason=f"Indexed embedding similarity {sim:.3f}"
            ))
            if len(items) >= candidate_limit:
                break
        return items, {"backend": "sqlite_embeddings", "available": True, "model": embedding_model, "hits": len(items)}
    except Exception as exc:
        return [], {"backend": "sqlite_embeddings", "available": False, "reason": str(exc)[:160]}


def _rerank_with_flashrank(
    query: str,
    items: list[dict[str, Any]],
    *,
    model: str,
    pool_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rerank fused candidates with a real local cross-encoder when available."""
    if not items:
        return items, {"enabled": True, "available": True, "backend": "flashrank", "reranked": 0}
    try:
        import memoryctl
        from flashrank import RerankRequest

        ranker = memoryctl._get_reranker(model)
        if ranker is None:
            return items, {"enabled": True, "available": False, "backend": "flashrank",
                           "model": model, "reason": "FlashRank package or model is unavailable"}
        pool = items[:max(1, min(pool_size, len(items)))]
        remainder = items[len(pool):]
        passages = [
            {"id": str(i), "text": f"{item.get('key', '')} {item.get('statement', '')}"}
            for i, item in enumerate(pool)
        ]
        results = ranker.rerank(RerankRequest(query=query, passages=passages))
        by_id = {str(i): item for i, item in enumerate(pool)}
        reranked: list[dict[str, Any]] = []
        for result in results:
            item = by_id.get(str(result.get("id")))
            if item is None:
                continue
            item["cross_encoder_score"] = round(float(result.get("score", 0.0)), 6)
            reranked.append(item)
        seen = {id(item) for item in reranked}
        reranked.extend(item for item in pool if id(item) not in seen)
        return reranked + remainder, {
            "enabled": True, "available": True, "backend": "flashrank",
            "model": model, "reranked": len(reranked),
        }
    except Exception as exc:
        return items, {"enabled": True, "available": False, "backend": "flashrank",
                       "model": model, "reason": str(exc)[:160]}


def _run_lane_decisions(root: Path, query_tokens: list[str], project: str, as_of: str | None, candidate_limit: int = 10) -> list[dict[str, Any]]:
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
                                if rank > candidate_limit:
                                    break
            except Exception:
                pass

    # 2. Database structured decisions from gms_claims or gms_context_candidates (accepted only)
    db = root / "gms_trust.sqlite"
    if db.exists() and rank <= candidate_limit:
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            q_filter = ""
            params = []
            if query_tokens:
                q_like = " OR ".join(["memory_key LIKE ? OR value LIKE ?"] * len(query_tokens[:6]))
                q_filter = f" AND ({q_like})"
                for t in query_tokens[:6]:
                    params.extend([f"%{t}%", f"%{t}%"])
            params.append(max(1, candidate_limit - rank + 1))
            rows = conn.execute(
                f"SELECT claim_id, memory_key, value, created_at FROM gms_claims WHERE status='active' AND (memory_key LIKE '%decision%' OR memory_key LIKE '%policy%'){q_filter} ORDER BY claim_id DESC LIMIT ?",
                params
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
                if rank > candidate_limit:
                    break
            conn.close()
        except Exception:
            pass
    return items


def _run_lane_procedures(root: Path, query_tokens: list[str], project: str, as_of: str | None, candidate_limit: int = 6) -> list[dict[str, Any]]:
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
                        if rank > candidate_limit:
                            break
            except Exception:
                pass

    # 2. SKILL.md protocols
    skill_fp = Path(__file__).resolve().parent.parent / "SKILL.md"
    if skill_fp.exists() and rank <= candidate_limit:
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
                        if rank > candidate_limit:
                            break
        except Exception:
            pass
    return items


def _run_lane_tasks(root: Path, project: str, as_of: str | None, candidate_limit: int = 10, query_tokens: list[str] | None = None, intent: str = "context") -> list[dict[str, Any]]:
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
            query_sql += f" ORDER BY updated_at DESC LIMIT {max(1, candidate_limit * 2)}"
            rows = conn.execute(query_sql, params).fetchall()
            for r in rows:
                if len(items) >= candidate_limit:
                    break
                task_id = str(r["task_id"])
                title = str(r["title"] or "")
                obj = str(r["objective"] or "")
                TASK_QUERY_TERMS = {"task", "tasks", "work", "todo", "todos", "job", "jobs", "in_progress", "status", "handoff", "checkpoint", "active"}
                if query_tokens and intent != "resume":
                    query_set = set(query_tokens)
                    if not (query_set & TASK_QUERY_TERMS):
                        combined = f"{task_id} {title} {obj}".lower()
                        if not any(t in combined for t in query_tokens):
                            continue
                rank = len(items) + 1
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
                t_dict = dict(r)
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


def _run_lane_conflicts(root: Path, query_tokens: list[str], project: str, as_of: str | None, candidate_limit: int = 5) -> list[dict[str, Any]]:
    items = []
    rank = 1
    # 1. Alias collisions from inventory
    try:
        inv = alias_inventory(root)
        for col in inv.get("collisions", []):
            can_k = col["canonical_key"]
            recs = col.get("records", [])
            key_terms = set(_tokenize(can_k))
            project_terms = set(_tokenize(project))
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
            if rank > candidate_limit:
                break
    except Exception:
        pass

    # 2. Superseded claims
    db = root / "gms_trust.sqlite"
    if db.exists() and rank <= candidate_limit:
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT claim_id, memory_key, value, created_at FROM gms_claims WHERE status='superseded' ORDER BY claim_id DESC LIMIT ?",
                (max(1, candidate_limit - rank + 1),)
            ).fetchall()
            for r in rows:
                k_tokens = set(_tokenize(r["memory_key"]))
                project_tokens = set(_tokenize(project)) if project else set()
                if project and not (k_tokens & set(query_tokens) or k_tokens & project_tokens):
                    continue
                if not query_tokens or any(t in k_tokens for t in query_tokens):
                    items.append(_make_item("conflicts", r["memory_key"], r["value"], "imported_legacy",
                                            f"claim:{r['claim_id']}", rank,
                                            component_score=0.8, contradiction_flag=True,
                                            warning="superseded record",
                                            effective_at=r["created_at"],
                                            inclusion_reason="Superseded claim in conflict chain"))
                    rank += 1
                    if rank > candidate_limit:
                        break
            conn.close()
        except Exception:
            pass
    return items


def _run_lane_episodes(root: Path, query_tokens: list[str], project: str, as_of: str | None, candidate_limit: int = 6) -> list[dict[str, Any]]:
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
                        if rank > candidate_limit:
                            break
            except Exception:
                pass

    # Daily notes recent updates
    hist_dir = root / "episodic" / "history"
    if hist_dir.exists() and rank <= candidate_limit:
        all_fps = sorted(hist_dir.glob("*.md"), reverse=True)
        if as_of:
            all_fps = [fp for fp in all_fps if fp.stem <= str(as_of)[:10]]
        daily_candidates: list[tuple[int, Path, str]] = []
        for fp in all_fps[:3]:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                current_header = ""
                for line in lines:
                    if line.startswith("#"):
                        current_header = line.lstrip("#").strip()
                    elif line.startswith("- "):
                        header_lower = current_header.lower()
                        line_lower = line.lower()
                        match_count = sum(1 for t in query_tokens if t in line_lower or t in header_lower) if query_tokens else 1
                        if match_count > 0:
                            entry_text = f"[{current_header}] {line.strip()}" if current_header else line.strip()
                            daily_candidates.append((match_count, fp, entry_text))
            except Exception:
                pass
        daily_candidates.sort(key=lambda x: x[0], reverse=True)
        for _, fp, entry_text in daily_candidates[:candidate_limit - rank + 1]:
            items.append(_make_item("episodes", f"daily.{fp.stem}.{rank}", entry_text,
                                    "source_document", str(fp), rank,
                                    component_score=0.70,
                                    effective_at=fp.stem,
                                    inclusion_reason="Recent daily note entry"))
            rank += 1
            if rank > candidate_limit:
                break
    return items


def _run_lane_graph(
    root: Path,
    query_tokens: list[str],
    project: str,
    as_of: str | None,
    graph_hops: int = 1,
    candidate_limit: int = 10,
) -> list[dict[str, Any]]:
    items = []
    db = root / "gms_trust.sqlite"
    if not db.exists() or not query_tokens:
        return items

    try:
        import networkx as nx
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        has_rel = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_relationships'").fetchone()
        if not has_rel:
            conn.close()
            return items

        # Canonical alias expansion for graph query tokens
        expanded_tokens = list(query_tokens)
        try:
            inv = alias_inventory(root)
            for t in query_tokens:
                for alias_entry in inv.get("aliases", []):
                    a_term = alias_entry.get("alias", "").lower()
                    c_term = alias_entry.get("canonical_key", "").lower()
                    if t in a_term or t in c_term:
                        for word in _tokenize(c_term):
                            if word not in expanded_tokens:
                                expanded_tokens.append(word)
        except Exception:
            pass

        columns = {row[1] for row in conn.execute("PRAGMA table_info(gms_relationships)")}
        has_entities_schema = {"subject_entity_id", "predicate", "object_entity_id"}.issubset(columns)

        G = nx.DiGraph()
        edge_records = []

        if has_entities_schema:
            has_entities_tbl = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_entities'").fetchone()
            entities = {}
            if has_entities_tbl:
                for erow in conn.execute("SELECT entity_id, name, entity_type, summary FROM gms_entities").fetchall():
                    entities[erow["entity_id"]] = {
                        "name": erow["name"], "type": erow["entity_type"], "summary": erow["summary"] or ""
                    }

            sql = """
                SELECT r.relationship_id,
                       se.entity_id AS subject_entity_id,
                       oe.entity_id AS object_entity_id,
                       se.name AS source_id,
                       COALESCE(oe.name, r.object_literal) AS target_id,
                       r.predicate AS rel_type,
                       COALESCE(se.summary, '') || CASE WHEN oe.summary IS NOT NULL THEN '; ' || oe.summary ELSE '' END AS summary,
                       1.0 AS weight, r.valid_from, r.valid_to, r.source_claim_id
                FROM gms_relationships r
                JOIN gms_entities se ON se.entity_id = r.subject_entity_id
                LEFT JOIN gms_entities oe ON oe.entity_id = r.object_entity_id
                WHERE (r.valid_to IS NULL OR r.valid_to > COALESCE(?, datetime('now')))
            """
            rows = conn.execute(sql, [as_of]).fetchall()
            for r in rows:
                sid = r["source_id"]
                tid = r["target_id"]
                if sid and tid:
                    w = float(r["weight"]) if r["weight"] is not None else 1.0
                    edge_data = {
                        "relationship_id": r["relationship_id"],
                        "source_id": sid,
                        "target_id": tid,
                        "rel_type": r["rel_type"],
                        "summary": r["summary"] or "",
                        "weight": w,
                        "valid_from": r["valid_from"],
                        "valid_to": r["valid_to"],
                        "source_claim_id": r["source_claim_id"],
                    }
                    edge_records.append(edge_data)
                    G.add_edge(sid, tid, **edge_data)
        else:
            sql = """
                SELECT id AS relationship_id, source_id, target_id, rel_type,
                       COALESCE(summary, '') AS summary, COALESCE(weight, 1.0) AS weight,
                       valid_from, valid_to
                FROM gms_relationships
                WHERE (valid_to IS NULL OR valid_to > COALESCE(?, datetime('now')))
            """
            rows = conn.execute(sql, [as_of]).fetchall()
            for r in rows:
                sid = r["source_id"]
                tid = r["target_id"]
                if sid and tid:
                    w = float(r["weight"]) if r["weight"] is not None else 1.0
                    edge_data = {
                        "relationship_id": r["relationship_id"],
                        "source_id": sid,
                        "target_id": tid,
                        "rel_type": r["rel_type"],
                        "summary": r["summary"] or "",
                        "weight": w,
                        "valid_from": r["valid_from"],
                        "valid_to": r["valid_to"],
                        "source_claim_id": None,
                    }
                    edge_records.append(edge_data)
                    G.add_edge(sid, tid, **edge_data)

        # 1. Match seed nodes from expanded query tokens
        seed_nodes = []
        token_set = {t.lower() for t in expanded_tokens if len(t) >= 3}
        for node in G.nodes():
            n_str = str(node).lower()
            n_tokens = set(_tokenize(n_str))
            if any(t == n_str or t in n_tokens or t in n_str for t in token_set):
                seed_nodes.append(node)

        # 2. HippoRAG Personalized PageRank (PPR) Diffusion
        ppr_scores: dict[Any, float] = {}
        if seed_nodes and len(G) > 0:
            try:
                pers = {n: (1.0 / len(seed_nodes) if n in seed_nodes else 0.0) for n in G.nodes()}
                UG = G.to_undirected(as_view=True)
                raw_ppr = nx.pagerank(UG, alpha=0.85, personalization=pers, max_iter=100, tol=1e-5)
                ppr_scores = {n: float(s) for n, s in raw_ppr.items()}
            except Exception:
                ppr_scores = {n: (1.0 if n in seed_nodes else 0.1) for n in G.nodes()}

        # 3. Score edges by composite endpoint PPR stationary probability
        scored_edges = []
        for e in edge_records:
            u, v = e["source_id"], e["target_id"]
            ppr_u = ppr_scores.get(u, 0.0)
            ppr_v = ppr_scores.get(v, 0.0)
            # Edge associative score combines endpoint probabilities and edge weight
            edge_score = (ppr_u + ppr_v) * e["weight"]
            # Fallback boost if directly matches query tokens
            if any(t in str(u).lower() or t in str(v).lower() for t in token_set):
                edge_score += 0.5
            if edge_score > 0.0:
                scored_edges.append((edge_score, e))

        scored_edges.sort(key=lambda x: x[0], reverse=True)

        seen_edges = set()
        for score, r in scored_edges[:candidate_limit]:
            pair_key = (r["source_id"], r["target_id"])
            if pair_key in seen_edges:
                continue
            seen_edges.add(pair_key)
            rank = len(items) + 1
            path = [r["source_id"], r["rel_type"], r["target_id"]]
            stmt = f"{r['source_id']} —[{r['rel_type']}]→ {r['target_id']}: {r['summary']}"
            norm_comp_score = round(min(1.0, max(0.5, score)), 3)
            items.append(_make_item(
                "graph", f"graph:{r['source_id']}_{r['target_id']}", stmt,
                "verified_system_output", "sqlite:gms_relationships", rank,
                component_score=norm_comp_score,
                graph_path=path,
                effective_at=r["valid_from"],
                source_id=r["source_id"],
                target_id=r["target_id"],
                predicate=r["rel_type"],
                valid_from=r["valid_from"],
                valid_to=r["valid_to"],
                source_claim_id=r["source_claim_id"],
                inclusion_reason=f"HippoRAG PPR associative triple ({r['source_id']} -> {r['target_id']})"
            ))

        # 4. Multi-hop 2-hop associative paths if requested and capacity remains
        if graph_hops >= 2 and len(items) < candidate_limit and len(G) > 0:
            target_nodes = [it["target_id"] for it in items if it.get("target_id")]
            for t_node in target_nodes:
                if len(items) >= candidate_limit:
                    break
                for succ in G.successors(t_node):
                    if len(items) >= candidate_limit:
                        break
                    pair_key = (t_node, succ)
                    if pair_key in seen_edges:
                        continue
                    seen_edges.add(pair_key)
                    e_data = G.get_edge_data(t_node, succ)
                    rank2 = len(items) + 1
                    path2 = [t_node, e_data.get("rel_type") or e_data.get("predicate", "related_to"), succ]
                    stmt2 = f"2-hop: {t_node} —[{path2[1]}]→ {succ}: {e_data.get('summary', '')}"
                    items.append(_make_item(
                        "graph", f"graph_2hop:{t_node}_{succ}", stmt2,
                        "verified_system_output", "sqlite:gms_relationships", rank2,
                        component_score=0.85,
                        graph_path=path2,
                        effective_at=e_data.get("valid_from"),
                        source_id=t_node,
                        target_id=succ,
                        predicate=path2[1],
                        valid_from=e_data.get("valid_from"),
                        valid_to=e_data.get("valid_to"),
                        source_claim_id=e_data.get("source_claim_id"),
                        inclusion_reason=f"2-hop Graph path connected via {t_node}"
                    ))

        conn.close()
    except Exception:
        pass
    return items


def _run_lane_artifacts(root: Path, query_tokens: list[str], project: str, as_of: str | None, candidate_limit: int = 5) -> list[dict[str, Any]]:
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
                        if rank > candidate_limit:
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
    query_embedding: Sequence[float] | None = None,
    enable_reranking: bool = False,
    rerank_model: str = "ms-marco-TinyBERT-L-2-v2",
    rerank_k: int = 25,
    reranker: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    config: RetrievalConfig | None = None,
) -> dict[str, Any]:
    root = Path(mem_root)
    cfg = config if config is not None else RetrievalConfig(
        rerank_policy="always" if enable_reranking else "never",
        rerank_model=rerank_model,
        rerank_k=rerank_k,
    )
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
    enabled_lanes = {lane["name"] for lane in plan["lanes"] if lane["enabled"]}

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

    limits = cfg.lane_candidate_limits

    if "exact" in enabled_lanes:
        _execute_lane("exact", lambda: _run_lane_exact(root, query, terms, project, as_of))
    if "bm25" in enabled_lanes:
        _execute_lane("bm25", lambda: _run_lane_bm25(root, query, query_tokens, project, as_of,
                                                     candidate_limit=limits.get("bm25", 15)))
    vector_meta: dict[str, Any] = {}
    def _vector_runner():
        items, meta = _run_lane_vector(
            root, query, query_tokens, project, as_of,
            enable_indexed_vector=enable_indexed_vector,
            embedding_model=embedding_model,
            query_embedding=query_embedding,
            similarity_cutoff=cfg.vector_similarity_cutoff,
            candidate_limit=limits.get("vector", 8),
        )
        vector_meta.update(meta)
        return items
    if "vector" in enabled_lanes:
        _execute_lane("vector", _vector_runner)
    if "decisions" in enabled_lanes:
        _execute_lane("decisions", lambda: _run_lane_decisions(root, query_tokens, project, as_of,
                                                              candidate_limit=limits.get("decisions", 10)))
    if "procedures" in enabled_lanes:
        _execute_lane("procedures", lambda: _run_lane_procedures(root, query_tokens, project, as_of,
                                                                candidate_limit=limits.get("procedures", 6)))
    if "tasks" in enabled_lanes:
        _execute_lane("tasks", lambda: _run_lane_tasks(root, project, as_of,
                                                       candidate_limit=limits.get("tasks", 10),
                                                       query_tokens=query_tokens,
                                                       intent=plan.get("intent", "context")))
    if "conflicts" in enabled_lanes:
        _execute_lane("conflicts", lambda: _run_lane_conflicts(root, query_tokens, project, as_of,
                                                               candidate_limit=limits.get("conflicts", 5)))
    if "episodes" in enabled_lanes:
        _execute_lane("episodes", lambda: _run_lane_episodes(root, query_tokens, project, as_of,
                                                             candidate_limit=limits.get("episodes", 6)))
    if "graph" in enabled_lanes:
        _execute_lane("graph", lambda: _run_lane_graph(root, query_tokens, project, as_of,
                                                       graph_hops=cfg.graph_hops,
                                                       candidate_limit=limits.get("graph", 10)))
    if "artifacts" in enabled_lanes:
        _execute_lane("artifacts", lambda: _run_lane_artifacts(root, query_tokens, project, as_of,
                                                               candidate_limit=limits.get("artifacts", 5)))

    # RECIPROCAL RANK FUSION (RRF)
    # Score(d) = sum_{lane} (w_lane / (rrf_k + rank_in_lane)) * boost
    rrf_scores: dict[str, float] = {}
    grouped_items: dict[str, dict[str, Any]] = {}
    item_lanes: dict[str, set[str]] = {}

    for it in all_items:
        key = canonicalize(it["key"])
        c_rank = it["component_rank"]
        boost = 1.2 if it.get("exact_match") else (1.3 if it.get("contradiction_flag") else 1.0)
        if it.get("record_shape") == "structured" or it.get("authority") in {"source_document", "verified_system_output"}:
            boost *= 1.12
        elif it.get("record_shape") == "legacy_flat":
            boost *= 0.88
        lane_w = float(cfg.lane_weights.get(it["lane"], 1.0))
        rrf_contrib = (1.0 / (float(cfg.rrf_k) + c_rank)) * boost * lane_w
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

    meta_terms = {
        "using", "only", "recorded", "evidence", "check", "guess", "within",
        "current", "memory", "state", "stale", "records",
    }
    mat_terms = set(query_tokens) - meta_terms - set(_tokenize(project))

    def _item_query_overlap(k: str) -> int:
        it = grouped_items[k]
        text_tokens = set(_tokenize(f"{it.get('key', '')} {it.get('statement', '')}"))
        return len(text_tokens & mat_terms) if mat_terms else len(text_tokens & set(query_tokens))

    # Sort merged candidates by RRF score descending, breaking ties by corroborated lanes and query overlap
    ranked_keys = sorted(
        grouped_items.keys(),
        key=lambda k: (
            -rrf_scores[k],
            -len(item_lanes.get(k, set())),
            -_item_query_overlap(k),
            -grouped_items[k].get("component_score", 0.0),
        ),
    )

    # Calculate fusion diagnostics
    if ranked_keys:
        top1_k = ranked_keys[0]
        top1_item = grouped_items[top1_k]
        top1_rrf_score = float(rrf_scores.get(top1_k, 0.0))
        top2_rrf_score = float(rrf_scores[ranked_keys[1]]) if len(ranked_keys) >= 2 else 0.0
        normalized_margin = float((top1_rrf_score - top2_rrf_score) / top1_rrf_score) if top1_rrf_score > 0 else 1.0

        top1_tokens = set(_tokenize(f"{top1_item.get('key', '')} {top1_item.get('statement', '')}"))
        top1_cov_terms = mat_terms & top1_tokens
        top1_query_term_coverage = float(len(top1_cov_terms) / len(mat_terms)) if mat_terms else 1.0

        top5_tokens = set()
        for k in ranked_keys[:min(5, len(ranked_keys))]:
            cand = grouped_items[k]
            top5_tokens |= set(_tokenize(f"{cand.get('key', '')} {cand.get('statement', '')}"))
        top5_cov_terms = mat_terms & top5_tokens
        top5_query_term_coverage = float(len(top5_cov_terms) / len(mat_terms)) if mat_terms else 1.0

        top1_lane_count = len(item_lanes.get(top1_k, set()))
        exact_match_available = bool(top1_item.get("exact_match", False))
        top1_requires_corroboration = bool(
            top1_item.get("record_shape") == "legacy_flat" or top1_item.get("requires_corroboration", False)
        )
        conflict_present = bool(any(
            grouped_items[k].get("contradiction_flag")
            or grouped_items[k].get("lifecycle_status") in {"quarantined", "contested"}
            for k in ranked_keys[:min(3, len(ranked_keys))]
        ))
    else:
        top1_rrf_score = 0.0
        top2_rrf_score = 0.0
        normalized_margin = 1.0
        top1_query_term_coverage = 0.0
        top5_query_term_coverage = 0.0
        top1_lane_count = 0
        exact_match_available = False
        top1_requires_corroboration = False
        conflict_present = False

    # Determine whether to execute reranker based on policy
    should_rerank = False
    selected_trigger = "policy_never"

    if cfg.rerank_policy == "always":
        should_rerank = bool(ranked_keys)
        selected_trigger = "always"
    elif cfg.rerank_policy == "assurance":
        if assurance == "high" and ranked_keys:
            should_rerank = True
            selected_trigger = "high_assurance"
        else:
            selected_trigger = "not_required"
    elif cfg.rerank_policy == "intent":
        if plan.get("intent") in {"decision", "procedure", "resume"} and ranked_keys:
            should_rerank = True
            selected_trigger = "decision_query"
        else:
            selected_trigger = "not_required"
    elif cfg.rerank_policy == "ambiguity":
        if len(ranked_keys) >= 2 and not exact_match_available and normalized_margin < cfg.rerank_margin_threshold:
            should_rerank = True
            selected_trigger = "ambiguous_fusion_margin"
        else:
            selected_trigger = "not_required"
    elif cfg.rerank_policy == "conditional":
        if assurance == "high" and ranked_keys:
            should_rerank = True
            selected_trigger = "high_assurance"
        elif plan.get("intent") in {"decision", "procedure", "resume"} and ranked_keys:
            should_rerank = True
            selected_trigger = "decision_query"
        elif conflict_present and ranked_keys:
            should_rerank = True
            selected_trigger = "conflicted_evidence"
        elif top1_requires_corroboration and ranked_keys:
            should_rerank = True
            selected_trigger = "legacy_requires_corroboration"
        elif (
            len(ranked_keys) >= 2
            and not exact_match_available
            and (top1_query_term_coverage >= 0.20 or top5_query_term_coverage >= 0.20)
            and normalized_margin < cfg.rerank_margin_threshold
        ):
            should_rerank = True
            selected_trigger = "ambiguous_fusion_margin"
        elif (
            ranked_keys
            and len(mat_terms) >= 2
            and top1_query_term_coverage < cfg.minimum_top1_term_coverage
            and top5_query_term_coverage > top1_query_term_coverage
            and top5_query_term_coverage >= 0.20
        ):
            should_rerank = True
            selected_trigger = "materially_incomplete_coverage"
        else:
            selected_trigger = "not_required"
    else:
        should_rerank = False
        selected_trigger = "policy_never"

    diagnostics = {
        "top1_rrf_score": round(top1_rrf_score, 6),
        "top2_rrf_score": round(top2_rrf_score, 6),
        "normalized_margin": round(normalized_margin, 4),
        "top1_query_term_coverage": round(top1_query_term_coverage, 4),
        "top5_query_term_coverage": round(top5_query_term_coverage, 4),
        "top1_lane_count": top1_lane_count,
        "exact_match_available": exact_match_available,
        "top1_requires_corroboration": top1_requires_corroboration,
        "conflict_present": conflict_present,
        "selected_trigger": selected_trigger,
    }

    rerank_meta: dict[str, Any] = {
        "enabled": cfg.rerank_policy != "never",
        "attempted": False,
        "available": True,
        "backend": "flashrank",
        "model": cfg.rerank_model,
        "pool_size": cfg.rerank_k,
        "reranked": 0,
        "policy": cfg.rerank_policy,
        "reason": selected_trigger,
        "latency_ms": 0.0,
    }

    if should_rerank and ranked_keys:
        t_rerank0 = time.perf_counter()
        fused = [grouped_items[key] for key in ranked_keys]
        for key, item in zip(ranked_keys, fused):
            item["rrf_score"] = round(rrf_scores[key], 5)
            item["lanes_matched"] = sorted(item_lanes[key])

        if reranker is not None:
            fused = reranker(query, fused)
            elapsed_ms = round((time.perf_counter() - t_rerank0) * 1000, 2)
            rerank_meta.update({
                "attempted": True,
                "available": True,
                "backend": "injected",
                "reranked": len(fused),
                "reason": selected_trigger,
                "latency_ms": elapsed_ms,
            })
        else:
            fused, sub_meta = _rerank_with_flashrank(query, fused, model=cfg.rerank_model, pool_size=cfg.rerank_k)
            elapsed_ms = round((time.perf_counter() - t_rerank0) * 1000, 2)
            rerank_meta.update({
                "attempted": True,
                "available": sub_meta.get("available", False),
                "backend": sub_meta.get("backend", "flashrank"),
                "reranked": sub_meta.get("reranked", 0),
                "reason": sub_meta.get("reason", selected_trigger) if not sub_meta.get("available") else selected_trigger,
                "latency_ms": elapsed_ms,
            })
        ranked_keys = [canonicalize(item["key"]) for item in fused]

    selected: list[dict[str, Any]] = []
    lifecycle_evidence: list[dict[str, Any]] = []
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

        if item.get("lifecycle_status") in {"archived", "superseded", "discarded", "expired"}:
            lifecycle_evidence.append(item)
            omitted.append({
                "key": item["key"],
                "reason": f"Lifecycle status is {item.get('lifecycle_status')}; excluded from active items",
                "lifecycle_status": item.get("lifecycle_status"),
                "source": item.get("source"),
            })
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
        "requested_lanes": sorted(enabled_lanes),
        "disabled_lanes": sorted(set(LANES) - enabled_lanes),
        "config": cfg.to_dict(),
        "profile": cfg.profile,
    }

    evidence_status, evidence_reasons = _classify_evidence(
        selected + lifecycle_evidence,
        query_tokens=query_tokens,
        intent=plan["intent"],
        project=project,
    )

    # Calibrated Abstention & Retrieval Confidence Calculation
    if not selected:
        retrieval_confidence = 0.0
        abstention_recommended = True
        abstention_reason = "No source-valid items survived retrieval and budget filters."
    else:
        top1_cov = float(diagnostics.get("top1_query_term_coverage", 0.0))
        top5_cov = float(diagnostics.get("top5_query_term_coverage", 0.0))
        margin = float(diagnostics.get("normalized_margin", 0.0))
        lane_count = int(diagnostics.get("top1_lane_count", 1))
        has_conflict = bool(diagnostics.get("conflict_present", False))
        is_supported = (evidence_status == "supported")

        # Composite calibrated confidence in [0.0, 1.0]
        # Cross-lane corroboration in top5 contributes to material term coverage
        effective_cov = max(top1_cov, top5_cov)
        base_confidence = 0.40 * effective_cov + 0.25 * min(1.0, lane_count / 2.0) + 0.15 * min(1.0, margin) + (0.20 if is_supported else 0.0)
        if effective_cov == 0.0:
            base_confidence = 0.0
        elif evidence_status == "insufficient":
            base_confidence = min(base_confidence, 0.25)
        if has_conflict:
            base_confidence *= 0.70

        retrieval_confidence = round(max(0.0, min(1.0, base_confidence)), 4)
        abstention_recommended = (retrieval_confidence < 0.40 or evidence_status == "insufficient")
        if abstention_recommended:
            abstention_reason = f"Low retrieval confidence ({retrieval_confidence:.2f}) and insufficient corroborated evidence."
            if evidence_status == "supported":
                evidence_status = "insufficient"
                evidence_reasons = [abstention_reason]
        else:
            abstention_reason = ""

    manifest["retrieval_confidence"] = retrieval_confidence
    manifest["abstention_recommended"] = abstention_recommended
    manifest["abstention_reason"] = abstention_reason

    return {
        "plan": plan,
        "items": selected,
        "lifecycle_evidence": lifecycle_evidence,
        "evidence_status": evidence_status,
        "evidence_reasons": evidence_reasons,
        "actionable": evidence_status == "supported",
        "retrieval_confidence": retrieval_confidence,
        "abstention_recommended": abstention_recommended,
        "abstention_reason": abstention_reason,
        "manifest": manifest,
        "lane_latencies_ms": lane_latencies,
        "vector_backend": vector_meta,
        "reranker": rerank_meta,
        "rerank_diagnostics": diagnostics,
        "omission_manifest": omitted,
    }


def _classify_evidence(
    items: list[dict[str, Any]], *, query_tokens: list[str], intent: str, project: str = ""
) -> tuple[str, list[str]]:
    """Classify retrieval evidence without collapsing it into a synthetic score."""
    if not items:
        return "insufficient", ["No source-valid evidence survived retrieval and budget filters."]

    meta_terms = {
        "using", "only", "recorded", "evidence", "check", "guess", "within",
        "current", "memory", "state", "stale", "records", "record",
    }
    non_substantive = {"mihir", "user", "agent", "system"}
    q_terms = {
        t for t in (set(query_tokens) - meta_terms - set(_tokenize(project)))
        if not (t.isdigit() or t in non_substantive)
    }
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        item_terms = set(_tokenize(f"{item.get('key', '')} {item.get('statement', '')}"))
        scored.append((len(q_terms & item_terms), item))
    max_overlap = max((score for score, _ in scored), default=0)
    minimum_overlap = min(2, max(1, len(q_terms)))
    if q_terms and max_overlap < minimum_overlap:
        return "insufficient", ["Retrieved records do not sufficiently overlap the material query terms."]

    focus = [item for score, item in scored if score == max_overlap]
    if any(item.get("contradiction_flag") or item.get("lifecycle_status") in {"quarantined", "contested"} for item in focus):
        return "conflicted", ["The most query-relevant evidence contains an unresolved contradiction or contest."]

    stale_states = {"archived", "superseded", "discarded", "expired"}
    stale_focus = [
        item for item in focus
        if item.get("lifecycle_status") in stale_states or item.get("freshness_state") == "stale"
    ]
    current_focus = [
        item for item in focus
        if item.get("source_valid")
        and item.get("lifecycle_status", "accepted") not in stale_states | {"quarantined", "contested"}
        and item.get("freshness_state") != "stale"
    ]
    if stale_focus and not current_focus:
        return "stale", ["Only archived, superseded, discarded, expired, or stale evidence supports the query."]

    action_intent = intent in {"resume", "procedure"}
    if action_intent:
        corroborated = [item for item in current_focus if not item.get("requires_corroboration")]
        if not corroborated:
            return "insufficient", ["Consequential action requires current corroborated evidence; only legacy or unverified records matched."]

    if current_focus:
        return "supported", ["Current source-valid evidence directly matches the query."]
    return "insufficient", ["No current source-valid evidence directly supports the query."]
