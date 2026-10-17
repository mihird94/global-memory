import json
import pytest
from research_harness.pilots import harvest_pilot as pilot


def fake_transport(fail=False):
    def transport(path, payload=None, timeout=5):
        if path == "/api/tags":
            return {"models": [{"name": m} for m in ["qwen2.5-coder:7b", "qwen3:8b"]]}
        if path == "/api/ps":
            return {"models": []}
        if "prompt" not in payload:
            return {}
        if fail:
            raise TimeoutError("simulated timeout")
        return {"response": "malformed JSON", "prompt_eval_count": 50, "eval_count": 10}
    return transport


def test_freeze_rejects_changed_protocol_before_dispatch(tmp_path, monkeypatch):
    bundle = tmp_path / "run"
    pilot.freeze(bundle)
    (bundle / "protocol.json").write_text("{}")
    monkeypatch.setattr(pilot, "http", lambda *a, **kw: pytest.fail("must not dispatch"))
    with pytest.raises(ValueError, match="Protocol changed"):
        pilot.execute(bundle)


def test_raw_invalid_output_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path / "original"))
    bundle = tmp_path / "run"
    pilot.freeze(bundle)
    monkeypatch.setattr(pilot, "http", fake_transport())
    pilot.execute(bundle)
    events = [json.loads(line) for line in (bundle / "dispatch.jsonl").read_text().splitlines()]
    assert len([e for e in events if e["state"] == "RESPONSE"]) == 8
    assert len([e for e in events if e["state"] == "INVALID_OUTPUT"]) == 8
    assert json.loads((bundle / "summary.json").read_text())["reported_tokens"] == 480


def test_timeout_keeps_partial_evidence_and_halts(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ROOT", str(tmp_path / "original"))
    bundle = tmp_path / "run"
    pilot.freeze(bundle)
    monkeypatch.setattr(pilot, "http", fake_transport(fail=True))
    pilot.execute(bundle)
    events = [json.loads(line) for line in (bundle / "dispatch.jsonl").read_text().splitlines()]
    assert [e["state"] for e in events] == ["STARTED", "ERROR"]
    assert json.loads((bundle / "summary.json").read_text())["status"] == "FAILED_BACKEND"
    assert (bundle / "manifest.json").exists()
