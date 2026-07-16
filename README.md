# Sentinel Bisect

Sentinel Bisect is a CLI investigator for regressions. It searches Git history in isolated worktrees, repeatedly runs the reproduction at every decision point, and refuses to treat inconsistent results as evidence. Once it confirms the introducing commit, it can use GPT-5.6 to explain the causal diff, suggest a patch, and verify it before presenting the result.

The project name is a working hackathon name; it was chosen to suggest a watchful engineering assistant rather than a thin `git bisect` wrapper.

## Why it exists

`git bisect` is fast but assumes a human already has a reliable pass/fail script. A one-off flaky result can send it down the wrong branch. Error-monitoring products can rank likely commits near an exception, but do not execute the suspected revision. CI analytics can surface flaky tests over time, but do not investigate an individual regression.

Sentinel's key distinction is that it establishes a repeatable signal while searching: all repeated runs must pass or all must fail to influence the search. Mixed outcomes are surfaced in the JSON trace and never silently accepted. The execution layer is deterministic and LLM-free; GPT-5.6 only handles the ambiguous language and explanation tasks.

### Proof: flaky disambiguation in action

The checked-in [demo trace](fixtures/demo-trace.json) is produced by regenerating the included fixture and running the documented command with three attempts per candidate. The fixture places the unrelated intermittent probe at the deterministic first midpoint. This excerpt is from that run; its `untrusted_flaky` decision means the commit could not be trusted to select a bisection branch. Rather than stopping, Sentinel routes around it: the very next trace step (see `substitute_for` below) is a stable adjacent commit that stands in as the decision point so the search keeps going. The `escalation` array records each rerun tier and its outcomes; here the single documented tier of 3 was still mixed, so the commit was routed around.

```json
{
  "commit": "1b1e9dca495f3f2da53b30babf4b890eb59b3a70",
  "classification": "flaky",
  "attempt_count": 3,
  "outcomes": ["fail", "pass", "fail"],
  "escalation": [
    { "runs": 3, "classification": "flaky", "outcomes": ["fail", "pass", "fail"] }
  ],
  "decision": "untrusted_flaky",
  "substitute_for": null
}
```

The following step in the trace carries `"decision": "substituted_pass"` and `"substitute_for": "1b1e9dca…"`, marking the adjacent commit that was used in place of the flaky one.

## Setup

Python 3.11+ and Git are required.

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env
# Add OPENAI_API_KEY to .env (or export it) for intake and analysis.
```

### macOS/Linux (bash/zsh)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
# Add OPENAI_API_KEY to .env (or export it) for intake and analysis.
```

The editable install exposes the `sentinel-bisect` command used below. The offline bisection demo does not require an API key. For model-enabled commands, load the key into your shell; Sentinel uses the standard `OPENAI_API_KEY` environment variable. If needed, `python -m sentinel_bisect.cli` is an equivalent fallback.

## End-to-end demo

Regenerate the intentionally small repository first:

```powershell
python fixtures/build_fixture.py
```

Then search it with a focused, stable reproduction command. The fixture deliberately includes an unrelated random flaky test, so the demo illustrates why the report names a target instead of blindly running every test.

```powershell
sentinel-bisect --repo fixtures/flaky-regression-demo --command "pytest -q tests/test_calculator.py" --runs 3 --report-file demo-report.md --trace-file demo-trace.json
```

Expected terminal output identifies the commit whose subject is `optimize parser result handling`. Open `demo-report.md` for the compact ASCII timeline and `demo-trace.json` for every attempt's captured output. The fixture generator is reproducible, so each demo begins with the same history.

For natural-language intake, put a report such as this into `bug.txt`:

```text
CI regression: tests/test_calculator.py::test_parse_total fails after a parser change.
```

Then run:

```powershell
sentinel-bisect --repo fixtures/flaky-regression-demo --bug-report bug.txt
```

