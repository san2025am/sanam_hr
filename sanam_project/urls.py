"""
URL configuration for sanam_project project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# في ملف sanam_project/urls.py

from django.contrib import admin
from django.urls import path, include # تأكد من وجود include هنا

# استيراد الـ Views الخاصة بـ simple-jwt
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    # هذا السطر صحيح ومهم، لكنه يعالج فقط الروابط داخل تطبيق api_guard
    # مثل /api/v1/users/me/
    path('api/v1/', include('api_guard.urls')), 

    # === أضف هذه الأسطر ===
    # هذا هو الجزء المفقود.
    # يقوم بتعريف مسارات تسجيل الدخول وتحديث التوكن.
    path('api/v1/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # =======================
]
