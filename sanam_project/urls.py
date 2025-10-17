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
from django.views.generic import RedirectView

# استيراد الـ Views الخاصة بـ simple-jwt
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Redirect /admin/ to the custom dashboard
    path('admin/', RedirectView.as_view(pattern_name='admin_extras:dashboard', permanent=False)),
    # Admin extras (dashboard + chat) under /admin/* must come before admin.site.urls
    path('admin/', include('admin_extras.urls', namespace='admin_extras')),
    path('admin/', admin.site.urls),
   path('', lambda request: HttpResponse('API is running')),
    # هذا السطر صحيح ومهم، لكنه يعالج فقط الروابط داخل تطبيق api_guard
    # مثل /api/v1/users/me/
    path('api/v1/', include('api_guard.urls')), 
    path('hr/', include('hr.urls')),
    # === أضف هذه الأسطر ===
    # هذا هو الجزء المفقود.
    # يقوم بتعريف مسارات تسجيل الدخول وتحديث التوكن.
    path('api/v1/auth/login/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # =======================
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Optional: OpenAPI/Swagger schema if drf-spectacular is installed; fallback to core schema
try:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    ]
except Exception:
    try:
        from rest_framework.schemas import get_schema_view
        from django.views.generic import TemplateView

        schema_view = get_schema_view(title="Sanam API", description="API schema", version="1.0.0")
        urlpatterns += [
            path('api/schema/', schema_view, name='schema'),
        ]
    except Exception:
        pass
