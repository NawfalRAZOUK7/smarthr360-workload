"""Email notifications for workload alerts (best-effort).

Console backend by default; SMTP via env. WORKLOAD_HR_EMAIL adds an HR
inbox in copy on CRITICAL alerts. Failures are logged, never raised.
"""

from __future__ import annotations

import logging
import os

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def notify_burnout_alert(user_email: str, alert) -> bool:
    recipients = [user_email] if user_email else []
    if alert.level == "CRITICAL":
        hr_inbox = os.environ.get("WORKLOAD_HR_EMAIL", "")
        if hr_inbox:
            recipients.append(hr_inbox)
    if not recipients:
        return False
    try:
        send_mail(
            f"[SmartHR360] Workload alert ({alert.level})",
            (
                f"{alert.message}\n\nRecommendations:\n- "
                + "\n- ".join(alert.recommendations)
                + "\n\nDetails: /api/workload/scores/"
            ),
            getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@smarthr360.dev"),
            recipients,
            fail_silently=False,
        )
        return True
    except Exception as exc:  # pragma: no cover - notification only
        logger.warning("workload alert email failed: %s", exc)
        return False
