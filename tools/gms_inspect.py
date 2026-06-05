#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_mem_root() -> Path:
    memory_root = os.environ.get("MEMORY_ROOT")
    if memory_root:
        return Path(memory_root).expanduser()
    return Path.home() / "memories"


MEM_ROOT = _default_mem_root()
DB_PATH = MEM_ROOT / "gms_trust.sqlite"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _count_episodes() -> tuple[int, list[dict]]:
    history_dir = MEM_ROOT / "episodic" / "history"
    episodes = []
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.md"), reverse=True):
            episodes.append({
                "source": str(path),
                "type": "history",
                "size_bytes": path.stat().st_size,
            })

    journal = MEM_ROOT / "episodic" / "journal.md"
    if journal.exists():
        episodes.insert(0, {
            "source": str(journal),
            "type": "journal",
            "size_bytes": journal.stat().st_size,
        })
    return len(episodes), episodes[:5]


def _db_counts() -> dict:
    counts = {
        "claims_by_status": {},
        "quarantined_facts": 0,
        "quarantine_reviews": 0,
        "procedures": 0,
        "entities": 0,
        "relationships": 0,
    }
    if not DB_PATH.exists():
        return counts

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT status, COUNT(*) FROM gms_claims GROUP BY status")
        counts["claims_by_status"] = {status: count for status, count in cursor.fetchall()}
    except sqlite3.OperationalError:
        pass

    for table_name, key in (
        ("gms_quarantined_facts", "quarantined_facts"),
        ("gms_quarantine_reviews", "quarantine_reviews"),
        ("gms_procedures", "procedures"),
        ("gms_entities", "entities"),
        ("gms_relationships", "relationships"),
    ):
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            counts[key] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            pass

    conn.close()
    return counts


def _recent_quarantine_items(limit: int = 5) -> list[dict]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT fact_key, agent_id, branch, timestamp
            FROM gms_quarantined_facts
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [
        {
            "fact_key": fact_key,
            "agent_id": agent_id,
            "branch": branch,
            "timestamp": timestamp,
        }
        for fact_key, agent_id, branch, timestamp in rows
    ]


def build_snapshot() -> dict:
    semantic = _read_json(MEM_ROOT / "semantic" / "facts.json")
    operational = _read_json(MEM_ROOT / "operational" / "facts.json")
    procedural = _read_json(MEM_ROOT / "procedural" / "facts.json")
    episode_count, latest_episodes = _count_episodes()
    db_counts = _db_counts()

    return {
        "memory_root": str(MEM_ROOT),
        "facts": {
            "semantic": len(semantic),
            "operational": len(operational),
            "procedural": len(procedural),
        },
        "episodes": {
            "count": episode_count,
            "latest": latest_episodes,
        },
        "db": db_counts,
        "quarantine": {
            "recent": _recent_quarantine_items(),
        },
    }


def main() -> int:
    print(json.dumps(build_snapshot(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
