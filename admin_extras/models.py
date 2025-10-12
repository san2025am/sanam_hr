from django.conf import settings
from django.db import models

from core.models import BaseModel


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
