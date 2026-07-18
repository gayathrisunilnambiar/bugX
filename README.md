# Sentinel Bisect

AI can generate a patch in seconds; the question is whether it is correct or merely lucky. Sentinel Bisect finds the regression-introducing commit in isolated worktrees, reruns evidence until it is trustworthy, and verifies a proposed fix before accepting it. It never lets one unverified pass/fail signal decide the search.

## Setup, sample data, and running

### Judge quickstart: Docker, no local setup

This is the recommended evaluation path. It needs no Python installation, API key, account, test account, or hosted-service signup. There is no hosted demo instance: the reproducible Docker run is the deliberate way to test the project without setting up a local development environment.

```bash
docker build -t sentinel-bisect .
docker run --rm -p 8787:8787 sentinel-bisect
```

The container builds the included offline fixture, runs the flaky-aware bisection, and prints a `Timeline: http://localhost:8787/runs/<run-id>/timeline` URL. Leave it running, then inspect the produced evidence from another terminal or browser:

```bash
curl http://localhost:8787/runs
curl http://localhost:8787/runs/<run-id>/trace
```

Open `http://localhost:8787/runs/<run-id>/timeline` for the self-contained HTML timeline. This exact path was freshly rebuilt from a purged image and checked through all three endpoints. It does not use `OPENAI_API_KEY` or require external-service credentials.

### Local installation

Use Python 3.11 and Git for the local path. Docker above is preferred for a clean evaluation run.

**Windows PowerShell**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

**macOS/Linux bash/zsh**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

The editable install exposes `sentinel-bisect`. The offline demos and explicit `--mock-analysis` need no API key. Only live `--analyze`/`--verify` calls require `OPENAI_API_KEY`.

`wheel` is declared as a build requirement. On a restricted/offline package index, build isolation cannot fetch build requirements; use Docker, or run `python -m pip install setuptools wheel` followed by `python -m pip install --no-build-isolation -e .`.

### Included sample fixtures

`fixtures/flaky-regression-demo/` is the baseline sample: an unrelated intermittent test forces Sentinel to escalate reruns and route around an untrusted flaky midpoint.

```bash
python fixtures/build_fixture.py
sentinel-bisect --repo fixtures/flaky-regression-demo --command "pytest -q tests/test_calculator.py" --serve
```

`fixtures/hard-regression-demo/` is the analysis-quality stress case. It has a shared parser bug and three required verification gates: target, smoke, and a 780-case parameterized invariant. The disclosed mock harness demonstrates the complete tier1 -> tier2 -> tier3 verification/escalation path without claiming live-model behavior.

```bash
python fixtures/build_hard_fixture.py
sentinel-bisect --repo fixtures/hard-regression-demo --command "pytest -q tests/test_calculator.py::test_parse_total" --smoke-command "pytest -q tests/test_calculator.py::test_parse_average" --invariant-command "pytest -q tests/test_invariants.py" --runs 1 --analyze --verify --mock-analysis
```

`--mock-analysis` is explicit, deterministic, and visibly labeled `analysis_provider: "mock"` in its trace/report/timeline. It is never a fallback for a missing API key and does not prove that live GPT-5.6 will escalate.

### Supported platforms

- **Verified:** the Docker judge path (fresh image build, port mapping, `/runs`, `/trace`, and `/timeline`); WSL2 with DrvFs, including fixture removal retry handling; and direct Python 3.11 testing plus an installed console-script offline run on native Windows.
- **Historical compatibility check:** Python 3.10 with an external `StrEnum` shim/backport was previously exercised. Current package metadata requires Python 3.11 or newer, so use Python 3.11 for a new local installation.
- **Qualified native-Windows claim:** `_remove_tree` was spot-checked with an injected transient `PermissionError` and left no worktree directories behind. A host-side isolated editable install could not be completed while its package index was unavailable; the fresh Docker editable build did succeed.
- **Not yet verified:** clean native macOS or Linux local installs outside Docker. No cross-platform parity beyond these checks is implied.

## Codex and GPT-5.6 usage

### Where Codex accelerated the workflow

Codex produced the initial working scaffold: module boundaries, fixture generators, CLI wiring, and the first unit-test coverage. That shortened the path from idea to a runnable bisection demo while leaving the confidence policy and demo history as deliberate, reviewable choices.

Later Codex passes strengthened the verification bar with the shared-parser invariant and its flawed-patch controls, added the disclosed mock escalation harness, and performed the Windows/Python 3.11 spot checks and packaging fix. The value was not merely code generation: each change was paired with a reproducible control or environment check.

### Key engineering decisions

- **Disclosed mock instead of an unverified live-model claim:** API budget was unavailable, so the project uses an explicit deterministic provider with hand-built shallow, partial, and root-cause controls. It proves the real CLI/verify/escalation pipeline without pretending to characterize GPT-5.6.
- **No Programmatic Tool Calling (PTC):** analysis is a single high-stakes judgment call whose patch must be approved by verification, and each verification result changes the next action. That shape does not fit a bounded, no-judgment-needed PTC workflow.
- **Adaptive reruns are the default:** the demo no longer pins `--runs 3`, because that hid the flagship escalation behavior. The default `3,7,15` schedule makes the flaky-routing evidence visible by default.
- **Limits are stated, not inferred away:** mock runs, platform qualifications, and offline-install caveats are labeled in the README and expanded in [DECISIONS.md](DECISIONS.md).

### How GPT-5.6 is used

GPT-5.6 is reserved for two judgment-heavy tasks: intake extracts structured reproduction intent from a report, and analysis interprets a confirmed diff plus failure output into an explanation and minimal unified patch. It does not make bisection decisions.

Intake uses `gpt-5.6-luna` with low reasoning effort. Analysis uses `gpt-5.6-sol`, beginning at high effort; a failed verification escalates through high -> xhigh -> pro, capped by `--max-analysis-tier`. Retries carry `previous_response_id` plus `reasoning.context: all_turns`, so the next tier receives the prior reasoning context and the new verification failure rather than a duplicated full prompt. Both calls use explicit one-hour prompt caching on their stable instructions.

The proposed patch is applied only in a disposable worktree and must pass every configured target, smoke, and invariant gate. Gate-level outcomes appear in the JSON trace, Markdown report, and HTML timeline.

## Further detail

[DECISIONS.md](DECISIONS.md) contains the fuller decision record, including mock-harness disclosure, PTC rationale, and verification controls. The optional [GitHub Actions workflow](.github/workflows/sentinel-bisect.yml) demonstrates a manual CI integration that posts an offline-bisection summary to a pull request.

## License

MIT - see [LICENSE](LICENSE).
