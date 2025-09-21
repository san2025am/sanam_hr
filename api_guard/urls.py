# في ملف api_guard/urls.py

from django.urls import path,include
from . import views # سنقوم بإنشاء هذه الـ views في الخطوة التالية
from rest_framework.routers import DefaultRouter
# 1. إنشاء Router
router = DefaultRouter()
from api_guard.views import  GuardLoginAndProfileView, PasswordForgotUsernameView, PasswordResetUsernameView


# 2. تسجيل الـ ViewSet مع الـ Router
# 'roles' هو المسار الذي سيتم استخدامه في الـ URL (e.g., /api/v1/roles/)

urlpatterns = [
    # مثال: نقطة نهاية محمية لعرض بيانات المستخدم الحالي
    path("auth/guard/login/", GuardLoginAndProfileView.as_view(), name="guard-login"),
     path("auth/password/forgot/username/", PasswordForgotUsernameView.as_view(), name="password-forgot-Username"),
    path("auth/password/reset/username/",  PasswordResetUsernameView.as_view(),  name="password-reset-Username"),
  


    # هنا سنضيف جميع نقاط النهاية المستقبلية الخاصة بالتطبيق
    # مثل:
    # path('tasks/', views.TaskListCreateView.as_view(), name='task-list'),
    # path('tasks/<int:pk>/', views.TaskDetailView.as_view(), name='task-detail'),
]
