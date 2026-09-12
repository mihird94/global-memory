"""Canonical-key and auditable alias analysis without implicit merges."""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

def canonicalize(key: str) -> str:
    if "@" in key:
        base, qualifier = key.split("@", 1)
        return re.sub(r"[^a-z0-9]+", ".", base.lower()).strip(".") + "@" + qualifier.lower()
    return re.sub(r"[^a-z0-9]+", ".", key.lower()).strip(".")

def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS gms_memory_aliases (
      alias TEXT PRIMARY KEY, canonical_key TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
      state TEXT NOT NULL DEFAULT 'active', rationale TEXT NOT NULL, actor_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

def alias_inventory(mem_root: Path) -> dict[str, Any]:
    facts_path = Path(mem_root) / "semantic" / "facts.json"
    facts = json.loads(facts_path.read_text()) if facts_path.exists() else {}
    groups: dict[str, list[str]] = {}
    for key in facts: groups.setdefault(canonicalize(key), []).append(key)
    collisions = []
    for canonical, keys in sorted(groups.items()):
        if len(keys) > 1:
            values = [{"key": k, "value": facts[k], "canonical_proposal": canonical} for k in keys]
            same = len({json.dumps(v["value"], sort_keys=True) for v in values}) == 1
            collisions.append({"canonical_key": canonical, "records": values,
                               "proposal": "merge" if same else "contradict",
                               "requires_review": True, "resolved": False})
    db = Path(mem_root) / "gms_trust.sqlite"
    aliases = []
    if db.exists():
        conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
        try:
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_memory_aliases'").fetchone()
            if exists: aliases = [dict(r) for r in conn.execute("SELECT * FROM gms_memory_aliases ORDER BY alias")]
        finally: conn.close()
    return {"aliases": aliases, "collisions": collisions, "collision_count": len(collisions)}

def resolve_alias(mem_root: Path, key: str) -> dict[str, Any]:
    db = Path(mem_root) / "gms_trust.sqlite"; canonical = canonicalize(key)
    if db.exists():
        conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
        try:
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gms_memory_aliases'").fetchone()
            row=conn.execute("SELECT * FROM gms_memory_aliases WHERE alias=? AND state='active'",(key,)).fetchone() if exists else None
            if row: return {"input":key,"canonical_key":row["canonical_key"],"source":"registry","merged":False}
        finally: conn.close()
    return {"input":key,"canonical_key":canonical,"source":"normalization_preview","merged":False}

def consolidate_collision(mem_root: Path, canonical_key: str, preferred_key: str, *,
                          actor: str, rationale: str, apply: bool=False) -> dict[str,Any]:
    root=Path(mem_root); inventory=alias_inventory(root)
    collision=next((c for c in inventory["collisions"] if c["canonical_key"]==canonical_key),None)
    if not collision: return {"status":"error","error":"collision not found"}
    records={r["key"]:r["value"] for r in collision["records"]}
    if preferred_key not in records: return {"status":"error","error":"preferred key is not in collision"}
    if len(rationale.strip())<10: return {"status":"error","error":"substantive rationale required"}
    result={"status":"preview","canonical_key":canonical_key,"preferred_key":preferred_key,
            "aliases":sorted(records),"value":records[preferred_key],"recoverable":True}
    if not apply: return result
    facts_path=root/"semantic"/"facts.json"; facts=json.loads(facts_path.read_text())
    preferred_value=records[preferred_key]
    for key in records: facts.pop(key,None)
    facts[canonical_key]=preferred_value
    facts_path.write_text(json.dumps(facts,indent=2,sort_keys=True),encoding="utf-8")
    db=root/"gms_trust.sqlite"; conn=sqlite3.connect(db); ensure_tables(conn)
    now=datetime.now(timezone.utc).isoformat()
    for alias in records:
        if alias==canonical_key: continue
        conn.execute("INSERT OR REPLACE INTO gms_memory_aliases(alias,canonical_key,version,state,rationale,actor_id,created_at) VALUES(?,?,1,'active',?,?,?)",
                     (alias,canonical_key,rationale,actor,now))
        conn.execute("UPDATE gms_claims SET status='superseded',confidence=0.0 WHERE memory_key=? AND status='active'",(alias,))
    conn.execute("INSERT INTO gms_claims(memory_kind,memory_key,value,agent_id,branch,status,confidence,created_at) VALUES('semantic',?,?,?,'main','active',1.0,CURRENT_TIMESTAMP)",
                 (canonical_key,json.dumps(preferred_value,ensure_ascii=False) if isinstance(preferred_value,(dict,list)) else str(preferred_value),actor))
    conn.commit(); conn.close(); result["status"]="applied"; return result
