# api_guard/emailer.py
import logging

from django.conf import settings
from django.core.mail import EmailMessage


logger = logging.getLogger(__name__)


def _log_debug_mail(to_email: str, subject: str, body: str) -> None:
    logger.warning(
        "SMTP credentials are missing; printing OTP email because DEBUG_SMS_ECHO is enabled."
    )
    logger.warning("OTP email → %s | %s", to_email, subject)
    logger.warning(body)


def send_email_otp(to_email: str, subject: str, body: str) -> None:
    if not to_email:
        raise RuntimeError("لا يوجد بريد إلكتروني مرتبط بالحساب")

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(
        settings, "EMAIL_HOST_USER", None
    ) or "no-reply@sanam.local"
    reply_to = getattr(settings, "EMAIL_REPLY_TO", None)
    backend = getattr(settings, "EMAIL_BACKEND", "")

    missing_credentials = (
        backend.endswith("smtp.EmailBackend")
        and (
            not getattr(settings, "EMAIL_HOST_USER", None)
            or not getattr(settings, "EMAIL_HOST_PASSWORD", None)
        )
    )

    if missing_credentials:
        if getattr(settings, "DEBUG_SMS_ECHO", False):
            _log_debug_mail(to_email, subject, body)
            return
        raise RuntimeError(
            "SMTP_HOST/SMTP_USER/SMTP_PASS environment variables are not configured."
        )

    email = EmailMessage(subject, body, from_email, [to_email])
    if reply_to:
        email.reply_to = [reply_to]

    sent = email.send(fail_silently=False)
    if sent == 0:
        raise RuntimeError("فشل إرسال البريد الإلكتروني")
