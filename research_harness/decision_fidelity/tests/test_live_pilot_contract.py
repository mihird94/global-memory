"""Offline contract tests: zero LLM calls, production writes or internet access."""
import json
import pytest

from research_harness.decision_fidelity.live_pilot import (
    SCHEDULE_PATH, parse_model_object, preflight, validate_loopback, make_writer_prompt,
)
from research_harness.decision_fidelity.pilot_analysis import (
    paired_family_deltas, exact_sign_flip, cluster_bootstrap_ci, holm_adjust,
)


def test_frozen_schedule_sources_and_writer_reader_cells():
    manifest = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    assert preflight(manifest) == {
        "calls": 72, "reader_calls": 48, "writer_calls": 24, "families": 6,
    }


@pytest.mark.parametrize("bad", [
    "{}", "[]", "null", "plain text", '{"action":"ok"} trailing',
])
def test_strict_no_salvage(bad):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_model_object(bad)


def test_valid_json_action():
    assert parse_model_object('{"action":"abstain","reason":"protected"}')["action"] == "abstain"


def test_local_only_endpoints():
    assert validate_loopback("http://127.0.0.1:11434").endswith("/api/generate")
    assert validate_loopback("http://localhost:11434").endswith("/api/generate")
    for bad in [
        "https://localhost:11434", "http://example.com:11434",
        "http://127.0.0.1:11434/api/generate",
        "http://localhost:11434@evil.example:11434",
        "http://127.0.0.1:11434/?x=1",
    ]:
        with pytest.raises(ValueError):
            validate_loopback(bad)


def test_writer_prompts_have_only_public_source_argument():
    for arm in ("Arm_C_Ordinary_Structured", "Arm_D_Source_Bound"):
        prompt = make_writer_prompt(arm, "SYNTHETIC_ABC_SOURCE")
        assert "SYNTHETIC_ABC_SOURCE" in prompt
        assert "gold_canonical_action" not in prompt
        assert "gold_minimal_pair_action" not in prompt


def test_family_clustered_deltas_not_variant_pseudoreplication():
    rows = []
    for arm, corrects in (("C", [False, True]), ("D", [True, True])):
        for variant, value in zip(("canonical", "minimal_pair"), corrects):
            rows.append({
                "stage": "reader", "status": "COMPLETED",
                "family_id": "family-1", "variant_id": variant,
                "arm_id": arm, "correct": value,
            })
    assert paired_family_deltas(rows, "D", "C") == {"family-1": 0.5}


def test_partial_comparisons_raise():
    rows = [
        {"stage": "reader", "status": "COMPLETED", "family_id": "x",
         "variant_id": "canonical", "arm_id": "D", "correct": True},
    ]
    with pytest.raises(ValueError):
        paired_family_deltas(rows, "D", "C")


def test_signflip_includes_ties_and_is_exact():
    assert exact_sign_flip([0.0, 0.0, 0.0]) == 1.0
    assert exact_sign_flip([1.0, 1.0, 1.0]) == 0.125
    assert exact_sign_flip([1.0, 1.0, 1.0], "two-sided") == 0.25


def test_deterministic_bootstrap_and_holm():
    assert cluster_bootstrap_ci([0.5, 0.5]) == [0.5, 0.5]
    assert holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03}) == {
        "a": 0.03, "c": 0.06, "b": 0.06,
    }
