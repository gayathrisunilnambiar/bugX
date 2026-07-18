# Sentinel Bisect

Sentinel Bisect is a CLI investigator for regressions. It searches Git history in isolated worktrees, repeatedly runs the reproduction at every decision point, and refuses to treat inconsistent results as evidence. Once it confirms the introducing commit, it can use GPT-5.6 to explain the causal diff, suggest a patch, and verify it before presenting the result.

The project name is a working hackathon name; it was chosen to suggest a watchful engineering assistant rather than a thin `git bisect` wrapper.

## Why it exists

`git bisect` is fast but assumes a human already has a reliable pass/fail script. A one-off flaky result can send it down the wrong branch. Error-monitoring products can rank likely commits near an exception, but do not execute the suspected revision. CI analytics can surface flaky tests over time, but do not investigate an individual regression.

Sentinel's key distinction is that it establishes a repeatable signal while searching: all repeated runs must pass or all must fail to influence the search. Mixed outcomes are surfaced in the JSON trace and never silently accepted. The execution layer is deterministic and LLM-free; GPT-5.6 only handles the ambiguous language and explanation tasks.

### Proof: flaky disambiguation in action

The checked-in [demo trace](fixtures/demo-trace.json) is produced by regenerating the included fixture and running the documented command with the default adaptive rerun schedule (`3,7,15`). The fixture places the unrelated intermittent probe at the deterministic first midpoint. This excerpt is from that run; its `untrusted_flaky` decision means the commit could not be trusted to select a bisection branch even after escalating through every tier. Rather than stopping, Sentinel routes around it: the very next trace step (see `substitute_for` below) is a stable adjacent commit that stands in as the decision point so the search keeps going. The `escalation` array records each rerun tier and its outcomes; here all three tiers — 3, 7, and 15 attempts — stayed mixed, so the commit was routed around only after the full schedule was exhausted.

```json
{
  "commit": "1b1e9dca495f3f2da53b30babf4b890eb59b3a70",
  "classification": "flaky",
  "attempt_count": 15,
  "outcomes": ["fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail"],
  "escalation": [
    { "runs": 3, "classification": "flaky", "outcomes": ["fail", "pass", "fail"] },
    { "runs": 7, "classification": "flaky", "outcomes": ["pass", "fail", "pass", "fail", "pass", "fail", "pass"] },
    { "runs": 15, "classification": "flaky", "outcomes": ["fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail", "pass", "fail"] }
  ],
  "decision": "untrusted_flaky",
  "substitute_for": null
}
```

The following step in the trace carries `"decision": "substituted_pass"` and `"substitute_for": "1b1e9dca…"`, marking the adjacent commit that was used in place of the flaky one. This same escalation and substitution are visible in `demo-report.md`'s ASCII timeline (`escalated: 3->flaky, 7->flaky, 15->flaky`) and, if you pass `--serve`, in the rendered HTML timeline as three inline tier segments on the flaky commit followed by a substitution badge.

## Quick Test (No Setup)

Two options that need nothing installed beyond Docker or a browser — no venv, no `pip install`, no `.env`, no `OPENAI_API_KEY`. Both run the same offline bisection demo shown in the "Proof" section above: regenerate the fixture, bisect it with the adaptive rerun schedule, and serve the HTML timeline.

**Option A — Docker (instant output):**

```bash
docker build -t sentinel-bisect .
docker run --rm -p 8787:8787 sentinel-bisect
```

The container prints the same `Culprit: ...` / `Report: ...` / `Timeline: ...` lines a manual run produces. Because `-p 8787:8787` maps the container's port to the host, open the printed `http://localhost:8787/runs/.../timeline` URL directly in a browser on your machine. Leave the container running (it stays up to keep serving the timeline); `Ctrl+C` or `docker stop` to exit.

**Option B — GitHub Codespaces / VS Code Dev Containers (interactive session):**

