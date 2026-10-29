"""Runtime settings, read from the environment.

Secrets (``ROUTES_API_KEY``, ``TOKEN_511``, ``TICKETMASTER_KEY``) come from
Secret Manager via Cloud Run env bindings; they are excluded from ``repr`` so
a logged ``Settings`` never leaks them. Gemini is reached with the service
account, so there is no Gemini key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DISPLAY_TZ = "America/Los_Angeles"


@dataclass(frozen=True)
class Settings:
    GEMINI_MODEL: str
    GCP_PROJECT: str = ""
    VERTEX_REGION: str = "us-west1"
    ROUTES_API_KEY: str = field(default="", repr=False)
    TOKEN_511: str = field(default="", repr=False)
    TICKETMASTER_KEY: str | None = field(default=None, repr=False)
    TOOL_TIMEOUT_S: float = 1.5
    EXPLAIN_TIMEOUT_S: float = 4.0
    RATE_LIMIT_PER_HOUR: int = 10
    MAX_MESSAGE_CHARS: int = 500
    # Fixed, not read from the environment: the process-wide TZ variable is
    # often "UTC" in containers, and user-facing times must be Pacific.
    TZ: str = DISPLAY_TZ


def load_settings() -> Settings:
    """Build ``Settings`` from the environment.

    Raises ``RuntimeError`` if ``GEMINI_MODEL`` is unset or blank: the model id
    has no default, so a deploy that forgot it fails at startup, not at the
    first question.
    """
    model = os.environ.get("GEMINI_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "GEMINI_MODEL is not set; set it to a Flash-tier model id available "
            "in Vertex AI (there is deliberately no default)"
        )
    env = os.environ
    return Settings(
        GEMINI_MODEL=model,
        GCP_PROJECT=env.get("GCP_PROJECT", ""),
        VERTEX_REGION=env.get("VERTEX_REGION", "us-west1"),
        ROUTES_API_KEY=env.get("ROUTES_API_KEY", ""),
        TOKEN_511=env.get("TOKEN_511", ""),
        TICKETMASTER_KEY=env.get("TICKETMASTER_KEY") or None,
        TOOL_TIMEOUT_S=float(env.get("TOOL_TIMEOUT_S", "1.5")),
        EXPLAIN_TIMEOUT_S=float(env.get("EXPLAIN_TIMEOUT_S", "4.0")),
        RATE_LIMIT_PER_HOUR=int(env.get("RATE_LIMIT_PER_HOUR", "10")),
        MAX_MESSAGE_CHARS=int(env.get("MAX_MESSAGE_CHARS", "500")),
    )
