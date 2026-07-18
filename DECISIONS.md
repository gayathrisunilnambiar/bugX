# Decisions

- **Name:** Sentinel Bisect. It communicates a watchful debugging assistant while retaining the familiar bisection metaphor.
- **Git integration:** the tool uses `subprocess` and a disposable Git worktree. The user's checkout is never checked out, reset, or patched.
- **Confidence rule:** a commit is `pass` only when every attempt passes, `fail` only when every attempt fails, and `flaky` otherwise. Three attempts is the default for a quick, explainable MVP.
- **Flaky commits:** Sentinel retries an inconclusive midpoint once and never treats mixed outcomes as a trusted pass or fail.
- **Flaky midpoint follow-up:** after the configured retries remain mixed, Sentinel labels that revision `untrusted_flaky` and probes its immediately newer neighbor. Only that neighbor's stable result may advance a boundary; a flaky neighbor still stops the search. This makes the skipped evidence explicit in both JSON and Markdown rather than turning a mixed result into a pass or fail.
- **LLM fallback:** API-backed intake and analysis are optional; deterministic heuristics keep the fixture demo usable without credentials.

## GPT-5.6 upgrade batch (Session A: model routing, escalation, persisted reasoning)

- **Model tiers:** `intake/` uses `gpt-5.6-luna` at `reasoning.effort: low` — a bounded
  structured-extraction task doesn't need deep judgment. `analysis/` uses
  `gpt-5.6-sol`, starting at `effort: high` as tier 1 of the escalation ladder below.
  Both are configurable via `SENTINEL_INTAKE_MODEL`/`SENTINEL_INTAKE_EFFORT` env vars
  and `--intake-model`/`--analysis-model` CLI flags, mirroring the orchestrator's
  existing philosophy of escalating quality/effort rather than maxing out settings
  everywhere (`--rerun-schedule`'s 3 -> 7 -> 15).
- **Escalation ladder** (`analysis/escalation.py`): tier1 `gpt-5.6-sol`/`high` ->
  tier2 `gpt-5.6-sol`/`xhigh` -> tier3 `gpt-5.6-sol`/`mode: pro`. Only triggers when
  both `--analyze` and `--verify` are given — `--analyze` alone has no verification
  signal to escalate on, so it stays a single tier-1 call. Each attempt gets a fresh
  disposable worktree (patch state from a failed `git apply` can't be reused).
  Exhaustion is reported honestly (`EscalationOutcome.exhausted=True`, the last
  failed attempt still surfaced) rather than raising or silently accepting a bad
  patch. `--max-analysis-tier` caps the ladder for cost control.
- **Trace/report visibility:** `BisectEngine` already writes the JSON trace before
  analysis runs, so `cli.py`'s `_augment_trace_with_analysis` re-reads and rewrites it
  with an `"analysis"` key once escalation finishes, mirroring the existing
  rerun-escalation shape. `report/renderer.py` adds an "## Analysis escalation"
  section (only when more than one tier ran) and `report/timeline.py` renders a tier
  badge row reusing the existing `.tier`/`.tier-pass`/`.tier-fail` CSS classes used
  for rerun-count escalation, so the same visual language covers both kinds of
  escalation.
- **Persisted reasoning:** retries pass `previous_response_id` (the prior tier's
  `response.id`) plus `reasoning.context: all_turns`, and send only the verification
  failure text as new input rather than resending the full diff — the prior response
  already has it server-side. **Zero Data Retention:** nothing in this project
  currently sets `store: false` or configures ZDR for the OpenAI org it runs under.
  Per instruction to flag rather than assume, this implementation relies on default
  `store: true` behavior for `previous_response_id` to work; the encrypted-
  reasoning-item replay pattern was **not** implemented. If ZDR is ever enabled here,
  this needs revisiting.
- **Hard-regression fixture** (`fixtures/build_hard_fixture.py` ->
  `fixtures/hard-regression-demo/`): the original fixture's regression (`parts[0]`
  instead of `sum(parts)`) is directly visible in its failing output, so a first-pass
  patch is plausibly always correct — tier 1 might never fail, making the escalation
  ladder undemonstrable live (the same class of problem the `--runs 3` default had
  before it became adaptive). The hard fixture's regression instead breaks a *shared*
  helper (`_parse_values`) used by two functions; the declared reproduction target
  (`test_parse_total`) only exercises one of them, while `--smoke-command
  "pytest -q tests/test_calculator.py::test_parse_average"` exercises the other. A
  patch that special-cases the symptom shown in the failing output (rather than
  fixing the shared helper the diff actually shows is broken) still fails the smoke
  command — verified manually by applying exactly that shortcut patch in a worktree
  (see the session transcript): `test_parse_total` passes, `test_parse_average`
  still fails with `assert 3.0 == 4`. This is a genuine harder-to-fully-patch bug,
  not a rigged failure. **What is not confirmed:** whether the real `gpt-5.6-sol`
  model at `effort: high` actually takes that shortcut — that requires a live
  `OPENAI_API_KEY`, which was not available in this session. Running
  `sentinel-bisect --repo fixtures/hard-regression-demo --command "pytest -q
  tests/test_calculator.py::test_parse_total" --smoke-command "pytest -q
  tests/test_calculator.py::test_parse_average" --analyze --verify` with a real key
  is the way to observe this live.

## GPT-5.6 upgrade batch (Session B: prompt leanness, verbosity, caching, PTC)

## Hard-regression three-gate verification (Session C)

- **Invariant gate:** `--invariant-command` is a third independently required
  verification command. `verify/` always runs every configured target, smoke, and
  invariant gate after applying a patch, so one failure cannot hide another. The
  JSON trace includes each gate's command, classification, and pass/fail result;
  Markdown and the HTML timeline surface the same per-gate status. Any failed gate
  feeds the existing reasoning-effort escalation flow.
- **Domain basis:** the hard fixture's `test_invariants.py` parameterizes all
  integer sequences of lengths 1 through 4 over `-2..2` (780 cases), formatting
  each as a whitespace-padded comma-separated string. Its property is that the
  shared `_parse_values` helper preserves every valid segment in order. This is the
  helper's contract, not a list reverse-engineered from model behavior.
- **Controls:** `tests/test_hard_regression_invariant.py` hand-constructs two
  flawed patches: wrapper hardcodes for the target/smoke examples, and a
  `parts[:3]` repair. Both pass target and smoke but fail the invariant specifically.
  The root-cause repair (`parts` rather than `parts[:-1]`) passes all three. These
  controls prove stricter verification without making the fixture unsatisfiable.

- **Prompt restructuring:** both `intake/service.py` and `analysis/service.py` moved
  from one concatenated `input` string to a stable `instructions` field (the
  cacheable prefix, see Phase 6 below) plus a variable `input` (the actual bug
  report / diff / retry context). Intake's instruction text: 164 -> 151 chars (25 ->
  23 words). Analysis's is the more meaningful case: the "return JSON only:
  explanation + patch" contract was previously stated twice — once in the base-call
  prompt (161 chars) and again, slightly reworded, in every escalation retry (128
  chars each) — now stated once as a 144-char `instructions` string shared
  identically by the base call and every retry tier. Counts are plain
  chars/words, not a tokenizer count — precise enough to show the duplication was
  removed, which is what this phase asked for.
