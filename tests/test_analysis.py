from __future__ import annotations

from types import SimpleNamespace

import pytest

from sentinel_bisect.analysis.service import (
    DEFAULT_ANALYSIS_EFFORT,
    DEFAULT_ANALYSIS_MODEL,
    MissingApiKeyError,
    analyze_culprit,
)


def test_analysis_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    with pytest.raises(MissingApiKeyError, match="OPENAI_API_KEY"):
        analyze_culprit("repo", "abc123", "failure")  # type: ignore[arg-type]


def _fake_openai(output_text='{"explanation": "boom", "patch": "diff --git a/a b/a"}', response_id="resp-1", usage=None):
    """A fake OpenAI client double: records every `.responses.create(**kwargs)` call
    (no real API calls, per the escalation-ladder tests requirement) and returns a
    canned response with `output_text` and `id`."""
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=output_text, id=response_id, usage=usage)

    class FakeOpenAI:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    return FakeOpenAI, calls


def test_base_analysis_call_uses_tier1_model_and_effort(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    fake_cls, calls = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.analysis.service.OpenAI", fake_cls)

    result = analyze_culprit("repo", "abc123", "failure", effort=DEFAULT_ANALYSIS_EFFORT)  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0]["model"] == DEFAULT_ANALYSIS_MODEL
    assert calls[0]["reasoning"] == {"effort": "high"}
    assert calls[0]["text"] == {"verbosity": "medium"}
    assert calls[0]["prompt_cache_options"] == {"mode": "explicit", "ttl": "1h"}
    assert "previous_response_id" not in calls[0]
    assert result.explanation == "boom"
    assert result.response_id == "resp-1"


def test_cache_stats_logged_at_debug_when_present(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    usage = SimpleNamespace(cached_tokens=128, cache_write_tokens=64)
    fake_cls, _ = _fake_openai(usage=usage)
    monkeypatch.setattr("sentinel_bisect.analysis.service.OpenAI", fake_cls)

    with caplog.at_level("DEBUG", logger="sentinel_bisect.analysis.service"):
        analyze_culprit("repo", "abc123", "failure")  # type: ignore[arg-type]

    assert "cached_tokens=128" in caplog.text
    assert "cache_write_tokens=64" in caplog.text


def test_no_cache_stats_logged_when_usage_absent(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    fake_cls, _ = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.analysis.service.OpenAI", fake_cls)

    with caplog.at_level("DEBUG", logger="sentinel_bisect.analysis.service"):
        analyze_culprit("repo", "abc123", "failure")  # type: ignore[arg-type]

    assert "cached_tokens" not in caplog.text


def test_analysis_model_and_effort_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    fake_cls, calls = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.analysis.service.OpenAI", fake_cls)

    analyze_culprit("repo", "abc123", "failure", model="gpt-5.6-custom", effort="xhigh")  # type: ignore[arg-type]

    assert calls[0]["model"] == "gpt-5.6-custom"
    assert calls[0]["reasoning"] == {"effort": "xhigh"}


def test_mode_only_tier_omits_effort(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    fake_cls, calls = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.analysis.service.OpenAI", fake_cls)

    analyze_culprit("repo", "abc123", "failure", mode="pro")  # type: ignore[arg-type]

    assert calls[0]["reasoning"] == {"mode": "pro"}


def test_escalation_retry_uses_previous_response_id_and_failure_context(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("sentinel_bisect.analysis.service.git", lambda *args: "diff --git a/a b/a")
    fake_cls, calls = _fake_openai(response_id="resp-2")
    monkeypatch.setattr("sentinel_bisect.analysis.service.OpenAI", fake_cls)

    analyze_culprit(
        "repo",
        "abc123",
        "failure",
        effort="xhigh",
        previous_response_id="resp-1",
        retry_context="target test still fails after applying the patch",
    )  # type: ignore[arg-type]

    assert calls[0]["previous_response_id"] == "resp-1"
    assert calls[0]["reasoning"] == {"effort": "xhigh", "context": "all_turns"}
    assert "target test still fails" in calls[0]["input"]
    # Retries must not resend the full diff — the prior response already has it.
    assert "CONFIRMED DIFF" not in calls[0]["input"]
