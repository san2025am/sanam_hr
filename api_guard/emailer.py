# api_guard/emailer.py
import logging

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from typing import Iterable, Optional


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


def notify_geofence_violation(
    *,
    employee,
    location=None,
    outside_minutes: Optional[float] = None,
    grace_minutes: Optional[int] = None,
    recorded_at=None,
    extra_recipients: Optional[Iterable[str]] = None,
) -> None:
    """
    يرسل تنبيه بريد إلكتروني عند تسجيل مخالفة الانسحاب (الخروج عن النطاق).
    يعتمد على إعدادات البريد في settings ويستعمل EMAIL_SUBJECT_PREFIX و GEOFENCE_ALERT_RECIPIENTS.
    """
    try:
        from django.conf import settings
    except Exception:  # pragma: no cover
        return

    emp_name = getattr(employee, "full_name", None) or str(getattr(employee, "id", ""))
    loc_name = getattr(location, "name", None) if location is not None else None
    when = recorded_at or timezone.now()

    prefix = getattr(settings, "EMAIL_SUBJECT_PREFIX", "") or ""
    subject = f"{prefix}تنبيه مخالفة الانسحاب — {emp_name}{f' @ {loc_name}' if loc_name else ''}"

    lines = [
        f"تم رصد مخالفة الخروج عن نطاق الموقع للحارس: {emp_name}.",
    ]
    if loc_name:
        lines.append(f"الموقع: {loc_name}.")
    if outside_minutes is not None and grace_minutes is not None:
        try:
            out_str = f"{outside_minutes:.1f}"
        except Exception:
            out_str = str(outside_minutes)
        lines.append(f"مدة الابتعاد: {out_str} دقيقة (المسموح: {grace_minutes} دقيقة).")
    lines.append(f"وقت الرصد: {timezone.localtime(when):%Y-%m-%d %H:%M}.")
    body = "\n".join(lines)

    recipients: list[str] = []
    # البريد الخاص بالموظف
    try:
        emp_email = getattr(getattr(employee, "user", None), "email", None)
        if emp_email and emp_email.strip():
            recipients.append(emp_email.strip())
    except Exception:
        pass
    # بريد المشرف
    try:
        sup_user = getattr(getattr(employee, "supervisor", None), "user", None)
        sup_email = getattr(sup_user, "email", None)
        if sup_email and sup_email.strip():
            recipients.append(sup_email.strip())
    except Exception:
        pass
    # عناوين عامة من الإعدادات
    try:
        extra = list(getattr(settings, "GEOFENCE_ALERT_RECIPIENTS", []) or [])
        for addr in extra:
            if addr and addr.strip():
                recipients.append(addr.strip())
    except Exception:
        pass
    # عناوين إضافية
    if extra_recipients:
        for addr in extra_recipients:
            if addr and str(addr).strip():
                recipients.append(str(addr).strip())

    # إزالة التكرارات
    recipients = list(dict.fromkeys([r for r in recipients if r]))
    if not recipients:
        logger.info("No email recipients available for geofence violation; skipping email.")
        return

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(
        settings, "EMAIL_HOST_USER", None
    ) or "no-reply@sanam.local"
    reply_to = getattr(settings, "EMAIL_REPLY_TO", None)

    email = EmailMessage(subject, body, from_email, recipients)
    if reply_to:
        email.reply_to = [reply_to]
    try:
        email.send(fail_silently=False)
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed sending geofence violation email to %s: %s", recipients, exc)


# =========================
# Reports notifications
# =========================

def _report_admin_url(report) -> str | None:
    try:
        base = getattr(settings, 'SITE_URL', None) or ''
        path = f"/admin/api_guard/report/{report.id}/change/"
        return f"{base}{path}" if base else path
    except Exception:
        return None


