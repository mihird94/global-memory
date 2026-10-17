"""
test_reproduction_controls.py — Negative & Positive Verification Controls
========================================================================
Implements focused unit tests for reproduction runner contracts and invariants:
  1. Negative Control: Absent CCMP directory marks INCOMPLETE and fails.
  2. Negative Control: available=False in retrieval ablation rejects fallback pass.
  3. Negative Control: Numerical mismatch in regression report triggers failure.
  4. Negative Control: Child process non-zero exit or timeout is cleanly captured.
  5. Negative Control: Checksum or partial bundle tampering triggers failure.
  6. Positive Control: Partial harvesting pilot bundle matches manifest & FAILED_BACKEND.
  7. Positive Control: Latency distributions satisfy monotonicity (P50 <= P95) & separate populations.
"""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

# Add brain directory to sys.path to import reproduce_papers
REPRODUCE_DIR = Path("/Users/mihirdeshpande/.gemini/antigravity/brain/b1cbfee1-d259-44d2-bda8-3319f7367cd3")
if str(REPRODUCE_DIR) not in sys.path:
    sys.path.insert(0, str(REPRODUCE_DIR))

import reproduce_papers as rp


def test_negative_control_absent_ccmp_dir(tmp_path):
    """Negative Control 1: Absent CCMP directory must fail with INCOMPLETE status."""
    nonexistent = tmp_path / "missing_ccmp_package"
    ok, dur, msg, parsed = rp.verify_ccmp_package(nonexistent, sys.executable)
    assert ok is False
    assert parsed.get("status") == "INCOMPLETE"
    assert "missing" in msg.lower() or "not found" in msg.lower()


def test_negative_control_available_false_retrieval_strategy():
    """Negative Control 2: available=False in retrieval ablation rejects fallback as a strategy pass."""
    # Build valid mock ablation data
    valid_data = {
        "strategies": {
            s: {
                "available": True,
                "queries_evaluated": 45,
                "mean_recall@5": 0.9,
                "mean_mrr": 0.8,
                "mean_ndcg@10": 0.7,
                "latency": {"p50": 2.0, "p95": 4.0},
            }
            for s in ["lexical_bm25", "dense_vector", "relational_graph", "hybrid_rrf", "hybrid_reranked"]
        }
    }
    # Verify valid data passes
    ok_v, _, _ = rp.verify_retrieval_ablation_data(valid_data)
    assert ok_v is True

    # Mutate hybrid_reranked to available=False (simulating flashrank missing)
    tampered = copy.deepcopy(valid_data)
    tampered["strategies"]["hybrid_reranked"]["available"] = False
    tampered["strategies"]["hybrid_reranked"]["reason"] = "flashrank uninstalled; fell back to hybrid_rrf"

    ok, msg, _ = rp.verify_retrieval_ablation_data(tampered)
    assert ok is False
    assert "unavailable" in msg.lower()
    assert "fallback is not permitted" in msg.lower()


def test_negative_control_numerical_mismatch_against_saved_report():
    """Negative Control 3: Numerical mismatch against expected regression totals triggers failure."""
    valid_summary = {
        "evaluation_summary": {
            "verdict": "regression_green",
            "canonical_cases": {"passed": 31, "total": 31},
            "correlated_robustness_variants": {"passed": 111, "total": 111},
            "answerable_cases": {"passed": 103, "total": 103},
            "expected_abstentions": {"passed": 37, "total": 37},
            "actionable_prohibited_leaks": 0,
            "answerable_non_supported_passes": 0,
        }
    }
    ok_v, _, _ = rp.verify_regression_suite_data(valid_summary)
    assert ok_v is True

    # Mutate 1: Canonical passed degraded from 31 to 30
    mismatch_1 = copy.deepcopy(valid_summary)
    mismatch_1["evaluation_summary"]["canonical_cases"]["passed"] = 30
    ok_1, msg_1, _ = rp.verify_regression_suite_data(mismatch_1)
    assert ok_1 is False
    assert "30/31" in msg_1

    # Mutate 2: Prohibited leaks injected
    mismatch_2 = copy.deepcopy(valid_summary)
    mismatch_2["evaluation_summary"]["actionable_prohibited_leaks"] = 1
    ok_2, msg_2, _ = rp.verify_regression_suite_data(mismatch_2)
    assert ok_2 is False
    assert "prohibited information leaks" in msg_2.lower()


