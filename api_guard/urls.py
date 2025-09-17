# في ملف api_guard/urls.py

from django.urls import path,include
from . import views # سنقوم بإنشاء هذه الـ views في الخطوة التالية
from rest_framework.routers import DefaultRouter
# 1. إنشاء Router
router = DefaultRouter()
from api_guard.views import GuardLoginView


# 2. تسجيل الـ ViewSet مع الـ Router
# 'roles' هو المسار الذي سيتم استخدامه في الـ URL (e.g., /api/v1/roles/)
router.register(r'roles', views.RoleViewSet, basename='role')

urlpatterns = [
    # مثال: نقطة نهاية محمية لعرض بيانات المستخدم الحالي
    path('users/me/', views.UserProfileView.as_view(), name='user-profile'),
    path("api/auth/guard/login/", GuardLoginView.as_view(), name="guard-login"),
    
    path('users/register/', views.UserRegistrationView.as_view(), name='user-register'),
    path('', include(router.urls)),
    # هنا سنضيف جميع نقاط النهاية المستقبلية الخاصة بالتطبيق
    # مثل:
    # path('tasks/', views.TaskListCreateView.as_view(), name='task-list'),
    # path('tasks/<int:pk>/', views.TaskDetailView.as_view(), name='task-detail'),
]
