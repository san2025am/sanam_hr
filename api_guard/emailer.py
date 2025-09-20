# api_guard/emailer.py
from django.core.mail import send_mail
from django.conf import settings

def send_email_otp(to_email: str, subject: str, body: str) -> None:
    if not to_email:
        raise RuntimeError("لا يوجد بريد إلكتروني مرتبط بالحساب")
    sent = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=False)
    if sent == 0:
        raise RuntimeError("فشل إرسال البريد الإلكتروني")