- **Tools:** confirmed neither call exposes any tools/function-calling (`grep`
  turned up no `tools=`/`tool_choice` anywhere in `sentinel_bisect/`) — both are
  pure JSON-extraction calls that never need to act directly, so there was nothing
  to trim here, and none were added.
- **Quality re-verification:** re-ran `test_intake.py`/`test_analysis.py`/
  `test_escalation.py` after trimming — all still pass, confirming the JSON-shape
  contract the code parses is unchanged. This is a structural check only; there is
  no live `OPENAI_API_KEY` in this environment, so an actual output-quality
  comparison against the real model was not possible and is not claimed.
- **Verbosity:** the base analysis call sets `text: {verbosity: "medium"}`, sized
  for the full Markdown report / HTML timeline. `scripts/post_pr_comment.py`
  derives its PR-comment summary by truncating the existing explanation (first
  sentence, capped length) instead of making a second API call — cheaper,
  deterministic, and avoids a second round-trip's latency just to shorten text
  that's already in hand.
- **Explicit caching:** `prompt_cache_options: {mode: "explicit", ttl: "1h"}` is
  set alongside `instructions` on both calls. A ~1h TTL comfortably covers repeated
  demo/judging runs within a sitting without holding a cache indefinitely.
  `cached_tokens`/`cache_write_tokens` are logged when `--debug` is passed.
- **PTC (Programmatic Tool Calling):** evaluated, not implemented. `--analyze` is a
  single high-stakes call whose result is applied by `verify/` only after passing
  verification — each result can change what happens next (whether to escalate to
  the next reasoning-effort tier). Both are cases where direct tool calling (what
  this project already does) fits better than PTC's bounded, no-judgment-needed
  workflow shape.
