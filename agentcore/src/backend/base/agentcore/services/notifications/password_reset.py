from __future__ import annotations

import asyncio
import logging
from email.message import EmailMessage

from agentcore.services.notifications.user_email import _load_smtp_config, _send_message_sync

logger = logging.getLogger(__name__)

_HTML = """\
<html><body style="font-family:sans-serif;color:#333;padding:32px;max-width:480px;margin:0 auto">
  <h2 style="color:#da2128;margin-bottom:8px">Reset Your Password</h2>
  <p>Hello {name},</p>
  <p>Click the button below to set your password. This link expires in <strong>30 minutes</strong>.</p>
  <p style="margin:28px 0">
    <a href="{reset_link}"
       style="background:#da2128;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold;display:inline-block">
      Reset Password
    </a>
  </p>
  <p style="color:#888;font-size:12px">If you didn't request this, you can safely ignore this email.</p>
</body></html>
"""

_TEXT = """\
Reset Your Password

Hello {name},

Use the link below to set your password (expires in 30 minutes):
{reset_link}

If you didn't request this, ignore this email.
"""


async def send_password_reset_email(
    *,
    settings,
    recipient_email: str,
    recipient_name: str,
    reset_link: str,
) -> tuple[bool, str | None]:
    try:
        smtp_config = _load_smtp_config(settings)
    except ValueError as exc:
        logger.warning("SMTP not configured for password reset: %s", exc)
        return False, str(exc)

    name = recipient_name or recipient_email
    msg = EmailMessage()
    msg["To"] = recipient_email
    msg["From"] = (
        f"{smtp_config.from_name} <{smtp_config.from_email}>"
        if smtp_config.from_name
        else smtp_config.from_email
    )
    msg["Subject"] = "Reset Your Password"
    msg.set_content(_TEXT.format(name=name, reset_link=reset_link))
    msg.add_alternative(_HTML.format(name=name, reset_link=reset_link), subtype="html")

    try:
        await asyncio.to_thread(_send_message_sync, smtp_config=smtp_config, message=msg)
        return True, None
    except Exception as exc:
        logger.exception("Password reset email failed: %s", exc)
        return False, str(exc)
