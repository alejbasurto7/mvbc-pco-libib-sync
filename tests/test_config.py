import pytest

from lib.config import Config, load_config


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("PCO_APP_ID", "app1")
    monkeypatch.setenv("PCO_SECRET", "sec1")
    monkeypatch.setenv("LIBIB_API_KEY", "lkey")
    monkeypatch.setenv("LIBIB_API_USER", "luser")
    monkeypatch.setenv("GMAIL_USER", "alex@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")
    monkeypatch.setenv("EMAIL_FROM", "MVBC Library <alex@gmail.com>")
    monkeypatch.setenv("LIBIB_LOGIN_URL", "https://x")

    cfg = load_config()
    assert cfg.pco_app_id == "app1"
    assert cfg.libib_api_key == "lkey"
    assert cfg.gmail_user == "alex@gmail.com"
    assert cfg.gmail_app_password == "abcdefghijklmnop"
    assert cfg.email_from == "MVBC Library <alex@gmail.com>"
    assert cfg.stability_hours == 24.0  # default
    assert cfg.baseline_mode is False  # default
    assert cfg.email_backend == "gmail"  # default


def test_email_from_defaults_to_gmail_user(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    cfg = load_config()
    assert cfg.email_from == cfg.gmail_user


def test_stability_hours_parses_float(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("STABILITY_HOURS", "0.05")
    cfg = load_config()
    assert cfg.stability_hours == 0.05


def test_baseline_mode_parses_truthy(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("BASELINE_MODE", "true")
    assert load_config().baseline_mode is True
    monkeypatch.setenv("BASELINE_MODE", "True")
    assert load_config().baseline_mode is True
    monkeypatch.setenv("BASELINE_MODE", "1")
    assert load_config().baseline_mode is True
    monkeypatch.setenv("BASELINE_MODE", "false")
    assert load_config().baseline_mode is False


def test_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("PCO_APP_ID", raising=False)
    with pytest.raises(RuntimeError, match="PCO_APP_ID"):
        load_config()


def test_missing_gmail_user_raises(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("GMAIL_USER", raising=False)
    with pytest.raises(RuntimeError, match="GMAIL_USER"):
        load_config()


def test_missing_gmail_app_password_raises(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="GMAIL_APP_PASSWORD"):
        load_config()


def test_protected_tags_default_to_ssm(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("PROTECTED_TAGS", raising=False)
    cfg = load_config()
    assert cfg.protected_tags == ("ssm",)


def test_protected_tags_parses_comma_separated(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("PROTECTED_TAGS", "ssm, staff , vip")
    cfg = load_config()
    assert cfg.protected_tags == ("ssm", "staff", "vip")


def test_protected_tags_empty_yields_empty_tuple(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("PROTECTED_TAGS", "")
    cfg = load_config()
    assert cfg.protected_tags == ()


def _set_required(monkeypatch):
    for k, v in [
        ("PCO_APP_ID", "x"),
        ("PCO_SECRET", "x"),
        ("LIBIB_API_KEY", "x"),
        ("LIBIB_API_USER", "x"),
        ("GMAIL_USER", "alex@gmail.com"),
        ("GMAIL_APP_PASSWORD", "abcdefghijklmnop"),
        ("LIBIB_LOGIN_URL", "x"),
    ]:
        monkeypatch.setenv(k, v)
