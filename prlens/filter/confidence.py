"""Stage 2 — confidence threshold.

Drop anything below the configured threshold (default 0.7). Self-reported confidence
is imperfect, but with the schema forcing a number and the prompt explaining the
consequence, it correlates well enough to be useful. The correlation is measured on
the benchmark (evaluation/eval_precision.py) and reported.
"""

from __future__ import annotations

from ..agent.schema import Finding


def filter_confidence(findings: list[Finding], threshold: float) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    kept, dropped = [], []
    for f in findings:
        if f.confidence >= threshold:
            kept.append(f)
        else:
            dropped.append((f, f"confidence {f.confidence:.2f} < {threshold:.2f}"))
    return kept, dropped
