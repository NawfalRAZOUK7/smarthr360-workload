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


class CoreHRClient:
    """Reads the manager's team from smarthr360-core-hr (token
    pass-through) so rebalancing can name actual teammates."""

    def __init__(self, bearer_token: str):
        self.base = os.environ.get(
            "CORE_HR_API_URL", "http://core-hr:8000"
        ).rstrip("/")
        self.headers = {"Authorization": f"Bearer {bearer_token}"}

    def get_my_team_user_ids(self) -> list[int] | None:
        """user_ids of the caller's direct team; None when unavailable."""
        try:
            resp = SESSION.get(
                f"{self.base}/api/hr/employees/my-team/",
                headers=self.headers, timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("core-hr my-team returned %s", resp.status_code)
                return None
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("core-hr unavailable: %s", exc)
            return None
        data = payload.get("data", payload)
        if isinstance(data, dict):
            data = data.get("results", [])
        return [p["user_id"] for p in data or [] if p.get("user_id")]