Open this repository in a Codespace (**Code → Codespaces → Create codespace on main** on GitHub), or locally via the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) (**Reopen in Container**). [`.devcontainer/devcontainer.json`](.devcontainer/devcontainer.json) provisions Python 3.11, creates the venv, installs dependencies, and regenerates the fixture automatically — the terminal is ready for `sentinel-bisect` commands with no manual setup. Port `8787` is auto-forwarded, so `--serve` works the same way it does locally.

## Setup

The above requires no local install. Continue below only if you want to develop against the project directly (edit code, run the test suite, configure `OPENAI_API_KEY` for `--analyze`/`--verify`).

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
sentinel-bisect --repo fixtures/flaky-regression-demo --command "pytest -q tests/test_calculator.py" --report-file demo-report.md --trace-file demo-trace.json
```

Expected terminal output identifies the commit whose subject is `optimize parser result handling`. This uses the default adaptive rerun schedule (`3,7,15`), so the flaky commit hits in the fixture escalates through all three tiers before Sentinel routes around it — see the "Proof" section above for exactly what that looks like in the trace. Open `demo-report.md` for the compact ASCII timeline and `demo-trace.json` for every attempt's captured output. The fixture generator is reproducible, so each demo begins with the same history. (Pass `--runs N` instead to pin a fixed, non-escalating rerun count for a faster or simpler run; it's a shorthand, not the recommended default.)

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

### Reasoning-effort escalation demo

The hard-regression demo uses three required verification gates: target, smoke, and a parameterized shared-parser invariant. The invariant checks that parsing preserves every valid comma-separated integer segment across a range of sequence lengths and values, so wrapper hardcodes and a helper that retains only the first few values fail even when both known examples pass. Its criteria come from the helper's domain contract, not model-output tuning.

`fixtures/hard-regression-demo/` (regenerate with `python fixtures/build_hard_fixture.py`) is built so a patch that only fixes the symptom shown in the declared target's failing output can still fail a second, `--smoke-command`-checked function — the trigger for escalating `analysis/` to the next reasoning-effort tier (see "GPT-5.6 model configuration" above):

```powershell
sentinel-bisect --repo fixtures/hard-regression-demo --command "pytest -q tests/test_calculator.py::test_parse_total" --smoke-command "pytest -q tests/test_calculator.py::test_parse_average" --invariant-command "pytest -q tests/test_invariants.py" --analyze --verify
```

The offline bisection portion of this fixture (culprit-finding, no `--analyze`/`--verify`) is verified as part of this repo's test/demo workflow. Whether GPT-5.6 tier 1 actually needs escalating against the *live* model is something only a run with a real `OPENAI_API_KEY` can show — see `DECISIONS.md` for what was and wasn't confirmed.

### Disclosed mock analysis harness

When API budget is unavailable, the hard fixture can exercise the complete escalation pipeline without pretending to call GPT-5.6:

```powershell
sentinel-bisect --repo fixtures/hard-regression-demo --command "pytest -q tests/test_calculator.py::test_parse_total" --smoke-command "pytest -q tests/test_calculator.py::test_parse_average" --invariant-command "pytest -q tests/test_invariants.py" --runs 1 --analyze --verify --mock-analysis
```

`--mock-analysis` is an explicit, disclosed deterministic test double, never a fallback for a missing API key. It supplies hand-built controls for the actual shared-parser defect: wrapper hardcodes, a three-value partial repair, then the general helper repair. It proves that Sentinel's CLI, disposable worktrees, three verification gates, response-context retry wiring, trace, report, and timeline drive tier1 to tier3 end-to-end. It does **not** prove live GPT-5.6 will make the same choices; live escalation on this fixture remains untested because API budget is unavailable. Mock artifacts visibly identify `analysis_provider: "mock"` and display a disclosure banner; see `DECISIONS.md` for the rationale.

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

## CI Integration

[`.github/workflows/sentinel-bisect.yml`](.github/workflows/sentinel-bisect.yml) runs Sentinel Bisect in GitHub Actions and posts a compact summary as a PR comment — a minimal demonstration of the integration pattern, not a full product.

**Trigger:** manual `workflow_dispatch` only, with four inputs: `pr_number`, `good`, `bad`, and `command`. **This is a deliberate MVP simplification.** Automatically reacting to "a PR's CI check failed" would require correlating a `workflow_run` completion event back to the right PR, head SHA, and the specific failing check's reproduction command — a mapping that's specific to each repo's CI setup and easy to get subtly wrong within a short build. Manual dispatch keeps the demo honest: you supply the known-good/known-bad commits and the failing command, same as running `sentinel-bisect` locally.

**What it requires:** nothing beyond the repository's default `GITHUB_TOKEN` (used to post the comment via `gh pr comment`; no extra secrets to configure). No `OPENAI_API_KEY` is needed — the workflow only runs the offline bisection, not `--analyze`/`--verify`.

**What it does:**
1. Checks out full history and installs Sentinel Bisect (`pip install -e .`).
2. Runs `sentinel-bisect --good <good> --bad <bad> --command <command>`.
3. Uploads `sentinel-report.md` and `sentinel-trace.json` as a workflow artifact (the full report; `--serve`'s HTML timeline isn't started in CI since there's no long-lived server in a GitHub Actions job — the JSON trace is uploaded instead so it can be inspected or rendered locally with `--serve`).
4. Runs [`scripts/post_pr_comment.py`](scripts/post_pr_comment.py), which reads the trace and posts a short summary — the introducing commit, one line of counts (flaky/substituted decision points), and a link to the workflow run/artifact — as a PR comment via the `gh` CLI (preinstalled on GitHub-hosted runners, so no third-party comment-posting Action is needed).

**Current limitations:** manual dispatch only (no automatic trigger on CI failure); posts to whatever `pr_number` you provide (not derived from the run); does not run `--analyze`/`--verify`, so the comment never includes a proposed patch.

## Architecture

- `intake/`: turns a bug report into a command and revision intent; GPT-5.6 is optional with an offline heuristic fallback.
- `orchestrator/`: creates disposable Git worktrees, performs repeated command trials, and writes a JSON trace.
- `analysis/`: supplies the confirmed diff and failure output to GPT-5.6 for a mechanism explanation and unified patch, escalating reasoning effort on verification failure (see below).
- `verify/`: applies the suggested patch in the temporary worktree and runs every configured target, smoke, and invariant gate, recording each result.
- `report/`: creates a Markdown report and an HTML timeline visualization with a demo-friendly search timeline, and (via `--serve`) a small FastAPI server that serves them over HTTP.

### GPT-5.6 model configuration

- **Model tiers:** `intake/` calls `gpt-5.6-luna` at `reasoning.effort: low` — a bounded structured-extraction task. `analysis/` calls `gpt-5.6-sol` starting at `effort: high`. Both are configurable via `--intake-model`/`--analysis-model` (or the `SENTINEL_INTAKE_MODEL`/`SENTINEL_ANALYSIS_MODEL` env vars).
- **Reasoning-effort escalation:** when both `--analyze` and `--verify` are given, a failed verification (patch didn't apply, or the target/smoke command still fails) escalates `analysis/` to the next tier — `effort: high` -> `effort: xhigh` -> `reasoning.mode: pro` — and retries, informed by the prior attempt's response id and failure reason (`previous_response_id` + `reasoning.context: all_turns`). Only after every tier is exhausted is an unverified/failed result reported; the tier ladder is capped with `--max-analysis-tier`, and every attempt is visible in the JSON trace and the Markdown/HTML report, the same way rerun-count escalation already is. This mirrors the orchestrator's own escalation philosophy (3 -> 7 -> 15 reruns) applied to model quality instead of test reruns.
- **Explicit prompt caching:** both calls set `prompt_cache_options: {mode: "explicit", ttl: "1h"}` on their stable `instructions` field (never on the per-run diff/bug-report text). A ~1h TTL fits repeated demo/judging runs in one sitting. Pass `--debug` to log `cached_tokens`/`cache_write_tokens` from each response.
- **Programmatic Tool Calling (PTC):** evaluated, not used. `--analyze` is a single high-stakes call whose output is applied by `verify/` only after passing verification, and each result can change what happens next (whether to escalate to the next tier) — both cases where GPT-5.6's own guidance favors direct tool calling over PTC's bounded, no-judgment-needed workflow shape.

## Built with Codex and Claude Code

**Codex** accelerated the project scaffold, test fixture generator, typed module boundaries, CLI wiring, and unit tests. The core confidence policy and small demo history were deliberately hand-tuned for easy explanation in a three-minute walkthrough.

**Claude Code** hardened and extended the implementation with cross-platform setup documentation, OPENAI_API_KEY error handling with clear messages, the escalation tiers and adaptive rerun schedule, flaky-commit routing via substitution, the self-contained HTML timeline visualization served over HTTP, minimal GitHub Actions CI integration, comprehensive edge-case handling (no regression, flaky baseline, command failures, empty ranges), and the GPT-5.6 feature batch described above: model-tier routing (`gpt-5.6-luna`/`gpt-5.6-sol`), reasoning-effort quality escalation on verification failure, persisted reasoning across escalation retries via `previous_response_id`, and explicit prompt caching.

GPT-5.6 is reserved for two judgment-heavy tasks: extracting structured reproduction intent from raw reports, and interpreting a *confirmed* diff plus failure output into an explanation and minimal patch. It does not make bisection decisions.

## Edge cases

Before searching, Sentinel verifies the range boundaries (the good commit must consistently pass, the bad commit must consistently fail) so it never returns a misleading culprit or crashes on input that doesn't actually describe a regression. Expected behavior when a judge tests with their own input:

- **No regression in the range** (the bad commit passes, same as good): reports "No regression found in the given range" and exits non-zero — it does not invent a culprit.
- **Flaky baseline** (the good/starting commit is itself flaky): reports "Cannot establish a reliable baseline: the good baseline … is flaky" rather than searching from an untrustworthy anchor. A flaky bad commit is reported the same way.
- **Good baseline already fails** (regression predates the range, or a misconfigured command): reports that the good baseline already fails and suggests picking an earlier good commit or checking the command.
- **Reproduction command can't run** (typo'd command / not found, exit code 126–127 at the first commit checked): reports "The reproduction command failed to run … (e.g. command not found)", distinguishing a command/environment problem from a genuine test failure. (A command that runs but errors for another reason — e.g. a wrong test *path* returning a non-127 code — surfaces as the "good baseline already fails" message above.)
- **Single-commit range** (good and bad adjacent): handled as a valid trivial case — the one commit is the culprit, and its pass/fail anchors are actually verified, with no off-by-one crash. **Empty range** (good and bad are the same commit or reversed) is reported as "the range is empty" rather than a stack trace.

## Known limitations

- Flaky detection uses an adaptive rerun schedule, not a formal statistical model: a candidate is classified as soon as one tier's batch of runs is unanimous (all pass or all fail), escalating to a larger, independent batch only when a tier is mixed. The schedule defaults to `3,7,15` and is configurable via `--rerun-schedule`; `--runs N` remains available as shorthand for a fixed, non-escalating single-tier schedule.
- A persistently flaky midpoint does not stop the search: Sentinel first escalates its rerun count, and if the signal still will not resolve it routes around the commit by substituting an adjacent commit as the decision point (recorded in the trace as `substitute_for`). The search only halts for human guidance in the rare case where every commit in the remaining range is persistently flaky.
- The fixture demonstrates Python/pytest; test commands themselves are shell commands and can target other stacks.
- Patch generation needs an OpenAI API key and can decline to produce a safe patch.
- Dependency and cross-repository bisection are intentionally outside this MVP.

## License

MIT — see [LICENSE](LICENSE).
