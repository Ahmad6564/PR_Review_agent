"""Structured output schema for the review agent.

Structure is what makes everything downstream possible: filtering, scoring, dedupe
and evaluation all operate on ``Finding`` objects, never on free text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "bug",
    "security",
    "correctness",
    "performance",
    "maintainability",
    "style",
    "test",
]

Severity = Literal["critical", "major", "minor"]


class Finding(BaseModel):
    """A single reviewable claim about one added line of a diff."""

    path: str
    line: int = Field(description="Line number in the NEW file; must be an added line.")
    category: Category
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str = Field(max_length=80)
    body: str = Field(description="What's wrong and why it matters. 1-3 sentences.")
    suggestion: str | None = Field(
        default=None,
        description="Replacement code for a GitHub suggestion block, if a concrete fix exists.",
    )
    evidence: str = Field(
        description="What in the code or repo supports this claim.",
        default="",
    )

    # Not emitted by the model — filled in by the pipeline for tracing/debugging.
    source: str = Field(default="agent", exclude=False)

    def key(self) -> tuple[str, int]:
        """Stable identity for dedupe within a single run."""
        return (self.path, self.line)

    def rank_score(self) -> float:
        """Sort key for the hard cap: severity weight x confidence."""
        weight = {"critical": 3.0, "major": 2.0, "minor": 1.0}[self.severity]
        return weight * self.confidence


class ReviewOutput(BaseModel):
    """The agent's full output for a single hunk (or a whole-PR cross-cutting pass)."""

    findings: list[Finding] = Field(default_factory=list)
    summary: str = Field(default="", max_length=400)


class CriticVerdict(BaseModel):
    """Output of the adversarial critic pass (Phase 4.3)."""

    verdict: Literal["keep", "reject"]
    reason: str = Field(default="", max_length=200)
