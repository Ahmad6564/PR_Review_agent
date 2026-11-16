from prlens.config import build_config, load_repo_config


def test_defaults():
    cfg = build_config(repo_config_path="does-not-exist.yml")
    assert cfg.max_comments == 5
    assert cfg.min_confidence == 0.7
    assert "bug" in cfg.categories


def test_repo_config_overrides(tmp_path):
    p = tmp_path / ".prlens.yml"
    p.write_text(
        "max_comments: 2\nmin_confidence: 0.9\ncategories: [security]\n"
        "instructions: |\n  be strict\n",
        encoding="utf-8",
    )
    cfg = build_config(repo_config_path=str(p))
    assert cfg.max_comments == 2
    assert cfg.min_confidence == 0.9
    assert cfg.categories == ["security"]
    assert "be strict" in cfg.instructions


def test_env_toggle(monkeypatch):
    monkeypatch.setenv("PRLENS_CRITIC", "false")
    cfg = build_config(repo_config_path="none.yml")
    assert cfg.use_critic is False


def test_cli_overrides_win(tmp_path):
    p = tmp_path / ".prlens.yml"
    p.write_text("max_comments: 9\n", encoding="utf-8")
    cfg = build_config(repo_config_path=str(p), cli_overrides={"max_comments": 1})
    assert cfg.max_comments == 1


def test_load_repo_config_missing_returns_empty():
    assert load_repo_config("nope.yml") == {}
