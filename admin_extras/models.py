from django.conf import settings
from django.db import models

from core.models import BaseModel
from django.contrib.auth.models import Group, Permission


class ChatMessage(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_chat_messages')
    message = models.TextField()
    room = models.CharField(max_length=50, default='general')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'رسالة دردشة (أدمن)'
        verbose_name_plural = 'رسائل الدردشة (أدمن)'

    def __str__(self):
        return f"{self.user}: {self.message[:30]}"


class FunctionalSection(BaseModel):
    """
    تعريف قسم وظيفي (HR/Finance/Operations/Logistics ...) مع صلاحياته ورابط لوحة إدارته.
    - code: رمز فريد (HR, Finance, ...)
    - title: اسم قابل للعرض.
    - admin_path: الرابط الأساسي للوحة القسم، مثل "/admin/hr/".
    - group: مجموعة المستخدمين المرتبطة بهذا القسم (اختياريًا للتحكم السريع).
    - permissions: الصلاحيات المرتبطة بالقسم (يمكن ضبطها يدويًا أو عبر القوالب).
    """

    code = models.SlugField(max_length=40, unique=True, verbose_name="الرمز")
    title = models.CharField(max_length=120, verbose_name="الاسم")
    admin_path = models.CharField(max_length=200, verbose_name="رابط اللوحة", help_text='مثال: /admin/hr/')
    group = models.ForeignKey(Group, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المجموعة المرتبطة")
    permissions = models.ManyToManyField(Permission, blank=True, related_name="functional_sections", verbose_name="الصلاحيات")
    is_active = models.BooleanField(default=True, verbose_name="مفعّل؟")
    order = models.PositiveIntegerField(default=100, verbose_name="الترتيب")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    class Meta:
        ordering = ["order", "code"]
        verbose_name = "قسم وظيفي"
        verbose_name_plural = "الأقسام الوظيفية"

    def __str__(self):
        return f"{self.title} ({self.code})"
