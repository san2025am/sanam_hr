from django.urls import path

from . import views


app_name = 'admin_extras'

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('reports/daily-window/', views.daily_window_report_view, name='daily_window_report'),
    path('chat/', views.chat_view, name='chat'),
    path('chat/messages.json', views.chat_messages_json, name='chat_messages'),
    path('chat/send/', views.chat_send, name='chat_send'),
]
