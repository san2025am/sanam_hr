
from django.apps import AppConfig

class ApiGuardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api_guard'
    verbose_name = "إدارة شركة الأمن" # اسم سيظهر في لوحة التحكم

    def ready(self):
        # استيراد الإشارات لضمان تسجيلها عند بدء تشغيل التطبيق
        import api_guard.models 


