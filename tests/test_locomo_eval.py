"""Unit and integration tests for LoCoMo (Long Conversational Memory) adapter."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.datasets.locomo import LOCOMO_CASES, LoCoMoTestCase, get_locomo_cases_by_category
from eval.harness import MemoryEvalHarness, create_fixture_memory_root


def test_locomo_dataset_structure():
    """Verify LoCoMo dataset properties, category distribution, and robustness variants."""
    canonical_cases = [c for c in LOCOMO_CASES if c.variant_of is None]
    variant_cases = [c for c in LOCOMO_CASES if c.variant_of is not None]

    assert len(canonical_cases) == 12
    assert len(variant_cases) == 48
    assert len(LOCOMO_CASES) == 60

    categories = {c.category for c in LOCOMO_CASES}
    expected_categories = {"single_hop", "multi_hop", "temporal", "open_domain", "adversarial"}
    assert categories == expected_categories

    for cat in expected_categories:
        cat_cases = get_locomo_cases_by_category(cat)
        assert len(cat_cases) >= 10, f"Category {cat} should have at least 10 total cases (including variants)"


def test_locomo_adapter_execution(tmp_path):
    """Execute LoCoMo evaluation suite against isolated sandbox fixture."""
    root = create_fixture_memory_root(tmp_path)
    with MemoryEvalHarness(root) as harness:
        report = harness.run_locomo()

        assert report["suite"] == "Brain Conversational Memory — LoCoMo-inspired"
        assert report["official_public_benchmark"] is False
        assert report["canonical_cases"] == 12
        assert report["robustness_variants"] == 48
        assert report["total_cases"] == 60
        assert report["passed_cases"] == 60
        assert report["pass_rate"] == 1.0

        per_cat = report["per_category"]
        for cat in ("single_hop", "multi_hop", "temporal", "open_domain", "adversarial"):
            assert cat in per_cat
            assert per_cat[cat]["pass_rate"] == 1.0


def test_locomo_adversarial_abstention(tmp_path):
    """Verify that unrecorded/false-premise adversarial queries correctly abstain."""
    root = create_fixture_memory_root(tmp_path)
    with MemoryEvalHarness(root) as harness:
        from context_retrieval_planner import retrieve

        # Iceland offsite was never recorded
        ret = retrieve(root, "What were the flight details for Mihir's team offsite to Iceland in November 2026?")
        assert ret["evidence_status"] == "insufficient"
        assert ret.get("abstention_recommended", False) is True

        # Unrecorded AWS root secret
        ret2 = retrieve(root, "What is the production AWS root secret key stored in our chat logs?")
        assert ret2["evidence_status"] == "insufficient"
        assert ret2.get("abstention_recommended", False) is True
