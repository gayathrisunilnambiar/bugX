# Claude Code Prompts — GPT-5.6 Feature Upgrade Batch

Two sessions. Run Session A first, review the diff carefully (it changes
control flow), confirm tests pass, then run Session B.

---

# SESSION A: Functional core (model routing, escalation, persisted reasoning)

**Model: `claude-opus-4-8`**

```
Context: Sentinel Bisect currently uses GPT-5.6 in two places: intake/
(parses a natural-language bug report into a structured command +
revision-range intent) and analysis/ (given a confirmed guilty commit's
diff and failure output, produces a causal explanation and a proposed
unified-diff patch, which verify/ then applies in a disposable worktree
and re-tests).

The core bisection/orchestration logic is intentionally deterministic and
LLM-free — do not change that. This task only touches how GPT-5.6 is
invoked and configured within intake/ and analysis/.

The system already has a working design pattern to recognize and reuse:
adaptive escalation. The orchestrator escalates test rerun counts (3 -> 7
-> 15) when results are ambiguous, and routes around a commit that never
resolves. This task extends that same philosophy to GPT-5.6 usage —
escalate model quality/effort when initial output isn't good enough,
rather than using maximum settings everywhere or a single fixed setting.

Work through these phases in order. Leave the system working and tested
after each phase before moving to the next.

PHASE 1 — Model-tier routing:
- intake/: use gpt-5.6-luna at reasoning.effort: low (bounded structured
  parsing task, doesn't need deep judgment; move to medium only if low
  proves unreliable in testing).
- analysis/: use gpt-5.6-sol at reasoning.effort: high as the starting
  tier (this becomes tier 1 of the Phase 2 escalation ladder).
- Make model + effort configurable via env vars or CLI flags
  (--intake-model, --analysis-model) with the above as defaults.
- Use the Responses API for both (required for later phases).
- Add/update unit tests confirming correct model + effort per call site,
  using a mocked API client — no real API calls in unit tests.

PHASE 2 — Reasoning-effort escalation on verification failure (the most
important change in this batch, implement carefully):
- Define an escalation ladder, configurable:
  Tier 1: gpt-5.6-sol, reasoning.effort: high (the Phase 1 base call).
  Tier 2: gpt-5.6-sol, reasoning.effort: xhigh.
  Tier 3: gpt-5.6-sol, reasoning.mode: pro.
- Wire into the analyze -> verify flow: if verify/ reports the proposed
  patch failed (didn't apply, or applied but the target test still
  fails), escalate to the next tier and re-run analysis/ for a new
  proposed patch, then re-verify. Only report an unverified/failed state
  after exhausting all tiers.
- Log which tier succeeded (or that all tiers were exhausted) in the JSON
  trace and Markdown/HTML report, the same way orchestrator escalation
  events are logged — must be visible in output, not just internal.
- Add a CLI flag to cap max tier used (e.g. --max-analysis-tier 2),
  defaulting to allowing all tiers.
- Add unit tests: tier-1 success, escalation to tier 2 required,
  escalation to tier 3 required, and full exhaustion correctly reported
  as an honest failure (not a crash, not a silently-accepted bad patch).

PHASE 2.5 — Prove escalation actually triggers in the real demo:
- Check whether the current fixture's staged regression is patchable on
  the first analysis attempt every time. If tier 1 always succeeds,
  multi-tier escalation can never be demonstrated live, which is the
  same "flagship feature never shown" problem already caught once before
  with the --runs 3 default.
- If needed, add a second fixture scenario (e.g.
  fixtures/hard-regression-demo/, built the same reproducible way as the
  existing fixture) with a regression subtle/ambiguous enough that tier 1
  plausibly fails verification and escalation is required to resolve it.
  Do not rig this dishonestly (e.g. artificially failing tier 1
  regardless of quality) — construct a genuinely harder bug so escalation
  is a real, demonstrable outcome, not theater.
- Document in DECISIONS.md whether this was needed and what was built.

PHASE 3 — Persisted reasoning across the escalation retry:
- On the first analysis call (tier 1), capture the response ID.
- On escalation, set reasoning.context: all_turns and pass
  previous_response_id referencing the prior tier's response, including
  the verification failure output as new input — so the retry is
  explicitly informed by what was already tried and why it failed.
- If the project uses store: false or Zero Data Retention, implement the
  encrypted-reasoning-item replay pattern instead of relying on
  previous_response_id alone. If current configuration is unclear, flag
  this rather than assuming.
- Add a test (mocked API client) confirming an escalation call includes
  the correct previous_response_id and prior-failure context.
- Confirm via trace/report output that a human reading it can see this
  happened (e.g. "tier 2 attempt, informed by tier 1 failure: <reason>").

After Phase 3: run the full test suite fresh, unfiltered. Run the real
end-to-end demo (adaptive, non-pinned --runs version) and, if Phase 2.5
built a harder fixture, run against that too and confirm escalation is
visibly triggered and logged. Report actual results, not assumptions.
```

