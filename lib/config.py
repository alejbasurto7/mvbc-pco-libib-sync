"""Configuration loaded from environment variables.

For local dev, python-dotenv loads .env automatically when imported.
For GitHub Actions, env vars are set by the workflow from secrets.
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv may not be installed in CI for unit tests
    pass


REQUIRED = [
    "PCO_APP_ID",
    "PCO_SECRET",
    "LIBIB_API_KEY",
    "LIBIB_API_USER",
    "RESEND_API_KEY",
    "EMAIL_FROM",
    "LIBIB_LOGIN_URL",
]


@dataclass(frozen=True)
class Config:
    pco_app_id: str
    pco_secret: str
    libib_api_key: str
    libib_api_user: str
    resend_api_key: str
    email_from: str
    email_reply_to: str | None
    email_backend: str
    libib_login_url: str
    stability_hours: float
    baseline_mode: bool


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            f"For local dev, copy .env.example to .env and fill in values."
        )
    return Config(
        pco_app_id=os.environ["PCO_APP_ID"],
        pco_secret=os.environ["PCO_SECRET"],
        libib_api_key=os.environ["LIBIB_API_KEY"],
        libib_api_user=os.environ["LIBIB_API_USER"],
        resend_api_key=os.environ["RESEND_API_KEY"],
        email_from=os.environ["EMAIL_FROM"],
        email_reply_to=os.environ.get("EMAIL_REPLY_TO") or None,
        email_backend=os.environ.get("EMAIL_BACKEND", "resend"),
        libib_login_url=os.environ["LIBIB_LOGIN_URL"],
        stability_hours=float(os.environ.get("STABILITY_HOURS", "24")),
        baseline_mode=_truthy(os.environ.get("BASELINE_MODE")),
    )