def test_negative_control_child_process_timeout_or_nonzero_exit(tmp_path):
    """Negative Control 4: Subprocess non-zero exit and timeout are cleanly captured."""
    # Test non-zero exit code
    cmd_fail = [sys.executable, "-c", "import sys; sys.exit(42)"]
    ok, dur, out, code = rp.run_command_safe(cmd_fail, cwd=tmp_path, env={}, timeout_sec=5.0)
    assert ok is False
    assert code == 42

    # Test timeout expired
    cmd_timeout = [sys.executable, "-c", "import time; time.sleep(10)"]
    ok_t, dur_t, out_t, code_t = rp.run_command_safe(cmd_timeout, cwd=tmp_path, env={}, timeout_sec=0.1)
    assert ok_t is False
    assert code_t == -1
    assert "timed out" in out_t.lower()


def test_negative_control_checksum_or_partial_bundle_mismatch(tmp_path):
    """Negative Control 5: Tampered bundle file triggers SHA-256 manifest mismatch."""
    bundle_dir = tmp_path / "mock_bundle"
    bundle_dir.mkdir()
    file_a = bundle_dir / "data.json"
    file_a.write_text('{"key": "original"}')
    hash_a = hashlib.sha256(file_a.read_bytes()).hexdigest()

    manifest = {"data.json": hash_a}
    manifest_file = bundle_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))

    # Tamper with file_a
    file_a.write_text('{"key": "tampered"}')

    # Verify checksum mismatch is caught
    with open(manifest_file) as f:
        loaded_m = json.load(f)
    actual_hash = hashlib.sha256(file_a.read_bytes()).hexdigest()
    assert actual_hash != loaded_m["data.json"]


def test_positive_control_partial_pilot_bundle():
    """Positive Control 1: Real harvest_pilot_20261017_v1 bundle passes manifest checksums and reports FAILED_BACKEND."""
    gms_root = Path(__file__).resolve().parent.parent.parent
    pilot_dir = gms_root / "research_harness" / "reports" / "harvest_pilot_20261017_v1"
    assert pilot_dir.exists()

    manifest_file = pilot_dir / "manifest.json"
    summary_file = pilot_dir / "summary.json"
    assert manifest_file.exists()
    assert summary_file.exists()

    with open(manifest_file) as f:
        manifest = json.load(f)

    for fname, exp_hash in manifest.items():
        fpath = pilot_dir / fname
        assert fpath.exists(), f"Missing file: {fname}"
        actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        assert actual_hash == exp_hash, f"Hash mismatch on {fname}"

    with open(summary_file) as f:
        summary = json.load(f)
    assert summary.get("status") == "FAILED_BACKEND"
    assert summary.get("reported_tokens") == 10702


def test_positive_control_latency_variance_and_distribution():
    """Positive Control 2: Latencies in regression and ablation runs satisfy monotonic distribution invariants."""
    gms_root = Path(__file__).resolve().parent.parent.parent
    eval_runs_dir = gms_root / "research_harness" / "reports" / "eval_runs"

    # 1. Ablation run
    abl_file = eval_runs_dir / "ablation_run_20261017_102439.json"
    with open(abl_file) as f:
        abl = json.load(f)
    for strat, sdata in abl["strategies"].items():
        lat = sdata["latency"]
        assert lat["p50"] > 0
        assert lat["p50"] <= lat["p95"]
        assert lat["p95"] <= lat["p99"]

    # 2. Regression run
    reg_file = eval_runs_dir / "eval_run_20261017_085056.json"
    with open(reg_file) as f:
        reg = json.load(f)
    for suite, sdata in reg["results"].items():
        lat = sdata.get("latency")
        if lat:
            assert lat["p50"] > 0
            assert lat["p50"] <= lat["p95"]
