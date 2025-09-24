# في ملف api_guard/urls.py

from django.urls import path,include
from . import views # سنقوم بإنشاء هذه الـ views في الخطوة التالية
from rest_framework.routers import DefaultRouter
# 1. إنشاء Router
router = DefaultRouter()
from api_guard.views import  AttendanceCheckAPIView,GuardLoginAndProfileView, GuardMeView, PasswordForgotUsernameView, PasswordResetUsernameView, ResolveLocationAPIView


# 2. تسجيل الـ ViewSet مع الـ Router
# 'roles' هو المسار الذي سيتم استخدامه في الـ URL (e.g., /api/v1/roles/)

urlpatterns = [
    # مثال: نقطة نهاية محمية لعرض بيانات المستخدم الحالي
    path("auth/guard/login/", GuardLoginAndProfileView.as_view(), name="guard-login"),
    path("auth/guard/me/", GuardMeView.as_view(), name="guard-me"),
    path("auth/password/forgot/username/", PasswordForgotUsernameView.as_view(), name="password-forgot-Username"),
    path("auth/password/reset/username/",  PasswordResetUsernameView.as_view(),  name="password-reset-Username"),
  
    path("attendance/check/", AttendanceCheckAPIView.as_view(), name="attendance-check"),

  path("attendance/resolve-location/", ResolveLocationAPIView.as_view(), name="resolve-location"),
]
