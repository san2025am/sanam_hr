# في ملف api_guard/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated # <-- الأهم
from .serializers import UserProfileSerializer
from rest_framework import generics, permissions,viewsets
from .serializers import UserRegistrationSerializer
from .models import User
from .models import Role
from .serializers import RoleSerializer

# ... (الـ Views الأخرى مثل الخاصة بنفاذ)

class UserProfileView(APIView):
    """
    نقطة نهاية محمية.
    لا يمكن الوصول إليها إلا إذا كان المستخدم قد سجل دخوله
    وأرسل Token صالحًا.
    """
    permission_classes = [IsAuthenticated] # تحديد الصلاحيات المطلوبة

    def get(self, request, *args, **kwargs):
        # request.user سيكون متاحًا بفضل JWTAuthentication
        user = request.user
        serializer = UserProfileSerializer(user)
        return Response(serializer.data)

from .serializers import RoleSerializer

# ... (باقي الـ Views) ...

class RoleViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows roles to be viewed or edited.
    يوفر هذا الـ ViewSet جميع العمليات:
    - GET (list):   لعرض قائمة بجميع الأدوار.
    - GET (retrieve): لعرض دور واحد محدد بالـ ID.
    - POST (create): لإنشاء دور جديد.
    - PUT (update): لتحديث دور موجود بالكامل.
    - PATCH (partial_update): لتحديث جزء من دور موجود.
    - DELETE (destroy): لحذف دور موجود.
    """
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    
    # تحديد الصلاحيات: فقط المدير العام (Admin) يمكنه إدارة الأدوار
    # IsAdminUser هي صلاحية مدمجة في Django تتأكد من أن request.user.is_staff == True
    permission_classes = [permissions.IsAdminUser]


# ... (باقي الـ imports والـ Views) ...

class UserRegistrationView(generics.CreateAPIView):
    """
    نقطة نهاية لإنشاء مستخدم جديد (موظف).
    """
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    
    # تحديد الصلاحيات: فقط المستخدمون الذين قاموا بتسجيل الدخول
    # ويمكنك إنشاء صلاحية مخصصة (e.g., IsAdminOrHR) لمزيد من الأمان
    permission_classes = [permissions.IsAuthenticated] 
