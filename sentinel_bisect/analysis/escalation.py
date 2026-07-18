from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sentinel_bisect.analysis.mock import mock_analyze_culprit
from sentinel_bisect.analysis.service import DEFAULT_ANALYSIS_MODEL, AnalysisResult, analyze_culprit
from sentinel_bisect.orchestrator.git import disposable_worktree
from sentinel_bisect.verify.service import VerificationResult, verify_patch


@dataclass(frozen=True)
class Tier:
    name: str
    model: str
    effort: str | None = None
    mode: str | None = None


# Same philosophy as the orchestrator's rerun-count escalation (3 -> 7 -> 15): start
# at a reasonable default and only spend more (here, reasoning effort) when the
# result wasn't good enough, rather than maxing out settings on every call.
DEFAULT_TIERS: tuple[Tier, ...] = (
    Tier("tier1", DEFAULT_ANALYSIS_MODEL, effort="high"),
    Tier("tier2", DEFAULT_ANALYSIS_MODEL, effort="xhigh"),
    Tier("tier3", DEFAULT_ANALYSIS_MODEL, mode="pro"),
)


@dataclass(frozen=True)
class EscalationAttempt:
    tier: str
    model: str
    effort: str | None
    mode: str | None
    analysis: AnalysisResult
    verification: VerificationResult | None
    informed_by: str | None = None

    @property
    def verified(self) -> bool:
        return self.verification is not None and self.verification.verified

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "tier": self.tier,
            "analysis_provider": self.analysis.provider,
            "model": self.model,
            "effort": self.effort,
            "mode": self.mode,
            "response_id": self.analysis.response_id,
            "explanation": self.analysis.explanation,
            "has_patch": bool(self.analysis.patch),
            "verified": self.verified,
            "verification_message": self.verification.message if self.verification else None,
            "verification_gates": self.verification.gates_dict() if self.verification else [],
            "informed_by": self.informed_by,
        }
        if self.analysis.cost_estimate:
            result.update(self.analysis.cost_estimate.to_dict())
        return result


@dataclass(frozen=True)
class EscalationOutcome:
    attempts: list[EscalationAttempt]

    @property
    def analysis_provider(self) -> str:
        return self.final.analysis.provider

    @property
    def final(self) -> EscalationAttempt:
        return self.attempts[-1]

    @property
    def verified(self) -> bool:
        return self.final.verified

    @property
    def exhausted(self) -> bool:
        """True only when every usable tier was tried and none verified — the honest
        failure state the escalation ladder must report rather than crash on or
        silently accept a bad patch for."""
        return not self.verified

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "analysis_provider": self.analysis_provider,
            "attempts": [a.to_dict() for a in self.attempts],
            "verified_tier": self.final.tier if self.verified else None,
            "exhausted": self.exhausted,
        }
        estimates = [a.analysis.cost_estimate for a in self.attempts if a.analysis.cost_estimate]
        if estimates:
            # Every populated estimate comes from the same disclosed mock pricing
            # model, so summing preserves its estimate-only status.
            from sentinel_bisect.analysis.costs import COST_ESTIMATE_DISCLOSURE, GPT_56_SOL_PRICING_SOURCE
            result.update({
                "estimated_total_cost_usd": sum(estimate.estimated_cost_usd for estimate in estimates),
                "estimated_cost_disclosure": COST_ESTIMATE_DISCLOSURE,
                "pricing_source": GPT_56_SOL_PRICING_SOURCE,
            })
        return result


def run_escalation(
    repo: Path,
    culprit: str,
    failing_output: str,
    command: str,
    runs: int,
    smoke_command: str | None = None,
    invariant_command: str | None = None,
    tiers: Sequence[Tier] = DEFAULT_TIERS,
    max_tier: int | None = None,
    mock_analysis: bool = False,
) -> EscalationOutcome:
    """Run analysis -> verify, escalating the reasoning-effort tier whenever
    verification fails (didn't apply, or applied but a target/smoke/invariant command
    fails). Each retry is informed by the prior tier's response id and failure reason
    (see analysis/service.py's `previous_response_id`/`retry_context`). Stops at the
    first tier whose patch verifies; only reports failure after every usable tier is
    exhausted.
    """
    if not tiers:
        raise ValueError("tiers must contain at least one tier")
    usable_tiers = tiers[:max_tier] if max_tier else tiers

    attempts: list[EscalationAttempt] = []
    previous_response_id: str | None = None
    retry_context: str | None = None

    for tier in usable_tiers:
        provider = mock_analyze_culprit if mock_analysis else analyze_culprit
        analysis = provider(
            repo,
            culprit,
            failing_output,
            model=tier.model,
            effort=tier.effort,
            mode=tier.mode,
            previous_response_id=previous_response_id,
            retry_context=retry_context,
        )
        verification: VerificationResult | None = None
        if analysis.patch:
            with disposable_worktree(repo, culprit) as worktree:
                verification = verify_patch(worktree, analysis.patch, command, runs, smoke_command, invariant_command)

        attempt = EscalationAttempt(
            tier=tier.name,
            model=tier.model,
            effort=tier.effort,
            mode=tier.mode,
            analysis=analysis,
            verification=verification,
            informed_by=retry_context,
        )
        attempts.append(attempt)

        if attempt.verified:
            return EscalationOutcome(attempts)

        previous_response_id = analysis.response_id
        if verification is not None:
            retry_context = verification.message
        elif not analysis.patch:
            retry_context = "no patch was proposed"
        else:
            retry_context = "patch could not be applied or verified"

    return EscalationOutcome(attempts)