With `OPENAI_API_KEY` configured, request a causal explanation and patch proposal. `--analyze` and `--verify` call the OpenAI API and require `OPENAI_API_KEY`; without it, the bisection still runs to completion and then the command exits with a clear `Error: --analyze requires the OPENAI_API_KEY environment variable to be set...` (or the equivalent message for `--verify`) instead of a report.

```powershell
sentinel-bisect --repo fixtures/flaky-regression-demo --command "pytest -q tests/test_calculator.py" --analyze --verify
```

The proposed patch is applied only inside a disposable worktree at the culprit revision. Sentinel runs the focused target repeatedly and reports verification only when every run passes.

### Visual timeline (`--serve`)

The Markdown report and JSON trace are also available as a colored HTML timeline over HTTP — the same flaky-disambiguation moment shown in the "Proof" section above, but rendered visually instead of as a JSON excerpt. Pass `--serve` and, once the bisection finishes, Sentinel starts a local server and prints the URL to open:

```powershell
sentinel-bisect --repo fixtures/flaky-regression-demo --command "pytest -q tests/test_calculator.py" --serve
```

```text
Culprit: 4d55af94be70f9781f97dac95343a0231d1a4d1c
Report: sentinel-report.md
Timeline: http://localhost:8787/runs/20260716-125306-4d55af9/timeline
```

The timeline is a self-contained page (no CDN dependencies) with a green/red/amber segment per commit, escalation tiers shown inline on any commit that was re-run at a larger rerun count, and a badge on any commit that stood in for a persistently-flaky one. It's served by a small FastAPI app (`report/server.py`), which also exposes:

- `GET /runs` — lists discovered run ids
- `GET /runs/{run_id}/trace` — the raw JSON trace
- `GET /runs/{run_id}/timeline` — the HTML visualization
- `GET /docs` — FastAPI's interactive API explorer

Use `--serve-port` to change the port (default `8787`) and `--runs-dir` to change where per-run trace files are kept for the server to discover (default `sentinel-runs/`).

## Architecture

- `intake/`: turns a bug report into a command and revision intent; GPT-5.6 is optional with an offline heuristic fallback.
- `orchestrator/`: creates disposable Git worktrees, performs repeated command trials, and writes a JSON trace.
- `analysis/`: supplies the confirmed diff and failure output to GPT-5.6 for a mechanism explanation and unified patch.
- `verify/`: applies the suggested patch in the temporary worktree and repeats the target/smoke commands.
- `report/`: creates a Markdown report and an HTML timeline visualization with a demo-friendly search timeline, and (via `--serve`) a small FastAPI server that serves them over HTTP.

## Built with Codex

Codex accelerated the project scaffold, test fixture generator, typed module boundaries, CLI wiring, and unit tests. The core confidence policy and small demo history were deliberately hand-tuned for easy explanation in a three-minute walkthrough. GPT-5.6 is reserved for two judgment-heavy tasks: extracting structured reproduction intent from raw reports, and interpreting a *confirmed* diff plus failure output into an explanation and minimal patch. It does not make bisection decisions.

## Known limitations

- Flaky detection uses an adaptive rerun schedule, not a formal statistical model: a candidate is classified as soon as one tier's batch of runs is unanimous (all pass or all fail), escalating to a larger, independent batch only when a tier is mixed. The schedule defaults to `3,7,15` and is configurable via `--rerun-schedule`; `--runs N` remains available as shorthand for a fixed, non-escalating single-tier schedule.
- A persistently flaky midpoint does not stop the search: Sentinel first escalates its rerun count, and if the signal still will not resolve it routes around the commit by substituting an adjacent commit as the decision point (recorded in the trace as `substitute_for`). The search only halts for human guidance in the rare case where every commit in the remaining range is persistently flaky.
- The fixture demonstrates Python/pytest; test commands themselves are shell commands and can target other stacks.
- Patch generation needs an OpenAI API key and can decline to produce a safe patch.
- Dependency and cross-repository bisection are intentionally outside this MVP.

## License

MIT — see [LICENSE](LICENSE).
