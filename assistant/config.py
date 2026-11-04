"""Runtime settings, read from the environment.

Secrets (``ROUTES_API_KEY``, ``TOKEN_511``, ``TICKETMASTER_KEY``,
``ANTHROPIC_API_KEY``) come from Secret Manager via Cloud Run env bindings;
they are excluded from ``repr`` so a logged ``Settings`` never leaks them.

``LLM_PROVIDER`` picks the model behind the two calls: ``anthropic`` (Claude on
the Anthropic API, with ``ANTHROPIC_MODEL`` and ``ANTHROPIC_API_KEY``) or
``gemini`` (Gemini on Vertex AI with ``GEMINI_MODEL``, reached with the service
account, so there is no Gemini key). Unset means ``gemini``, so a revision that
predates the switch keeps starting as it did; setting the variable is both the
switch and the rollback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DISPLAY_TZ = "America/Los_Angeles"

PROVIDERS = ("anthropic", "gemini")
DEFAULT_PROVIDER = "gemini"


@dataclass(frozen=True)
class Settings:
    GEMINI_MODEL: str = ""
    LLM_PROVIDER: str = DEFAULT_PROVIDER
    ANTHROPIC_MODEL: str = ""
    ANTHROPIC_API_KEY: str = field(default="", repr=False)
    GCP_PROJECT: str = ""
    VERTEX_REGION: str = "us-west1"
    ROUTES_API_KEY: str = field(default="", repr=False)
    TOKEN_511: str = field(default="", repr=False)
    TICKETMASTER_KEY: str | None = field(default=None, repr=False)
    TOOL_TIMEOUT_S: float = 1.5
    EXPLAIN_TIMEOUT_S: float = 4.0
    # LLM call 1. 4 s, not 2.5: the first extract on a fresh instance took longer than 2.5 s
    # (connection, auth and model warm-up), which sent the rider the form.
    EXTRACT_TIMEOUT_S: float = 4.0
    RATE_LIMIT_PER_HOUR: int = 10
    MAX_MESSAGE_CHARS: int = 500
    # Fixed, not read from the environment: the process-wide TZ variable is
    # often "UTC" in containers, and user-facing times must be Pacific.
    TZ: str = DISPLAY_TZ

    @property
    def active_model(self) -> str:
        """The model id the two calls go to, for ``/health`` and the logs."""
        return self.ANTHROPIC_MODEL if self.LLM_PROVIDER == "anthropic" else self.GEMINI_MODEL


def _required(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set; {hint} (there is deliberately no default)")
    return value


def load_settings() -> Settings:
    """Build ``Settings`` from the environment.

    Raises ``RuntimeError`` when ``LLM_PROVIDER`` is not one of ``PROVIDERS``,
    or when the active provider's required values are unset or blank:
    ``GEMINI_MODEL`` for gemini, ``ANTHROPIC_MODEL`` and ``ANTHROPIC_API_KEY``
    for anthropic. Model ids have no default, so a deploy that forgot one fails
    at startup, not at the first question. Values are never echoed.
    """
    env = os.environ
    provider = env.get("LLM_PROVIDER", "").strip().lower() or DEFAULT_PROVIDER
    if provider not in PROVIDERS:
        raise RuntimeError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}")
    if provider == "gemini":
        gemini_model = _required("GEMINI_MODEL", "set it to a Flash-tier model id available in Vertex AI")
        anthropic_model = env.get("ANTHROPIC_MODEL", "").strip()
        anthropic_key = ""
    else:
        gemini_model = env.get("GEMINI_MODEL", "").strip()
        anthropic_model = _required("ANTHROPIC_MODEL", "set it to a Claude model id such as claude-haiku-5-5")
        anthropic_key = _required("ANTHROPIC_API_KEY", "bind it to the anthropic-api-key secret")
    return Settings(
        GEMINI_MODEL=gemini_model,
        LLM_PROVIDER=provider,
        ANTHROPIC_MODEL=anthropic_model,
        ANTHROPIC_API_KEY=anthropic_key,
        GCP_PROJECT=env.get("GCP_PROJECT", ""),
        VERTEX_REGION=env.get("VERTEX_REGION", "us-west1"),
        ROUTES_API_KEY=env.get("ROUTES_API_KEY", ""),
        TOKEN_511=env.get("TOKEN_511", ""),
        TICKETMASTER_KEY=env.get("TICKETMASTER_KEY") or None,
        TOOL_TIMEOUT_S=float(env.get("TOOL_TIMEOUT_S", "1.5")),
        EXPLAIN_TIMEOUT_S=float(env.get("EXPLAIN_TIMEOUT_S", "4.0")),
        EXTRACT_TIMEOUT_S=float(env.get("EXTRACT_TIMEOUT_S", "4.0")),
        RATE_LIMIT_PER_HOUR=int(env.get("RATE_LIMIT_PER_HOUR", "10")),
        MAX_MESSAGE_CHARS=int(env.get("MAX_MESSAGE_CHARS", "500")),
    )
