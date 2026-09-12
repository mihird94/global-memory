import json
import sqlite3
from pathlib import Path

from action_inbox import list_inbox_items, preview_inbox_action
from memory_repair import find_repair_evidence, analyze_missing_fields, stage_repair_candidate


def _setup_test_inbox_env(tmp_path: Path) -> Path:
    (tmp_path / "semantic").mkdir(parents=True, exist_ok=True)
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({
        "alphaos.swing.plugin_version": "2.0.0",
        "alphaos_swing_plugin_version": "1.9.0",
        "car_stickers_status": "active",
    }))

    hist_dir = tmp_path / "episodic" / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    (hist_dir / "2026-08-20.md").write_text("- Received physical car stickers from printer for event.")

    db = tmp_path / "gms_trust.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE gms_context_candidates (candidate_id TEXT PRIMARY KEY, canonical_key TEXT, content_hash TEXT, review_status TEXT, reviewed_by TEXT, created_at TEXT, payload_json TEXT)")
    conn.execute("INSERT INTO gms_context_candidates VALUES ('c_dec_1', 'policy.never_trust', 'h1', 'proposed', NULL, '2026-09-08', '{\"record_type\": \"policy\", \"statement\": \"Never trust agents globally\"}')")
    conn.commit()
    conn.close()
    return tmp_path


def test_action_inbox_consequence_ordering(tmp_path):
    root = _setup_test_inbox_env(tmp_path)
    inbox = list_inbox_items(root)

    assert inbox["schema_version"] == "gms-action-inbox-v1"
    assert inbox["total_items"] >= 2

    # Check consequence severity ordering (ascending)
    severities = [item["severity"] for item in inbox["items"]]
    assert severities == sorted(severities)

    # Key collision, proposed policy, and opaque status should be present
    categories = {item["category"] for item in inbox["items"]}
    assert "alias_collision" in categories or "blocking_contradiction" in categories
    assert "proposed_decision" in categories
    assert "opaque_status" in categories

    # Verify preview performs zero writes
    preview = preview_inbox_action(root, inbox["items"][0]["inbox_id"], "accept")
    assert preview["durable_writes"] == 0
    assert preview["dry_run"] is True


def test_memory_repair_discovers_evidence_and_labels_fields(tmp_path):
    root = _setup_test_inbox_env(tmp_path)

    # 1. Evidence search
    ev = find_repair_evidence(root, "car_stickers_status")
    assert ev["evidence_count"] >= 1
    assert "car stickers" in ev["evidence"][0]["excerpt"].lower()
    assert ev["evidence"][0]["excerpt_hash"].startswith("sha256:")

    # 2. Missing fields analysis
    analysis = analyze_missing_fields(root, "car_stickers_status")
    assert analysis["schema_version"] == "gms-repair-analysis-v1"
    assert "fields" in analysis
    assert analysis["fields"]["statement"]["status"] == "recovered_from_source"
    assert analysis["fields"]["source"]["status"] == "recovered_from_source"

    # 3. Candidate staging preview performs 0 writes
    stage_prev = stage_repair_candidate(
        root,
        "car_stickers_status",
        {"key": "car_stickers_status", "statement": "active"},
        apply=False,
    )
    assert stage_prev["durable_writes"] == 0
    assert stage_prev["legacy_preserved"] is True
