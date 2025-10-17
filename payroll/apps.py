from django.apps import AppConfig


class PayrollConfigApp(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payroll'
    verbose_name = "الرواتب اليومية"

    def ready(self):
        # ربط إشارات إعادة احتساب الرواتب عند الإضافة/التعديل/الحذف
        try:
            from . import signals  # noqa: F401
        except Exception:
            # لا تعطل الإقلاع إذا فشل ربط الإشارات لأي سبب
            pass
