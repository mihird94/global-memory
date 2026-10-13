from research_harness.eval.cli import run_evals


def test_evaluation_summary_fields_and_compact_output(capsys):
    report = run_evals(suite="continuation", export=False)
    assert "evaluation_summary" in report
    summary = report["evaluation_summary"]
    assert "canonical_cases" in summary
    assert "correlated_robustness_variants" in summary
    assert "answerable_cases" in summary
    assert "expected_abstentions" in summary
    assert "verdict" in summary
    assert "benchmark_verdict" in summary
    assert summary["official_benchmark"] is False
    assert summary["fresh_agent_continuation_run"] is False
    assert summary["verdict"] in ("regression_green", "regression_degraded")
    assert summary["benchmark_verdict"] == "not_external_benchmark"

    captured = capsys.readouterr().out
    assert "Canonical cases:" in captured
    assert "Correlated robustness variants:" in captured
    assert "Official benchmark status:       False" in captured
    assert "Fresh model continuation run:    False" in captured
    assert "External benchmark verdict:      not_external_benchmark" in captured
