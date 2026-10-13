from pathlib import Path

import pytest

from research_harness.eval.cli import run_ablations, run_evals, run_tuning
from research_harness.eval.harness import MemoryEvalHarness
from research_harness.ccp.robustness_report import compute_source_manifest, compute_test_manifest
from research_harness.ccp.schema import init_temporary_ccp_db
from research_harness.eval.harness import create_fixture_memory_root


@pytest.mark.parametrize("run", [run_evals, run_ablations, run_tuning])
def test_research_live_mode_is_rejected(run):
    with pytest.raises(ValueError, match="cannot access live memory"):
        run(live=True)


def test_harness_rejects_canonical_live_root():
    with pytest.raises(ValueError, match="live memory root"):
        MemoryEvalHarness(Path.home() / "memories")


@pytest.mark.parametrize("operation", [create_fixture_memory_root, init_temporary_ccp_db])
def test_research_writers_reject_configured_memory_root(monkeypatch, tmp_path, operation):
    live_root = tmp_path / "production"
    monkeypatch.setenv("MEMORY_ROOT", str(live_root))
    with pytest.raises(ValueError, match="live memory root"):
        operation(live_root / "experiment.sqlite")
    assert not live_root.exists()


def test_ccp_manifests_follow_workspace_move():
    sources = compute_source_manifest()["files"]
    tests = compute_test_manifest()["files"]
    assert sources and tests
    assert all(path.startswith("research_harness/ccp/") for path in sources)
    assert "research_harness/tests/test_ccp_harness.py" in tests
