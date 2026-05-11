import pytest

from lib.config import Config, load_config


def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("PCO_APP_ID", "app1")
    monkeypatch.setenv("PCO_SECRET", "sec1")
    monkeypatch.setenv("LIBIB_API_KEY", "lkey")
    monkeypatch.setenv("LIBIB_API_USER", "luser")
    monkeypatch.setenv("RESEND_API_KEY", "re_xxx")
    monkeypatch.setenv("EMAIL_FROM", "MVBC <a@b>")
    monkeypatch.setenv("LIBIB_LOGIN_URL", "https://x")

    cfg = load_config()
    assert cfg.pco_app_id == "app1"
    assert cfg.libib_api_key == "lkey"
    assert cfg.email_from == "MVBC <a@b>"
    assert cfg.stability_hours == 24.0  # default
    assert cfg.baseline_mode is False  # default
    assert cfg.email_backend == "resend"  # default


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


def _set_required(monkeypatch):
    for k in ["PCO_APP_ID", "PCO_SECRET", "LIBIB_API_KEY", "LIBIB_API_USER",
              "RESEND_API_KEY", "EMAIL_FROM", "LIBIB_LOGIN_URL"]:
        monkeypatch.setenv(k, "x")
