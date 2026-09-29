"""
migrate_system_health.py — Surgical cleanup and ontology migration for GMS.

1. Purges 16 test fixtures from facts.json & gms_trust.sqlite.
2. Fixes stale paths (gms_root).
3. Reconciles contradictions (alphaos compatibility & duplicate reminders).
4. Cleans up corrupt entities (prose > 80 chars, raw JSON).
5. Migrates flat birthdays into first-class PERSON entities with has_birthday relations.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

MEM_ROOT = Path("/Users/mihirdeshpande/memories")
DB_PATH = MEM_ROOT / "gms_trust.sqlite"

FIXTURE_KEYS = {
    "temp_key", "conflict_key", "k1", "k2", "fact_sem", "fact_op",
    "legacy_key", "new_dream_fact", "server_url", "server_url@staging",
    "world_capital", "test_mcp_key", "test_mcp_value", "test_fact_key",
    "test_reinforce"
}

FIXTURE_ENTITIES = {
    "Alice", "Bob", "Charlie", "test_mcp_key", "test_mcp_value",
    "test_fact_key", "test_reinforce", "k1", "k2", "v1", "v2",
    "temp_key", "conflict_key", "val1", "val2", "Paris", "world_capital"
}

def clean_facts_json():
    print("--- 1. Cleaning facts.json across buckets ---")
    for tier in ["semantic", "operational", "procedural"]:
        file_path = MEM_ROOT / tier / "facts.json"
        if not file_path.exists():
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        initial_len = len(data)
        # Purge fixture keys
        data = {k: v for k, v in data.items() if k not in FIXTURE_KEYS and not k.startswith("test_")}

        # Path corrections in semantic / operational
        if "gms_root" in data:
            data["gms_root"] = "/Users/mihirdeshpande/projects/global-memory"
            print("  [FIX] Updated gms_root to /Users/mihirdeshpande/projects/global-memory")

        if "alphaos_swing_workflow_skill_path" in data:
            data["alphaos_swing_workflow_skill_path"] = "/Users/mihirdeshpande/.gemini/config/skills/alphaos-swing-workflow"
            print("  [FIX] Updated alphaos_swing_workflow_skill_path")

        # Reconcile reminders summary
        if tier == "semantic" and "live_reminders_summary" in data:
            rem_val = data.pop("live_reminders_summary")
            print("  [FIX] Removed duplicate live_reminders_summary from semantic/facts.json")
        if tier == "operational":
            if "operational.live_reminders_summary" in data:
                rem_val = data.pop("operational.live_reminders_summary")
                data["operational.reminders.summary"] = rem_val
                print("  [FIX] Canonicalized operational.reminders.summary in operational/facts.json")

        # Reconcile alphaos status
        if "alphaos.compatibility.status" in data:
            data["alphaos.compatibility.status"] = "release_ready"
            print("  [FIX] Reconciled alphaos.compatibility.status to release_ready")

        removed = initial_len - len(data)
        print(f"  [{tier}] Removed {removed} test/duplicate keys. Remaining: {len(data)}")

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)

def clean_sqlite():
    print("\n--- 2. Cleaning gms_trust.sqlite ---")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # 1. Purge fixture claims
    cur.execute("DELETE FROM gms_claims WHERE memory_key IN ({})".format(','.join('?' for _ in FIXTURE_KEYS)), list(FIXTURE_KEYS))
    cur.execute("DELETE FROM gms_claims WHERE memory_key LIKE 'test_%' OR agent_id IN ('test', 'agent_test', 'test_agent')")
    print(f"  [CLAIMS] Deleted fixture claims: {cur.rowcount} rows affected")

    # 2. Purge fixture entities
    cur.execute("DELETE FROM gms_entities WHERE name IN ({})".format(','.join('?' for _ in FIXTURE_ENTITIES)), list(FIXTURE_ENTITIES))
    cur.execute("DELETE FROM gms_entities WHERE name LIKE 'test_%'")
    print(f"  [ENTITIES] Deleted fixture entities: {cur.rowcount} rows affected")

    # 3. Clean corrupted entity nodes (prose > 80 chars, raw JSON)
    cur.execute("SELECT entity_id, name FROM gms_entities")
    corrupt_ids = []
    for eid, name in cur.fetchall():
        if len(name) > 80 or name.startswith("{") or name.startswith("[") or "\n" in name:
            corrupt_ids.append(eid)
    if corrupt_ids:
        cur.execute("DELETE FROM gms_relationships WHERE subject_entity_id IN ({}) OR object_entity_id IN ({})".format(
            ','.join('?' for _ in corrupt_ids), ','.join('?' for _ in corrupt_ids)
        ), corrupt_ids + corrupt_ids)
        cur.execute("DELETE FROM gms_entities WHERE entity_id IN ({})".format(','.join('?' for _ in corrupt_ids)), corrupt_ids)
        print(f"  [ENTITIES] Purged {len(corrupt_ids)} corrupted prose/JSON entity nodes and their edges")

    # 4. Clean 18 daily reminder snapshot entity nodes
    cur.execute("SELECT entity_id, name FROM gms_entities WHERE name LIKE '%total_incomplete%' OR name LIKE '%personal_chores%'")
    snapshot_ids = [row[0] for row in cur.fetchall()]
    if snapshot_ids:
        cur.execute("DELETE FROM gms_relationships WHERE subject_entity_id IN ({}) OR object_entity_id IN ({})".format(
            ','.join('?' for _ in snapshot_ids), ','.join('?' for _ in snapshot_ids)
        ), snapshot_ids + snapshot_ids)
        cur.execute("DELETE FROM gms_entities WHERE entity_id IN ({})".format(','.join('?' for _ in snapshot_ids)), snapshot_ids)
        print(f"  [ENTITIES] Purged {len(snapshot_ids)} daily reminder snapshot nodes")

    conn.commit()
    conn.close()

def migrate_person_ontology():
    print("\n--- 3. Migrating Person Ontology (Contacts & Birthdays) ---")
    sem_path = MEM_ROOT / "semantic" / "facts.json"
    with open(sem_path, "r", encoding="utf-8") as f:
        facts = json.load(f)

    # Find birthday keys
    birthday_map = {}
    for k, v in facts.items():
        if k.startswith("birthday_"):
            name = k.replace("birthday_", "").replace("_", " ").title()
            if name.endswith(" Tai"):
                name = name.replace(" Tai", "")
            birthday_map[name] = v

    print(f"  Found {len(birthday_map)} people with birthdays: {list(birthday_map.keys())}")

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    now_iso = datetime.now(timezone.utc).isoformat()
    person_count = 0
    rel_count = 0

    for person_name, bday in birthday_map.items():
        # 1. Create or get PERSON entity
        cur.execute("SELECT entity_id FROM gms_entities WHERE LOWER(name) = LOWER(?)", (person_name,))
        row = cur.fetchone()
        if row:
            p_id = row[0]
            cur.execute("UPDATE gms_entities SET entity_type = 'PERSON', summary = ? WHERE entity_id = ?",
                        (f"Contact / Individual: {person_name}", p_id))
        else:
            cur.execute("INSERT INTO gms_entities (name, entity_type, summary, created_at, updated_at) VALUES (?, 'PERSON', ?, ?, ?)",
                        (person_name, f"Contact / Individual: {person_name}", now_iso, now_iso))
            p_id = cur.lastrowid
            person_count += 1

        # 2. Create or get Date Concept entity
        bday_str = str(bday).strip()
        cur.execute("SELECT entity_id FROM gms_entities WHERE LOWER(name) = LOWER(?)", (bday_str,))
        row_d = cur.fetchone()
        if row_d:
            d_id = row_d[0]
        else:
            cur.execute("INSERT INTO gms_entities (name, entity_type, summary, created_at, updated_at) VALUES (?, 'DATE', ?, ?, ?)",
                        (bday_str, f"Calendar Date: {bday_str}", now_iso, now_iso))
            d_id = cur.lastrowid

        # 3. Create typed has_birthday relationship
        cur.execute("""
            SELECT relationship_id FROM gms_relationships
            WHERE subject_entity_id = ? AND object_entity_id = ? AND predicate = 'has_birthday'
        """, (p_id, d_id))
        if not cur.fetchone():
            cur.execute("""
                INSERT INTO gms_relationships (subject_entity_id, predicate, object_entity_id, created_at)
                VALUES (?, 'has_birthday', ?, ?)
            """, (p_id, d_id, now_iso))
            rel_count += 1

    # Remove old flat birthday entity keys if they exist
    for k in facts.keys():
        if k.startswith("birthday_"):
            cur.execute("DELETE FROM gms_relationships WHERE subject_entity_id IN (SELECT entity_id FROM gms_entities WHERE name = ?)", (k,))
            cur.execute("DELETE FROM gms_entities WHERE name = ?", (k,))

    conn.commit()
    conn.close()
    print(f"  [PERSON] Modeled {len(birthday_map)} people ({person_count} newly inserted) with {rel_count} has_birthday relationships.")

if __name__ == "__main__":
    clean_facts_json()
    clean_sqlite()
    migrate_person_ontology()
    print("\n✅ System Health Migration Complete!")
