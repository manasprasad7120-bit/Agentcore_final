from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
import logging
from pathlib import Path
import smtplib
import ssl


TEMPLATES_DIR = Path(__file__).with_suffix("").parent / "templates"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SmtpConfig:
    host: str
    port: int
    from_email: str
    from_name: str | None
    use_tls: bool
    use_ssl: bool
    timeout_seconds: int


def _coalesce_setting(
    settings,
    *names: str,
) -> str | None:
    for name in names:
        value = getattr(settings, name, None)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        elif value is not None:
            return str(value)
    return None


def _coalesce_bool_setting(settings, *names: str, default: bool) -> bool:
    for name in names:
        value = getattr(settings, name, None)
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip():
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _coalesce_int_setting(settings, *names: str, default: int) -> int:
    for name in names:
        value = getattr(settings, name, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return int(value.strip())
            except ValueError:
                continue
    return default


def _load_smtp_config(settings) -> SmtpConfig:
    host = _coalesce_setting(settings, "smtp_host", "smtp_server")
    port_raw = _coalesce_int_setting(settings, "smtp_port", default=0)
    from_email = _coalesce_setting(settings, "smtp_from_email", "smtp_from")

    if not host or not port_raw or not from_email:
        raise ValueError("SMTP is not fully configured.")

    from_name = _coalesce_setting(settings, "smtp_from_name")
    use_ssl = _coalesce_bool_setting(settings, "smtp_use_ssl", default=False)
    use_tls = _coalesce_bool_setting(settings, "smtp_use_tls", default=not use_ssl)
    # Cap the worst-case SMTP wait at 7s. Healthy SMTP completes well under a
    # second; the previous 20s default meant a misconfigured/slow mail server
    # blocked every user-edit request for up to 20 seconds. Override via the
    # smtp_timeout_seconds setting if a longer wait is genuinely required.
    timeout_seconds = _coalesce_int_setting(settings, "smtp_timeout_seconds", default=7)

    return SmtpConfig(
        host=host,
        port=port_raw,
        from_email=from_email,
        from_name=from_name,
        use_tls=use_tls,
        use_ssl=use_ssl,
        timeout_seconds=timeout_seconds,
    )


def _render_template(template_name: str, context: dict[str, str]) -> str:
    template_path = TEMPLATES_DIR / template_name
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)


def _render_changed_fields_html(changed_fields: list[str]) -> str:
    if not changed_fields:
        return "<li>No field details were provided.</li>"
    return "".join(f"<li>{escape(field)}</li>" for field in changed_fields)


def _render_changed_fields_text(changed_fields: list[str]) -> str:
    if not changed_fields:
        return "  - No field details were provided."
    return "\n".join(f"  - {field}" for field in changed_fields)


def _build_message(
    *,
    smtp_config: SmtpConfig,
    recipient_email: str,
    subject: str,
    context: dict[str, str],
) -> EmailMessage:
    message = EmailMessage()
    message["To"] = recipient_email
    message["From"] = (
        f"{smtp_config.from_name} <{smtp_config.from_email}>"
        if smtp_config.from_name
        else smtp_config.from_email
    )
    message["Subject"] = subject
    message.set_content(_render_template("user_notification.txt", context))
    message.add_alternative(
        _render_template("user_notification.html", context),
        subtype="html",
    )
    return message


def _send_message_sync(
    *,
    smtp_config: SmtpConfig,
    message: EmailMessage,
) -> None:
    logger.info(
        "Sending notification email via SMTP host=%s port=%s tls=%s ssl=%s",
        smtp_config.host,
        smtp_config.port,
        smtp_config.use_tls,
        smtp_config.use_ssl,
    )
    if smtp_config.use_ssl:
        with smtplib.SMTP_SSL(
            smtp_config.host,
            smtp_config.port,
            timeout=smtp_config.timeout_seconds,
            context=ssl.create_default_context(),
        ) as server:
            server.send_message(message)






            
        logger.info("Notification email sent successfully via SMTP_SSL.")
        return

    with smtplib.SMTP(
        smtp_config.host,
        smtp_config.port,
        timeout=smtp_config.timeout_seconds,
    ) as server:
        server.ehlo()
        if smtp_config.use_tls:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        server.send_message(message)
    logger.info("Notification email sent successfully via SMTP.")


async def send_user_notification_email(
    *,
    settings,
    recipient_email: str | None,
    recipient_name: str,
    subject: str,
    headline: str,
    intro_text: str,
    summary_text: str,
    actor_name: str,
    changed_fields: list[str],
    organization_name: str | None = None,
    department_name: str | None = None,
) -> tuple[bool, str | None]:
    if not recipient_email:
        logger.warning("Skipping notification email because recipient email is missing.")
        return False, "Recipient email is missing for this user."

    try:
        smtp_config = _load_smtp_config(settings)
    except ValueError as exc:
        logger.warning("Skipping notification email because SMTP config is incomplete: %s", exc)
        return False, str(exc)

    context = {
        "recipient_name": recipient_name,
        "headline": headline,
        "intro_text": intro_text,
        "summary_text": summary_text,
        "actor_name": actor_name,
        "organization_name": organization_name or "-",
        "department_name": department_name or "-",
        "changed_fields_text": _render_changed_fields_text(changed_fields),
        "changed_fields_html": _render_changed_fields_html(changed_fields),
    }

    try:
        message = _build_message(
            smtp_config=smtp_config,
            recipient_email=recipient_email,
            subject=subject,
            context=context,
        )
        await asyncio.to_thread(
            _send_message_sync,
            smtp_config=smtp_config,
            message=message,
        )
        return True, None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to send notification email via SMTP: %s", exc)
        return False, str(exc)
