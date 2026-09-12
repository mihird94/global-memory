"""Classify nightly candidates into explicit proposed operations; never promotes."""
from __future__ import annotations
from typing import Any
from memory_aliases import canonicalize

VALID_OPERATIONS={"add","reinforce","merge","supersede","contradict","noop","archive"}

def classify_candidate(candidate:dict[str,Any], existing_facts:dict[str,Any])->dict[str,Any]:
    key=str(candidate.get("key") or ""); statement=str(candidate.get("statement") or "").strip()
    matches=[(k,v) for k,v in existing_facts.items() if canonicalize(k)==canonicalize(key)]
    if not key or not statement:
        op,reason="noop","missing durable key or statement"
    elif not matches:
        op,reason="add","no canonical or alias-equivalent active value exists"
    elif any(str(v).strip()==statement for _,v in matches):
        has_new_evidence=bool(candidate.get("evidence"))
        op="reinforce" if has_new_evidence else "noop"
        reason="same assertion with additional evidence" if has_new_evidence else "duplicate assertion without new evidence"
    else:
        # A different value is a contradiction unless explicit temporal evidence
        # identifies the prior record and its effective replacement window.
        freshness=candidate.get("freshness") or {}
        if freshness.get("supersedes") and freshness.get("effective_at"):
            op,reason="supersede","different time-sensitive value with explicit supersession evidence"
        else:
            op,reason="contradict","alias-equivalent key has a different value; preserve both pending review"
    return {"operation":op,"reason":reason,"compared_keys":[k for k,_ in matches],
            "requires_review":op not in {"noop"},"automatic_promotion":False}
