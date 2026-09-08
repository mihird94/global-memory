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

import json
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
    """Safely parse value into dict if given as JSON string."""
    if isinstance(value, str):
        trimmed = value.strip()
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
            try:
                return json.loads(trimmed)
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
