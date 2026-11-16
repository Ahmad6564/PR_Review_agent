from prlens.agent.schema import Finding
from prlens.config import Config
from prlens.filter import categories, confidence, dedupe
from prlens.filter.pipeline import apply_cap, run_filter
from tests.helpers import make_mock_client


def _f(line=10, cat="bug", sev="major", conf=0.8, body="something is wrong here"):
    return Finding(
        path="src/x.py", line=line, category=cat, severity=sev,
        confidence=conf, title="t", body=body, evidence="e",
    )


def test_category_allowlist():
    kept, dropped = categories.filter_categories(
        [_f(cat="bug"), _f(cat="style")], ["bug", "security"]
    )
    assert len(kept) == 1 and kept[0].category == "bug"
    assert len(dropped) == 1


def test_confidence_threshold():
    kept, dropped = confidence.filter_confidence([_f(conf=0.9), _f(conf=0.5)], 0.7)
    assert len(kept) == 1 and kept[0].confidence == 0.9
    assert len(dropped) == 1


def test_dedupe_drops_already_posted():
    existing = [{"path": "src/x.py", "line": 10, "body": "something is wrong here"}]
    kept, dropped = dedupe.drop_already_posted([_f()], existing)
    assert kept == [] and len(dropped) == 1


def test_dedupe_collapse_repeats():
    findings = [_f(line=1), _f(line=2), _f(line=3)]
    kept, dropped = dedupe.collapse_repeats(findings)
    assert len(kept) == 1
    assert len(dropped) == 2


def test_apply_cap_keeps_top_n():
    findings = [
        _f(sev="minor", conf=0.7),
        _f(sev="critical", conf=0.9),
        _f(sev="major", conf=0.8),
    ]
    kept, suppressed = apply_cap(findings, 2)
    assert len(kept) == 2 and suppressed == 1
    assert kept[0].severity == "critical"  # highest rank first


def test_pipeline_runs_all_stages_with_critic():
    cfg = Config(min_confidence=0.7, max_comments=5)
    client = make_mock_client(critic_keep=True)
    findings = [_f(conf=0.9), _f(cat="style"), _f(conf=0.4)]
    result = run_filter(findings, cfg, client=client, hunk_text_for=lambda f: "code")
    # style dropped by category, 0.4 dropped by confidence, one survives critic.
    assert len(result.kept) == 1
    stages = {r.stage for r in result.rejections}
    assert "category" in stages and "confidence" in stages


def test_pipeline_critic_rejects_everything():
    cfg = Config(min_confidence=0.0, use_category_allowlist=False)
    client = make_mock_client(critic_keep=False)
    result = run_filter([_f(), _f(line=11)], cfg, client=client, hunk_text_for=lambda f: "c")
    assert result.kept == []
    assert all(r.stage == "critic" for r in result.rejections)


def test_toggles_disable_stages():
    cfg = Config(
        use_category_allowlist=False,
        use_confidence_threshold=False,
        use_critic=False,
        use_dedupe=False,
        use_cap=False,
    )
    findings = [_f(cat="style", conf=0.1)]
    result = run_filter(findings, cfg)
    assert len(result.kept) == 1  # nothing was filtered
