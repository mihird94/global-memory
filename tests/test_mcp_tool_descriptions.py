import json

import memory_mcp_server
from memory_mcp_server import TOOLS, TOOLS_LIST


def test_write_tool_descriptions_expose_context_engineering_contract():
    save_description = TOOLS["mem_save_fact"]["description"].lower()
    assert "lowercase dotted canonical key" in save_description
    assert "rationale" in save_description
    assert "provenance" in save_description
    assert "evidence" in save_description
    assert "never save a bare status" in save_description

    harvest_description = TOOLS["mem_session_harvest"]["description"].lower()
    assert "interpretation, not authorship" in harvest_description
    assert "owner-contestable" in harvest_description

    log_description = TOOLS["mem_log_event"]["description"].lower()
    assert "what changed" in log_description
    assert "why" in log_description
    assert "not only an activity or status" in log_description
    note_description = TOOLS["mem_log_event"]["inputSchema"]["properties"]["note"]["description"].lower()
    assert "project/task" in note_description
    assert "evidence or verification" in note_description
    assert "skip routine reads" in note_description


def test_retrieval_and_project_descriptions_expose_context_safety():
    search_description = TOOLS["mem_search"]["description"].lower()
    assert "not automatic truth" in search_description
    assert "corroborate imported legacy" in search_description

    project_description = TOOLS["mem_project"]["description"].lower()
    assert "five-file project context bank" in project_description
    assert "decisions with rationale" in project_description
    assert "next action" in project_description


def test_brain_aliases_inherit_convention_aware_descriptions():
    assert TOOLS["brain_save_fact"]["description"].endswith(TOOLS["mem_save_fact"]["description"])
    assert TOOLS["brain_search"]["description"].endswith(TOOLS["mem_search"]["description"])
    assert len(TOOLS_LIST) == len(TOOLS)


def test_legacy_reputation_tool_disclaims_global_trust_score():
    description = TOOLS["mem_get_reputations"]["description"].lower()
    assert "do not interpret or display" in description
    assert "global agent trust score" in description


def test_context_governance_tools_and_aliases_are_registered():
    additions = {
        "context_packet", "curation", "memory_quality", "memory_repair",
        "lifecycle", "aliases", "project_timeline",
    }
    for capability in additions:
        mem_name = f"mem_{capability}"
        brain_name = f"brain_{capability}"
        assert mem_name in TOOLS
        assert brain_name in TOOLS
        assert TOOLS[brain_name]["description"].endswith(TOOLS[mem_name]["description"])
    assert len([name for name in TOOLS if name.startswith("mem_")]) == 59
    assert len(TOOLS) == 118


def test_new_read_only_tools_execute_against_minimal_memory_root(tmp_path, monkeypatch):
    (tmp_path / "semantic").mkdir()
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({"legacy_key": "active"}))
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "projectBrief.md").write_text("# Demo\n\nA demonstration project.")
    (project / "activeContext.md").write_text("# Active Context\n\nCurrent work is verification.")
    db_path = tmp_path / "gms_trust.sqlite"
    monkeypatch.setattr(memory_mcp_server, "MEM_ROOT", tmp_path)
    monkeypatch.setattr(memory_mcp_server, "DB_PATH", db_path)

    packet = json.loads(memory_mcp_server.tool_mem_context_packet({"query": "verification", "project": "demo"}))
    assert packet["schema_version"] == "gms-context-packet-v1"
    assert packet["packet_hash"].startswith("sha256:")

    aliases = json.loads(memory_mcp_server.tool_mem_aliases({"action": "inventory"}))
    assert "collisions" in aliases

    quality = json.loads(memory_mcp_server.tool_mem_memory_quality({"action": "conventions"}))
    assert quality["legacy_flat_records"] == 1

    repair = json.loads(memory_mcp_server.tool_mem_memory_repair({"action": "analyze", "key": "legacy_key"}))
    assert repair["legacy_key"] == "legacy_key"

    timeline = json.loads(memory_mcp_server.tool_mem_project_timeline({"project": "demo"}))
    assert timeline["project_id"] == "demo"

    status = json.loads(memory_mcp_server.tool_mem_curation({"action": "status"}))
    assert status["policy"] == "system-decides-user-may-contest-v1"

    history = json.loads(memory_mcp_server.tool_mem_lifecycle({"action": "history", "record_id": "missing"}))
    assert history == []


def test_mutating_new_tools_preview_by_default(tmp_path, monkeypatch):
    (tmp_path / "semantic").mkdir()
    (tmp_path / "semantic" / "facts.json").write_text(json.dumps({"opaque_status": "active"}))
    db_path = tmp_path / "gms_trust.sqlite"
    monkeypatch.setattr(memory_mcp_server, "MEM_ROOT", tmp_path)
    monkeypatch.setattr(memory_mcp_server, "DB_PATH", db_path)
    memory_mcp_server.init_db(db_path)

    archive = json.loads(memory_mcp_server.tool_mem_memory_repair({
        "action": "archive_preview", "key": "opaque_status", "actor": "system",
        "rationale": "No evidence supports this opaque status.",
    }))
    assert archive["status"] == "preview"
    assert json.loads((tmp_path / "semantic" / "facts.json").read_text())["opaque_status"] == "active"

    lifecycle = json.loads(memory_mcp_server.tool_mem_lifecycle({
        "action": "transition_preview",
        "request": {
            "request_id": "req-preview", "record_id": "rec-preview",
            "canonical_key": "demo.record", "next_state": "proposed", "operation": "add",
            "actor_id": "system", "actor_kind": "system",
            "rationale": "Preview a properly explained lifecycle addition.", "content": {"statement": "demo"},
        },
    }))
    assert lifecycle["status"] == "preview"
    assert lifecycle["applied"] is False


def test_mcp_handshake_advertises_current_brain_version():
    response = memory_mcp_server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
    })
    assert response["result"]["serverInfo"] == {"name": "brain-memory", "version": "2.1.0"}