def notify_report_created_for_supervisor(*, report, employee) -> None:
    """ينبه المشرف المباشر عند إنشاء بلاغ من الحارس."""
    sup = getattr(employee, 'supervisor', None)
    sup_user = getattr(sup, 'user', None)
    sup_email = getattr(sup_user, 'email', None)
    if not (sup_email and str(sup_email).strip()):
        logger.info("No supervisor email to notify for report #%s", getattr(report, 'id', None))
        return
    prefix = getattr(settings, 'EMAIL_SUBJECT_PREFIX', '') or ''
    loc_name = getattr(getattr(report, 'location', None), 'name', None)
    subject = f"{prefix}بلاغ جديد من {employee.full_name}{f' @ {loc_name}' if loc_name else ''}"
    url = _report_admin_url(report)
    lines = [
        f"تم إنشاء بلاغ نوع: {report.get_report_type_display()} من الحارس: {employee.full_name}.",
        f"الحالة: {report.get_status_display()}.",
    ]
    if loc_name:
        lines.append(f"الموقع: {loc_name}.")
    if url:
        lines.append(f"رابط الإدارة: {url}")
    body = "\n".join(lines)
    email = EmailMessage(subject, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None) or 'no-reply@sanam.local', [sup_email])
    try:
        email.send(fail_silently=False)
    except Exception as exc:
        logger.warning("Failed sending report created email to %s: %s", sup_email, exc)


def notify_report_routed_to_hr(*, report) -> None:
    """ينبه الموارد البشرية عند تحويل البلاغ تلقائيًا إلى HR."""
    recips = list(getattr(settings, 'REPORT_HR_RECIPIENTS', []) or [])
    if not recips:
        logger.info("No REPORT_HR_RECIPIENTS configured; skipping HR route email for report #%s", getattr(report, 'id', None))
        return
    prefix = getattr(settings, 'EMAIL_SUBJECT_PREFIX', '') or ''
    loc_name = getattr(getattr(report, 'location', None), 'name', None)
    employee = getattr(report, 'employee', None)
    emp_name = getattr(employee, 'full_name', None) or '—'
    subject = f"{prefix}بلاغ محوّل للموارد — {emp_name}{f' @ {loc_name}' if loc_name else ''}"
    url = _report_admin_url(report)
    body = "\n".join([
        f"تم تحويل البلاغ تلقائيًا للموارد البشرية بعد تأخر رد المشرف.",
        f"الحارس: {emp_name}.",
        f"نوع البلاغ: {report.get_report_type_display()}.",
        f"الحالة: {report.get_status_display()}.",
        *( [f"الموقع: {loc_name}."] if loc_name else [] ),
        *( [f"رابط الإدارة: {url}"] if url else [] ),
    ])
    email = EmailMessage(subject, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None) or 'no-reply@sanam.local', recips)
    try:
        email.send(fail_silently=False)
    except Exception as exc:
        logger.warning("Failed sending report HR route email to %s: %s", recips, exc)


def notify_report_escalated_to_exec(*, report) -> None:
    """ينبه الإدارة العليا عند التصعيد."""
    recips = list(getattr(settings, 'REPORT_EXEC_RECIPIENTS', []) or [])
    if not recips:
        logger.info("No REPORT_EXEC_RECIPIENTS configured; skipping exec escalation email for report #%s", getattr(report, 'id', None))
        return
    prefix = getattr(settings, 'EMAIL_SUBJECT_PREFIX', '') or ''
    loc_name = getattr(getattr(report, 'location', None), 'name', None)
    employee = getattr(report, 'employee', None)
    emp_name = getattr(employee, 'full_name', None) or '—'
    subject = f"{prefix}بلاغ مُصعّد — {emp_name}{f' @ {loc_name}' if loc_name else ''}"
    url = _report_admin_url(report)
    body = "\n".join([
        f"تم تصعيد البلاغ إلى الإدارة العليا بطلب المستخدم بعد تأخر الرد من الموارد.",
        f"الحارس: {emp_name}.",
        f"نوع البلاغ: {report.get_report_type_display()}.",
        f"الحالة: {report.get_status_display()}.",
        *( [f"الموقع: {loc_name}."] if loc_name else [] ),
        *( [f"رابط الإدارة: {url}"] if url else [] ),
    ])
    email = EmailMessage(subject, body, getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None) or 'no-reply@sanam.local', recips)
    try:
        email.send(fail_silently=False)
    except Exception as exc:
        logger.warning("Failed sending report exec escalation email to %s: %s", recips, exc)