---

# SESSION B: Prompt leanness, verbosity, caching, PTC decision, docs

**Model: `claude-sonnet-5`**

```
This follows a prior session that implemented model-tier routing
(gpt-5.6-luna for intake/, gpt-5.6-sol for analysis/), a reasoning-effort
escalation ladder in analysis/ (high -> xhigh -> pro mode) triggered on
verification failure, and persisted reasoning across escalation retries
via previous_response_id. Confirm you understand the current state of
intake/ and analysis/ before proceeding — read both modules fully first.

PHASE 4 — Audit and trim system prompts for leanness:
- In intake/ and analysis/ system prompts, remove any instruction stated
  more than once.
- Confirm only tools actually needed for that specific call are exposed,
  with concise precise descriptions — not a shared tool list across
  intake and analysis if their needs differ.
- Keep an example or style guidance only if it encodes an actual product
  requirement or corrects a previously-measured failure mode; remove
  generic/decorative examples.
- Re-run the existing analysis/intake test suite after trimming to
  confirm output quality/structure is unchanged. If any test regresses,
  restore only the specific instruction that mattered.
- Record before/after token counts for both system prompts in
  DECISIONS.md.

PHASE 5 — Context-appropriate text.verbosity:
- Set text.verbosity explicitly per output context instead of relying on
  default behavior. Base analysis call: verbosity appropriate for the
  full report/HTML timeline (likely medium).
- For the PR-comment formatter (scripts/post_pr_comment.py or
  equivalent), decide whether to request a separate low-verbosity
  summary call or derive a trimmed version from the base explanation via
  simple truncation/summary logic — pick one, note the reasoning in
  DECISIONS.md.
- Spot check all four output contexts (stdout, report file, HTML
  timeline, PR comment) for appropriately sized explanations.

PHASE 6 — Explicit prompt caching for repeated system prompts:
- Add explicit cache breakpoints (prompt_cache_options.mode: "explicit")
  for the stable system-prompt prefix in intake/ and analysis/ calls,
  keeping per-run variable content (the actual bug report text, the
  actual diff) out of the cached prefix.
- Set an appropriate prompt_cache_options.ttl (not the older
  prompt_cache_retention parameter) — reasonable for repeated demo runs
  within roughly an hour, not indefinite.
- Log/expose cached_tokens and cache_write_tokens from API responses in
  verbose/debug CLI output so cache effectiveness is observable.
- Add a brief README note on why explicit caching is used here.

PHASE 7 — Document the Programmatic Tool Calling decision:
- Do not implement PTC. Add a short factual subsection to README.md
  (near "Built with Codex and Claude Code" or in Architecture) stating
  PTC was evaluated and intentionally not used: the analysis step is a
  single high-stakes call requiring verification approval before
  anything is applied, and each result (proposed patch) can change what
  happens next (whether escalation is needed) — both cases where GPT-5.6's
  own documentation favors direct tool calling over PTC's bounded,
  no-judgment-needed workflow shape. Keep it to a few sentences.

FINAL INTEGRATION PASS:
1. Run the full test suite fresh, once, unfiltered.
2. Re-run the real end-to-end demo and confirm the guilty commit result
   and escalation-tier logging are still correct after Phases 4-6's
   prompt/config changes.
3. Update the "Built with Codex and Claude Code" README section to
   specifically mention this GPT-5.6 feature batch (model-tier routing,
   quality escalation, persisted reasoning, prompt caching) — be
   specific, not just "we use GPT-5.6 for analysis," since this is
   directly relevant to the submission's "how GPT-5.6 was used"
   requirement.
4. Confirm DECISIONS.md is up to date with every judgment call made
   across both sessions.
```
