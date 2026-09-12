"""Deterministic explainable context packet assembly."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any
from context_retrieval_planner import retrieve

PROFILE_BUDGETS={"small":900,"standard":2400,"deep":6000}

def build_context_packet(mem_root:Path, query:str, *, project:str="", profile:str="standard", as_of:str|None=None)->dict[str,Any]:
    profile=profile.lower()
    if profile not in PROFILE_BUDGETS: raise ValueError("profile must be small, standard, or deep")
    result=retrieve(Path(mem_root),query,project=project,as_of=as_of,token_budget=PROFILE_BUDGETS[profile])
    packet={"schema_version":"gms-context-packet-v1","profile":profile,"project":project,"query":query,
            "as_of":as_of,"items":result["items"],"manifest":result["manifest"],"retrieval_plan":result["plan"]}
    canonical=json.dumps(packet,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    packet["packet_hash"]="sha256:"+hashlib.sha256(canonical.encode()).hexdigest()
    return packet
