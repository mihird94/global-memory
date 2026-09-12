"""
schemas.py — Namespaced Schema Contracts and Validation for GMS v2.1.0
=======================================================================
Provides strongly typed Pydantic models for memory facts across key namespaces:
  - infra.*: Infrastructure topology, endpoints, and credentials
  - trading.* / alphaos.*: Swing/algorithmic trade signals, targets, and stops
  - model.* / ml.*: ML checkpoints, context windows, and benchmark metrics
  - policy.* / operational.*: Agent behavior constraints, permissions, and settings
  - procedure.* / procedural.*: Reusable trigger-action playbooks and workflows

Enforces schema contracts at the trust gateway (memory_mcp_server / memoryctl)
while permitting unversioned / custom keys as untyped facts for backwards compatibility.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

try:
    from pydantic import BaseModel, Field, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    BaseModel = object  # type: ignore
    Field = lambda *args, **kwargs: None  # type: ignore
    class ValidationError(Exception):  # type: ignore
        pass


if PYDANTIC_AVAILABLE:
    class InfraNodeContract(BaseModel):
        host: str = Field(..., description="Hostname or alias (e.g. minipc, mac-m4)")
        ip: str | None = Field(default=None, description="IP address or Tailscale IP")
        port: int = Field(default=22, description="SSH or service port")
        user: str = Field(default="mihir", description="Default user login")
        role: str = Field(default="compute", description="Node role (e.g. compute, gateway, storage)")
        status: Literal["online", "offline", "unreachable", "maintenance", "unknown"] = "unknown"
        env: dict[str, str] = Field(default_factory=dict, description="Environment variables or tags")
        notes: str = Field(default="", description="Operational notes")

    class TradingSignalContract(BaseModel):
        ticker: str = Field(..., description="Asset symbol (e.g. NVDA, ADI, BTC)")
        action: Literal["buy", "sell", "hold", "exit", "watch", "trim"] = Field(..., description="Signal action")
        price: float | None = Field(default=None, description="Current or entry price")
        stop_loss: float | None = Field(default=None, description="Protective stop price")
        target_price: float | None = Field(default=None, description="Profit target price")
        timeframe: str = Field(default="swing", description="Trade horizon (e.g. intraday, swing, long-term)")
        thesis: str = Field(default="", description="Trade rationale or catalyst")
        status: Literal["open", "filled", "cancelled", "closed", "watching"] = "watching"
        score: float | None = Field(default=None, description="Ranking or model score")

    class ModelMetadataContract(BaseModel):
        name: str = Field(..., description="Model identifier or HuggingFace tag")
        path: str | None = Field(default=None, description="Filesystem or checkpoint path")
        context_window: int = Field(default=8192, description="Max context length tokens")
        device: str = Field(default="mps", description="Target execution device (mps, cuda, cpu)")
        eval_metric: str = Field(default="accuracy", description="Primary benchmark metric name")
        benchmark_score: float | None = Field(default=None, description="Benchmark score value")
        params_billion: float | None = Field(default=None, description="Parameter count in billions")

    class OperationalPolicyContract(BaseModel):
        agent_id: str = Field(default="*", description="Agent identity this applies to (* for all)")
        rule_name: str = Field(..., description="Unique policy or rule identifier")
        action: Literal["allow", "deny", "require_approval", "log_only"] = "allow"
        enabled: bool = Field(default=True, description="Whether rule is currently active")
        priority: int = Field(default=100, description="Priority integer (lower is higher priority)")
        description: str = Field(default="", description="Rule rationale and constraints")

    class ProceduralTaskContract(BaseModel):
        name: str = Field(..., description="Procedure name")
        trigger: str = Field(..., description="Trigger condition or event regex")
        action: str = Field(..., description="Action to execute or CLI command")
        prerequisites: list[str] = Field(default_factory=list, description="Prerequisite conditions")
        steps: list[str] = Field(default_factory=list, description="Ordered step instructions")
        timeout_seconds: int = Field(default=300, description="Execution timeout limit")

    class ScopeModel(BaseModel):
        level: Literal["global", "project", "workstream", "file", "system", "personal"] = "project"
        project: str = ""
        workstream: str = ""
        applies_to: list[str] = Field(default_factory=list)

    class ProvenanceModel(BaseModel):
        observed_agents: list[str] = Field(default_factory=list)
        extractor: str
        source_refs: list[str] = Field(default_factory=list)
        source_hashes: list[str] = Field(default_factory=list)
        extracted_at: str
        prompt_version: str = "context-harvest-v1"
        provider: str = ""
        model: str = ""

    class EvidenceItem(BaseModel):
        type: Literal[
            "user_instruction",
            "verified_system_output",
            "source_document",
            "agent_report",
            "test_output",
            "deterministic_derivation",
            "other"
        ] = "source_document"
        ref: str
        excerpt_hash: str = ""
        note: str = ""

    class FreshnessModel(BaseModel):
        effective_at: str | None = None
        review_after: str | None = None
        supersedes: list[str] = Field(default_factory=list)
        status: Literal["fresh", "possibly_stale", "stale", "timeless_until_superseded"] = "fresh"

    class ReviewModel(BaseModel):
        status: Literal["proposed", "accepted", "edited", "merged", "rejected", "deferred", "superseded"] = "proposed"
        requires_human: bool = True
        reasons: list[str] = Field(default_factory=list)
        reviewed_by: str | None = None
        reviewed_at: str | None = None
        review_rationale: str | None = None

    class DecisionContract(BaseModel):
        statement: str = Field(..., description="Chosen direction or durable decision")
        rationale: str = Field(..., description="Why this decision was made")
        implications: list[str] = Field(..., description="Actionable downstream constraints or practices")
        scope: ScopeModel = Field(default_factory=ScopeModel)
        provenance: ProvenanceModel
        evidence: list[EvidenceItem] = Field(default_factory=list)

    class PolicyContract(BaseModel):
        statement: str = Field(..., description="Durable policy or behavioral rule")
        rationale: str = Field(..., description="Reasoning and motivation behind policy")
        implications: list[str] = Field(default_factory=list)
        enforcement: str = Field(default="", description="How this policy is mechanically enforced")
        scope: ScopeModel = Field(default_factory=ScopeModel)
        provenance: ProvenanceModel

    class FactContract(BaseModel):
        statement: str = Field(..., description="Externally or mechanically verifiable statement")
        scope: ScopeModel = Field(default_factory=ScopeModel)
        provenance: ProvenanceModel
        evidence: list[EvidenceItem] = Field(default_factory=list)

    class ProcedureContract(BaseModel):
        trigger: str = Field(..., description="Trigger condition or event regex")
        action: str = Field(..., description="Action or CLI invocation")
        constraints: list[str] = Field(default_factory=list)
        scope: ScopeModel = Field(default_factory=ScopeModel)
        provenance: ProvenanceModel
        steps: list[str] = Field(default_factory=list)

    class ProjectStateContract(BaseModel):
        statement: str = Field(..., description="Current milestone, blocker, or focus")
        project: str = Field(..., description="Project identifier")
        effective_at: str = Field(..., description="ISO-8601 timestamp of state relevance")
        provenance: ProvenanceModel
        verification_status: Literal["verified", "partially_verified", "unverified", "contradicted"] = "unverified"
        scope: ScopeModel = Field(default_factory=ScopeModel)

    class ObservationContract(BaseModel):
        statement: str = Field(..., description="Observation not yet durable enough for fact/decision")
        provenance: ProvenanceModel
        uncertainty: str = Field(default="", description="Why this statement remains uncertain")
        scope: ScopeModel = Field(default_factory=ScopeModel)

    class QuestionContract(BaseModel):
        question: str = Field(..., description="Unresolved question requiring human or agent investigation")
        why_it_matters: str = Field(..., description="Downstream impact of leaving question unanswered")
        scope: ScopeModel = Field(default_factory=ScopeModel)
        provenance: ProvenanceModel

    class LessonCandidateContract(BaseModel):
        statement: str = Field(..., description="Reusable corrective rule")
        triggering_correction: str = Field(..., description="Incident or failure that triggered correction")
        scope: ScopeModel = Field(default_factory=ScopeModel)
        provenance: ProvenanceModel

    class ContextRecordEnvelope(BaseModel):
        schema_version: Literal["gms-context-record-v1"] = "gms-context-record-v1"
        record_type: Literal[
            "decision", "policy", "fact", "procedure",
            "project_state", "observation", "question", "lesson_candidate"
        ]
        key: str
        statement: str
        rationale: str = ""
        implications: list[str] = Field(default_factory=list)
        scope: dict[str, Any] = Field(default_factory=dict)
        provenance: dict[str, Any] = Field(default_factory=dict)
        evidence: list[dict[str, Any]] = Field(default_factory=list)
        freshness: dict[str, Any] = Field(default_factory=dict)
        review: dict[str, Any] = Field(default_factory=dict)
        authority: Literal[
            "user_instruction", "verified_system_output",
            "source_document", "agent_report", "llm_inference"
        ] = "llm_inference"
        verification: Literal[
            "verified", "partially_verified", "unverified", "contradicted"
        ] = "unverified"

    CONTRACT_REGISTRY: dict[str, type[BaseModel]] = {
        "infra": InfraNodeContract,
        "trading": TradingSignalContract,
        "model": ModelMetadataContract,
        "ml": ModelMetadataContract,
        "policy": OperationalPolicyContract,
        "operational": OperationalPolicyContract,
        "procedure": ProceduralTaskContract,
        "procedural": ProceduralTaskContract,
    }
else:
    CONTRACT_REGISTRY = {}


def get_namespace_for_key(key: str) -> str | None:
    """Extract namespace prefix from dot-separated or colon-separated key."""
    clean_k = key.strip().lower()

    # Specific hierarchical matching
    if clean_k.startswith(("alphaos.signal.", "alphaos.trade.", "alphaos.position.")):
        return "trading"
    if clean_k.startswith("alphaos.skill."):
        return None  # Permissive untyped for legacy skill strings
    if clean_k.startswith("alphaos.policy."):
        return "policy"
    if clean_k.startswith(("trading.", "trading:")):
        return "trading"
    if clean_k.startswith(("infra.", "infra:")):
        return "infra"
    if clean_k.startswith(("model.", "model:", "ml.", "ml:")):
        return "model"
    if clean_k.startswith(("policy.", "policy:", "operational.policy.")):
        return "policy"
    if clean_k.startswith(("procedure.", "procedure:", "procedural.task.")):
        return "procedure"

    for delimiter in [".", ":", "/"]:
        if delimiter in clean_k:
            prefix = clean_k.split(delimiter)[0]
            if prefix in ("infra", "trading", "model", "ml", "policy", "procedure"):
                return prefix
    return None



def parse_payload(value: Any) -> Any:
    """Safely parse value into dict if given as JSON string or python dict literal."""
    if isinstance(value, str):
        trimmed = value.strip()
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
            try:
                return json.loads(trimmed)
            except Exception:
                try:
                    import ast
                    val = ast.literal_eval(trimmed)
                    if isinstance(val, (dict, list)):
                        return val
                except Exception:
                    pass
    return value


def validate_fact(key: str, value: Any) -> tuple[bool, Any, str | None]:
    """
    Validate fact against registered namespace schema contract.

    Returns:
        (is_valid: bool, normalized_value: Any, error_message: str | None)

    Rules:
      1. If key matches a known namespace, value must validate against the Pydantic contract.
      2. If key does NOT match a known namespace, it is accepted as 'untyped' (permissive fallback).
      3. If Pydantic is not installed, permissive fallback with warning is used.
    """
    if not PYDANTIC_AVAILABLE:
        # Fallback gracefully if pydantic is not present
        return True, value, None

    namespace = get_namespace_for_key(key)
    if not namespace:
        # Permissive untyped fact
        return True, value, None

    model_cls = CONTRACT_REGISTRY[namespace]
    payload = parse_payload(value)

    if not isinstance(payload, dict):
        return False, None, (
            f"Schema validation failed for '{key}' [Contract: {model_cls.__name__}]: "
            f"Expected a JSON object/dictionary payload, received {type(payload).__name__}."
        )

    try:
        # Compatible with both Pydantic v1 and v2
        if hasattr(model_cls, "model_validate"):
            instance = model_cls.model_validate(payload)
            dumped = instance.model_dump()
        else:
            instance = model_cls.parse_obj(payload)  # type: ignore
            dumped = instance.dict()  # type: ignore
        return True, dumped, None
    except ValidationError as err:
        error_details = []
        for e in err.errors():
            loc = ".".join(str(x) for x in e.get("loc", []))
            msg = e.get("msg", "invalid")
            error_details.append(f"{loc}: {msg}")
        err_str = f"Schema validation failed for '{key}' [Contract: {model_cls.__name__}]: {'; '.join(error_details)}"
        return False, None, err_str
    except Exception as exc:
        return False, None, f"Schema validation error for '{key}': {exc}"


def list_contracts() -> dict[str, dict]:
    """Return dictionary of available schema contracts and their field definitions."""
    if not PYDANTIC_AVAILABLE:
        return {"error": "pydantic not installed"}

    contracts = {}
    for ns, model_cls in CONTRACT_REGISTRY.items():
        if model_cls.__name__ in contracts:
            continue
        fields = {}
        # Pydantic v1 vs v2 compatibility
        model_fields = getattr(model_cls, "model_fields", None) or getattr(model_cls, "__fields__", {})
        for field_name, field_info in model_fields.items():
            field_type = str(getattr(field_info, "annotation", getattr(field_info, "type_", "unknown")))
            desc = getattr(field_info, "description", "") or ""
            req = getattr(field_info, "is_required", lambda: True)() if callable(getattr(field_info, "is_required", None)) else getattr(field_info, "required", False)
            fields[field_name] = {
                "type": field_type,
                "required": req,
                "description": desc
            }
        contracts[model_cls.__name__] = {
            "namespaces": [k for k, v in CONTRACT_REGISTRY.items() if v == model_cls],
            "fields": fields
        }
    return contracts


# ──────────────────────────────────────────────────────────────────────────────
# Pass 5 Context Harvesting Deterministic Validators & Hashes
# ──────────────────────────────────────────────────────────────────────────────

SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"gh[pous]_[a-zA-Z0-9]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{22,}"),
    re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,}"),
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|secret|api_key|access_token|auth_token)\s*[:=]\s*['\"][^'\"]{6,}['\"]"),
]

FORBIDDEN_SCORE_KEYS = {
    "trust", "reliability", "reputation", "global_trust",
    "agent_trust", "agent_reputation", "health_score",
    "agent_confidence", "confidence_score", "trust_score"
}

GENERIC_RATIONALES = {
    "based on the journal", "based on journal", "as per journal",
    "from the journal", "from journal", "per journal",
    "n/a", "none", "unknown", "todo", "see journal", "not specified"
}

ALLOWED_RECORD_TYPES = {
    "decision", "policy", "fact", "procedure",
    "project_state", "observation", "question", "lesson_candidate"
}


def detect_secret_in_payload(val: Any) -> str | None:
    """Recursively search for sensitive tokens/keys in nested structures."""
    if isinstance(val, str):
        for pat in SECRET_PATTERNS:
            match = pat.search(val)
            if match:
                return f"Pattern matched '{pat.pattern[:25]}...'"
    elif isinstance(val, dict):
        for k, v in val.items():
            if isinstance(k, str):
                for pat in SECRET_PATTERNS:
                    if pat.search(k):
                        return f"Secret in key name '{k}'"
            res = detect_secret_in_payload(v)
            if res:
                return res
    elif isinstance(val, (list, tuple, set)):
        for item in val:
            res = detect_secret_in_payload(item)
            if res:
                return res
    return None


def has_forbidden_score(val: Any) -> bool:
    """Check if structure contains prohibited agent trust or synthetic composite scores."""
    if isinstance(val, dict):
        for k, v in val.items():
            k_lower = str(k).lower()
            if k_lower in FORBIDDEN_SCORE_KEYS:
                if isinstance(v, (int, float)):
                    return True
                if isinstance(v, str) and v.strip().replace(".", "", 1).isdigit():
                    return True
            if has_forbidden_score(v):
                return True
    elif isinstance(val, (list, tuple)):
        for item in val:
            if has_forbidden_score(item):
                return True
    return False


def compute_canonical_content_hash(payload: dict) -> str:
    """Compute reproducible SHA-256 hash of canonical candidate payload."""
    # Exclude mutable staging/review metadata so content hash is stable
    volatile_keys = {
        "candidate_id", "content_hash", "source_fingerprint",
        "review_status", "reviewed_by", "reviewed_at", "review_rationale",
        "merged_claim_id", "created_at", "updated_at"
    }
    canonical_dict = {k: v for k, v in payload.items() if k not in volatile_keys}
    canonical_str = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def compute_source_fingerprint(source_refs: list[str], source_hashes: list[str] | None = None) -> str:
    """Compute source fingerprint string from references and optional hashes."""
    norm_refs = sorted(str(r).strip() for r in (source_refs or []) if str(r).strip())
    norm_hashes = sorted(str(h).strip() for h in (source_hashes or []) if str(h).strip())
    combined = "|".join(norm_refs) + "::" + "|".join(norm_hashes)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def validate_context_candidate(
    candidate: Any,
    allowed_source_refs: list[str] | None = None,
    allowed_source_hashes: dict[str, str] | None = None,
) -> tuple[bool, dict | None, str | None]:
    """
    Deterministically validate a context harvesting candidate against the gms-context-record-v1 envelope.

    Returns:
        (is_valid: bool, normalized_payload: dict | None, error_message: str | None)
    """
    payload = parse_payload(candidate)
    if not isinstance(payload, dict):
        return False, None, f"Expected dictionary payload, received {type(payload).__name__}."

    # 1. Schema version
    schema_ver = payload.get("schema_version")
    if schema_ver != "gms-context-record-v1":
        return False, None, f"Invalid schema_version '{schema_ver}': expected 'gms-context-record-v1'."

    # 2. Record type
    rec_type = payload.get("record_type")
    if rec_type not in ALLOWED_RECORD_TYPES:
        return False, None, (
            f"Invalid record_type '{rec_type}'. "
            f"Must be one of: {', '.join(sorted(ALLOWED_RECORD_TYPES))}."
        )

    # 3. Canonical key
    key = str(payload.get("key", "")).strip()
    if not key or not re.match(r"^[a-zA-Z0-9_\.\:\-]+$", key) or len(key) < 3 or len(key) > 128:
        return False, None, f"Invalid canonical key format '{key}': must match ^[a-zA-Z0-9_.\\:-]+$ and length 3-128."

    # 4. Prohibited global trust / synthetic scores
    if has_forbidden_score(payload):
        return False, None, "Synthetic agent trust/reliability score field detected; global agent trust is retired."

    # 5. Secret detection
    secret_err = detect_secret_in_payload(payload)
    if secret_err:
        return False, None, f"Secret token detected in candidate payload: {secret_err}"

    # 6. Provenance requirements
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        return False, None, "Missing or invalid 'provenance' object."

    extractor = str(provenance.get("extractor") or provenance.get("extractor_agent", "")).strip()
    if not extractor:
        return False, None, "Provenance missing required 'extractor' identity."

    extracted_at = str(provenance.get("extracted_at", "")).strip()
    if not extracted_at:
        return False, None, "Provenance missing required 'extracted_at' timestamp."

    source_refs = provenance.get("source_refs")
    if not isinstance(source_refs, list) or len(source_refs) == 0:
        return False, None, "Provenance missing required non-empty 'source_refs' list."

    for ref in source_refs:
        ref_str = str(ref).strip()
        if not ref_str:
            return False, None, "Empty source reference found in provenance.source_refs."
        if allowed_source_refs is not None and ref_str not in allowed_source_refs:
            return False, None, f"Source reference '{ref_str}' does not belong to the processed batch."

    source_hashes = provenance.get("source_hashes") or []
    if allowed_source_hashes is not None and source_hashes:
        for sh in source_hashes:
            sh_clean = str(sh).strip()
            raw_hash = sh_clean.split(":", 1)[1] if ":" in sh_clean else sh_clean
            if raw_hash not in allowed_source_hashes.values():
                return False, None, f"Source hash '{sh_clean}' does not match expected source content hash."

    # 7. Record type specific requirements
    statement = str(payload.get("statement", "")).strip()
    rationale = str(payload.get("rationale", "")).strip()
    scope = payload.get("scope")
    if scope is not None and not isinstance(scope, dict):
        return False, None, "Scope must be a dictionary if provided."
    if scope is None:
        payload["scope"] = {}

    if rec_type == "decision":
        if not statement or len(statement) < 5:
            return False, None, "Decision requires a substantive 'statement' (minimum 5 characters)."
        if not rationale or len(rationale) < 10:
            return False, None, "Decision requires a substantive 'rationale' (minimum 10 characters)."
        if rationale.lower() == statement.lower():
            return False, None, "Decision rationale cannot be identical to the statement."
        if rationale.lower() in GENERIC_RATIONALES:
            return False, None, f"Decision rationale '{rationale}' is a generic placeholder and is rejected."
        implications = payload.get("implications")
        if not isinstance(implications, list) or len(implications) == 0:
            return False, None, "Decision requires at least one actionable downstream 'implications' item."
        for imp in implications:
            if not str(imp).strip():
                return False, None, "Empty string found in decision implications."
        evidence = payload.get("evidence")
        if not isinstance(evidence, list) or len(evidence) == 0:
            return False, None, "Decision requires at least one 'evidence' reference."

    elif rec_type == "policy":
        if not statement or len(statement) < 5:
            return False, None, "Policy requires a substantive 'statement' (minimum 5 characters)."
        if not rationale or len(rationale) < 10:
            return False, None, "Policy requires a substantive 'rationale' (minimum 10 characters)."
        if rationale.lower() == statement.lower():
            return False, None, "Policy rationale cannot be identical to the statement."
        if rationale.lower() in GENERIC_RATIONALES:
            return False, None, f"Policy rationale '{rationale}' is a generic placeholder and is rejected."
        implications = payload.get("implications") or []
        enforcement = str(payload.get("enforcement", "")).strip()
        if not enforcement and (not isinstance(implications, list) or len(implications) == 0):
            return False, None, "Policy requires either an actionable 'implications' list or 'enforcement' rule."

    elif rec_type == "fact":
        if not statement:
            val = payload.get("value")
            if val is not None and str(val).strip():
                statement = str(val).strip()
                payload["statement"] = statement
            else:
                return False, None, "Fact requires a non-empty 'statement' or 'value'."
        evidence = payload.get("evidence") or []
        if not isinstance(evidence, list) or len(evidence) == 0:
            # Check deterministic derivation or provenance
            if not provenance.get("source_refs"):
                return False, None, "Fact requires at least one 'evidence' reference or source ref."

    elif rec_type == "procedure":
        trigger = str(payload.get("trigger", "")).strip()
        action = str(payload.get("action", "")).strip()
        if not trigger or not action:
            return False, None, "Procedure requires non-empty 'trigger' and 'action'."

    elif rec_type == "project_state":
        if not statement:
            return False, None, "Project state requires a non-empty 'statement'."
        project = str(payload.get("project") or payload.get("scope", {}).get("project", "")).strip()
        if not project:
            return False, None, "Project state requires a non-empty 'project' identifier."
        payload["project"] = project
        effective_at = str(
            payload.get("effective_at")
            or payload.get("freshness", {}).get("effective_at")
            or payload.get("provenance", {}).get("extracted_at", "")
        ).strip()
        if not effective_at:
            return False, None, "Project state requires an 'effective_at' timestamp."
        payload["effective_at"] = effective_at
        v_status = payload.get("verification_status", "unverified")
        if v_status not in {"verified", "partially_verified", "unverified", "contradicted"}:
            return False, None, f"Invalid verification_status '{v_status}'."

    elif rec_type == "observation":
        if not statement:
            return False, None, "Observation requires a non-empty 'statement'."
        uncertainty = str(payload.get("uncertainty", "")).strip()
        review_reasons = payload.get("review", {}).get("reasons", []) if isinstance(payload.get("review"), dict) else []
        if not uncertainty and not review_reasons:
            return False, None, "Observation requires explicit 'uncertainty' or review reasons explaining its tentative status."

    elif rec_type == "question":
        question = str(payload.get("question", "")).strip()
        why_it_matters = str(payload.get("why_it_matters", "")).strip()
        if not question or not why_it_matters:
            return False, None, "Question requires non-empty 'question' and 'why_it_matters'."

    elif rec_type == "lesson_candidate":
        if not statement:
            return False, None, "Lesson candidate requires a non-empty 'statement'."
        corr = str(payload.get("triggering_correction") or payload.get("triggering_failure", "")).strip()
        if not corr:
            return False, None, "Lesson candidate requires 'triggering_correction' or triggering incident description."

    # 8. Normalize authority, verification, freshness, and review envelopes
    payload.setdefault("authority", "llm_inference")
    payload.setdefault("verification", "unverified")

    review = payload.setdefault("review", {})
    if not isinstance(review, dict):
        review = {"status": "proposed", "requires_human": True, "reasons": []}
        payload["review"] = review
    review.setdefault("status", "proposed")
    review.setdefault("requires_human", True)
    if "reasons" not in review or not isinstance(review["reasons"], list):
        review["reasons"] = [f"{rec_type} extracted by LLM"]

    freshness = payload.setdefault("freshness", {})
    if not isinstance(freshness, dict):
        freshness = {"status": "fresh"}
        payload["freshness"] = freshness
    freshness.setdefault("status", "fresh")

    # 9. Compute canonical content hash and source fingerprint
    content_hash = compute_canonical_content_hash(payload)
    source_fp = compute_source_fingerprint(source_refs, source_hashes)

    payload["content_hash"] = content_hash
    payload["source_fingerprint"] = source_fp
    if "candidate_id" not in payload:
        payload["candidate_id"] = f"cand_{key}_{content_hash[:12]}"

    return True, payload, None


# =============================================================================
# Source Reference & Excerpt Integrity
# =============================================================================

def compute_excerpt_hash(text: str) -> str:
    """Compute normalized SHA-256 hash for a text excerpt."""
    clean = "\n".join(line.rstrip() for line in (text or "").strip().splitlines())
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def extract_source_excerpt(
    content: str,
    anchor: str | None = None,
) -> tuple[bool, str | None, str | None]:
    """
    Extract a target excerpt from file content using an anchor locator.
    Supported anchors:
    - None or '': whole file
    - 'L10' or 'L10-L25' or '10-25': line numbers (1-indexed)
    - 'sec-1' or 'sec-...' or heading text: Markdown heading or anchor tag
    """
    if not anchor:
        return True, content, None

    clean_anchor = anchor.strip().lstrip("#")
    if not clean_anchor:
        return True, content, None

    # 1. Line range: L10-L25 or 10-25 or L10
    line_m = re.match(r"^L?(\d+)(?:-L?(\d+))?$", clean_anchor, re.IGNORECASE)
    if line_m:
        start_line = int(line_m.group(1))
        end_line = int(line_m.group(2)) if line_m.group(2) else start_line
        lines = content.splitlines()
        if start_line < 1 or start_line > len(lines):
            return False, None, f"Line range L{start_line}-L{end_line} is outside file length ({len(lines)} lines)."
        excerpt_lines = lines[start_line - 1 : min(end_line, len(lines))]
        return True, "\n".join(excerpt_lines), None

    # 2. Heading or Section anchor: e.g. sec-1, sec-outcome, or exact text
    lines = content.splitlines()
    found_idx = -1
    heading_level = 1

    anchor_norm = re.sub(r"[^a-zA-Z0-9]+", "-", clean_anchor).strip("-").lower()
    anchor_no_sec = re.sub(r"^sec-", "", anchor_norm)

    for i, line in enumerate(lines):
        if f'name="{clean_anchor}"' in line or f'id="{clean_anchor}"' in line:
            found_idx = i
            break
        m_head = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m_head:
            h_hashes, h_title = m_head.groups()
            h_slug = re.sub(r"[^a-zA-Z0-9]+", "-", h_title).strip("-").lower()
            if (
                anchor_norm in h_slug
                or h_slug in anchor_norm
                or anchor_no_sec in h_slug
                or h_title.lower().startswith(anchor_no_sec)
            ):
                found_idx = i
                heading_level = len(h_hashes)
                break

    if found_idx == -1:
        for i, line in enumerate(lines):
            if clean_anchor.lower() in line.lower():
                found_idx = i
                break

    if found_idx == -1:
        return False, None, f"Anchor '{anchor}' not found in document."

    section_lines = [lines[found_idx]]
    for line in lines[found_idx + 1 :]:
        m_head = re.match(r"^(#{1,6})\s+", line)
        if m_head and len(m_head.group(1)) <= heading_level:
            break
        section_lines.append(line)

    return True, "\n".join(section_lines), None


def validate_source_reference(
    source_ref: str,
    excerpt_hash: str | None = None,
    mem_root: Path | None = None,
    excerpt_text: str | None = None,
) -> tuple[bool, str, dict]:
    """
    Validate that a source reference resolves to a real file, contains the cited anchor,
    and matches the cited excerpt hash.

    Returns:
    (is_valid: bool, status_code: str, details: dict)
    status_code: 'valid' | 'missing_file' | 'missing_anchor' | 'hash_mismatch' | 'invalid_ref'
    """
    if not source_ref or not str(source_ref).strip():
        return False, "invalid_ref", {"error": "Source reference cannot be empty."}

    ref = str(source_ref).strip()
    if ref.startswith("file://"):
        ref = ref[7:]
    elif ref.startswith("memory://"):
        ref = ref[9:]

    path_part, _, anchor = ref.partition("#")
    path_part = path_part.strip()
    anchor = anchor.strip() if anchor else None

    root = mem_root or Path(os.environ.get("MEMORY_ROOT", Path.home() / "memories"))
    candidate_paths = [
        root / path_part,
        Path(path_part),
        root / path_part.lstrip("/"),
    ]
    if path_part.startswith("memories/"):
        candidate_paths.append(root / path_part[len("memories/"):])

    target_file: Path | None = None
    for p in candidate_paths:
        try:
            if p.is_file():
                target_file = p.resolve()
                break
        except Exception:
            continue

    if not target_file:
        return False, "missing_file", {
            "source_ref": source_ref,
            "path_part": path_part,
            "anchor": anchor,
            "error": f"Source file does not exist: {path_part}",
        }

    try:
        content = target_file.read_text(encoding="utf-8")
    except Exception as e:
        return False, "missing_file", {
            "source_ref": source_ref,
            "file_path": str(target_file),
            "error": f"Failed to read file: {e}",
        }

    ok, excerpt, anchor_err = extract_source_excerpt(content, anchor=anchor)
    if not ok:
        return False, "missing_anchor", {
            "source_ref": source_ref,
            "file_path": str(target_file),
            "anchor": anchor,
            "error": anchor_err or f"Anchor '{anchor}' not found in source file.",
        }

    computed_hash = compute_excerpt_hash(excerpt or "")
    whole_file_hash = compute_excerpt_hash(content)
    raw_file_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()

    if excerpt_hash:
        expected = str(excerpt_hash).strip()
        if expected.startswith("sha256:"):
            expected = expected[7:]

        matches = False
        if expected == computed_hash:
            matches = True
        elif expected in (whole_file_hash, raw_file_hash):
            matches = True
        elif excerpt_text and compute_excerpt_hash(excerpt_text) == expected:
            if excerpt_text.strip() in content:
                matches = True
        else:
            for para in content.split("\n\n"):
                if compute_excerpt_hash(para) == expected:
                    matches = True
                    break

        if not matches:
            return False, "hash_mismatch", {
                "source_ref": source_ref,
                "file_path": str(target_file),
                "anchor": anchor,
                "expected_hash": excerpt_hash,
                "computed_excerpt_hash": f"sha256:{computed_hash}",
                "error": f"Excerpt hash mismatch (expected '{excerpt_hash}', computed 'sha256:{computed_hash}'). Source text has changed.",
            }

    return True, "valid", {
        "source_ref": source_ref,
        "file_path": str(target_file),
        "anchor": anchor,
        "computed_hash": f"sha256:{computed_hash}",
        "excerpt_preview": (excerpt or "")[:200],
    }
