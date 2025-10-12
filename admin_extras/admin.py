from django.contrib import admin

from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('user', 'short_message', 'room', 'created_at')
    list_filter = ('room', 'user')
    search_fields = ('message', 'user__username', 'user__employee__full_name')
    autocomplete_fields = ('user',)
    readonly_fields = ('created_at', 'updated_at')

    def short_message(self, obj):
        return (obj.message or '')[:60]
    short_message.short_description = 'الرسالة'

