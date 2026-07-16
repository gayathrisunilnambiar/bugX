import pytest

from sentinel_bisect.analysis.service import MissingApiKeyError, analyze_culprit


def test_analysis_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
        analyze_culprit("repo", "abc123", "failure")  # type: ignore[arg-type]
