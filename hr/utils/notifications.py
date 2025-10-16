# hr/utils/notifications.py
from django.core.mail import send_mail
from django.conf import settings

STATUS_EMAIL_SUBJECT = {
    "under_review": "تحديث حالة طلبك لدى سنام الأمن",
    "accepted":     "تم قبول طلبك لدى سنام الأمن",
    "rejected":     "تحديث حالة طلبك لدى سنام الأمن",
}

STATUS_EMAIL_BODY = {
    "under_review": lambda app: f"""مرحبًا {app.full_name},

تم تحديث حالة طلبك لدى سنام الأمن إلى: قيد المراجعة.
سنقوم بالتواصل معك عند اكتمال الخطوات التالية.

تحياتنا،
فريق التوظيف — سنام الأمن
""",
    "accepted": lambda app: f"""مرحبًا {app.full_name},

نبارك لك! تم قبول طلبك مبدئيًا لدى سنام الأمن.
سنرسل لك عقد العمل الإلكتروني للتوقيع خلال الساعات القادمة.

تحياتنا،
فريق التوظيف — سنام الأمن
""",
    "rejected": lambda app: f"""مرحبًا {app.full_name},

نعتذر، تم رفض طلبك في هذه المرحلة.
نشكرك على اهتمامك ونأمل توافر فرص مناسبة قريبًا.

تحياتنا،
فريق التوظيف — سنام الأمن
""",
}

def send_status_email(app):
    """يرسل رسالة بحسب الحالة الحالية للطلب."""
    if not app.email:
        return False  # لا يوجد بريد لإرساله
    key = app.status  # "under_review" / "accepted" / "rejected" / "new"
    if key not in STATUS_EMAIL_SUBJECT:
        return False
    subject = STATUS_EMAIL_SUBJECT[key]
    body = STATUS_EMAIL_BODY[key](app)
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[app.email],
        fail_silently=False,
    )
    return True
