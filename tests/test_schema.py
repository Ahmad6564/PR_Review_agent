import pytest
from pydantic import ValidationError

from prlens.agent.schema import Finding, ReviewOutput


def _finding(**kw):
    base = dict(
        path="src/x.py",
        line=10,
        category="bug",
        severity="major",
        confidence=0.8,
        title="t",
        body="b",
        evidence="e",
    )
    base.update(kw)
    return Finding(**base)


def test_valid_finding():
    f = _finding()
    assert f.path == "src/x.py"


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        _finding(confidence=1.5)
    with pytest.raises(ValidationError):
        _finding(confidence=-0.1)


def test_invalid_category_rejected():
    with pytest.raises(ValidationError):
        _finding(category="vibes")


def test_rank_score_orders_by_severity_and_confidence():
    crit = _finding(severity="critical", confidence=0.9)
    minor = _finding(severity="minor", confidence=0.9)
    assert crit.rank_score() > minor.rank_score()


def test_review_output_defaults_empty():
    out = ReviewOutput()
    assert out.findings == [] and out.summary == ""
