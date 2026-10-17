"""Private memory must never fall back to a cloud extraction provider."""
import pytest
import dream_cycle


@pytest.mark.parametrize("providers", [["antigravity"], ["gemini"], ["ollama", "gemini"]])
def test_cloud_provider_rejected_before_any_extraction(monkeypatch, providers):
    monkeypatch.setattr(dream_cycle, "ENABLED_PROVIDERS", providers)
    def forbidden(*args, **kwargs):
        pytest.fail("No provider may receive private input with a cloud cascade configured")
    monkeypatch.setattr(dream_cycle, "_evaluate_provider_attempt", forbidden, raising=False)
    with pytest.raises(ValueError, match="local-only"):
        dream_cycle.extract_candidates_with_cascade("private input", {}, "source", "hash")
