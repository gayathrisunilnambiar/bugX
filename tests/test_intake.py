from sentinel_bisect.intake import derive_intent


def test_heuristic_extracts_pytest_target(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    intent = derive_intent("CI says tests/test_calculator.py::test_parse_total failed")
    assert intent.command == "pytest -q tests/test_calculator.py::test_parse_total"
    assert intent.source == "heuristic"
