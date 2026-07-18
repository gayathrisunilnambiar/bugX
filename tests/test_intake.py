from __future__ import annotations

from types import SimpleNamespace

from sentinel_bisect.intake import derive_intent
from sentinel_bisect.intake.service import DEFAULT_INTAKE_EFFORT, DEFAULT_INTAKE_MODEL


def test_heuristic_extracts_pytest_target(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    intent = derive_intent("CI says tests/test_calculator.py::test_parse_total failed")
    assert intent.command == "pytest -q tests/test_calculator.py::test_parse_total"
    assert intent.source == "heuristic"


def _fake_openai(output_text='{"command": "pytest -q tests/test_calculator.py", "good": null, "bad": null}', usage=None):
    """A fake OpenAI client double: records every `.responses.create(**kwargs)` call
    (no real API calls) and returns a canned response."""
    calls: list[dict] = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=output_text, id="resp-intake-1", usage=usage)

    class FakeOpenAI:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    return FakeOpenAI, calls


def test_intake_call_uses_default_model_and_low_effort(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_cls, calls = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.intake.service.OpenAI", fake_cls)

    intent = derive_intent("CI says tests/test_calculator.py::test_parse_total failed")

    assert len(calls) == 1
    assert calls[0]["model"] == DEFAULT_INTAKE_MODEL == "gpt-5.6-luna"
    assert calls[0]["reasoning"] == {"effort": DEFAULT_INTAKE_EFFORT} == {"effort": "low"}
    assert calls[0]["prompt_cache_options"] == {"mode": "explicit", "ttl": "1h"}
    assert intent.source == "gpt-5.6-luna"


def test_intake_cache_stats_logged_at_debug_when_present(monkeypatch, caplog) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    usage = SimpleNamespace(cached_tokens=42, cache_write_tokens=17)
    fake_cls, _ = _fake_openai(usage=usage)
    monkeypatch.setattr("sentinel_bisect.intake.service.OpenAI", fake_cls)

    with caplog.at_level("DEBUG", logger="sentinel_bisect.intake.service"):
        derive_intent("some report")

    assert "cached_tokens=42" in caplog.text
    assert "cache_write_tokens=17" in caplog.text


def test_intake_model_and_effort_are_configurable(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_cls, calls = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.intake.service.OpenAI", fake_cls)

    derive_intent("some report", model="gpt-5.6-custom", effort="medium")

    assert calls[0]["model"] == "gpt-5.6-custom"
    assert calls[0]["reasoning"] == {"effort": "medium"}


def test_intake_model_configurable_via_env_var(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SENTINEL_INTAKE_MODEL", "gpt-5.6-env")
    monkeypatch.setenv("SENTINEL_INTAKE_EFFORT", "medium")
    fake_cls, calls = _fake_openai()
    monkeypatch.setattr("sentinel_bisect.intake.service.OpenAI", fake_cls)

    derive_intent("some report")

    assert calls[0]["model"] == "gpt-5.6-env"
    assert calls[0]["reasoning"] == {"effort": "medium"}
