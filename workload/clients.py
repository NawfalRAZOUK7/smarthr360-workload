"""HTTP clients for sibling SmartHR360 services (best-effort)."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.trust_env = False  # deterministic in CI/sandbox proxies

DEFAULT_TIMEOUT = 4


class RetentionClient:
    """Pushes burnout signals to smarthr360-retention.

    The ORIGINAL caller's token is passed through: retention authorizes
    the ingest itself (self-report or manager/HR). Failures are logged,
    never raised — a retention outage must not break workload scoring.
    """

    def __init__(self, bearer_token: str):
        self.base = os.environ.get(
            "RETENTION_API_URL", "http://retention:8000"
        ).rstrip("/")
        self.headers = {"Authorization": f"Bearer {bearer_token}"}

    def notify_burnout(self, user_id: int, intensity: int, message: str) -> bool:
        try:
            resp = SESSION.post(
                f"{self.base}/api/retention/signals/ingest/",
                headers=self.headers,
                json={
                    "user_id": user_id,
                    "signal_type": "burnout_risk",
                    "intensity": intensity,
                    "source": "smarthr360-workload",
                    "context": message,
                },
                timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code in (200, 201):
                logger.info("retention notified for user %s", user_id)
                return True
            logger.warning(
                "retention ingest returned %s: %s",
                resp.status_code, resp.text[:200],
            )
        except requests.RequestException as exc:
            logger.warning("retention unreachable: %s", exc)
        return False
