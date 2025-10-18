from django.apps import AppConfig

class AdminExtrasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "admin_extras"
    verbose_name = "إضافات لوحة الإدارة"
    def ready(self):
        # تسجيل تحسينات الإدارة
        from . import group_admin  # noqa
        from . import section_admin  # noqa
