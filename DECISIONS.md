# Decisions

- **Name:** Sentinel Bisect. It communicates a watchful debugging assistant while retaining the familiar bisection metaphor.
- **Git integration:** the tool uses `subprocess` and a disposable Git worktree. The user's checkout is never checked out, reset, or patched.
- **Confidence rule:** a commit is `pass` only when every attempt passes, `fail` only when every attempt fails, and `flaky` otherwise. Three attempts is the default for a quick, explainable MVP.
- **Flaky commits:** Sentinel retries an inconclusive midpoint once and never treats mixed outcomes as a trusted pass or fail.
- **Flaky midpoint follow-up:** after the configured retries remain mixed, Sentinel labels that revision `untrusted_flaky` and probes its immediately newer neighbor. Only that neighbor's stable result may advance a boundary; a flaky neighbor still stops the search. This makes the skipped evidence explicit in both JSON and Markdown rather than turning a mixed result into a pass or fail.
- **LLM fallback:** API-backed intake and analysis are optional; deterministic heuristics keep the fixture demo usable without credentials.
