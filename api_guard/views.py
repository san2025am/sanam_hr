# في ملف api_guard/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated # <-- الأهم
from rest_framework import generics, permissions,viewsets
from .models import User
from .models import Role
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import GuardTokenObtainPairSerializer
# ... (الـ Views الأخرى مثل الخاصة بنفاذ)
from rest_framework import status


from .serializers import PhoneForgotSerializer, PhoneResetSerializer

from .serializers import (
    GuardTokenObtainPairSerializer,
    PhoneForgotSerializer,
    PhoneResetSerializer,
    RoleSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
)

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

# في ملف api_guard/views.py


class GuardLoginView(TokenObtainPairView):
    serializer_class = GuardTokenObtainPairSerializer



class PasswordForgotPhoneView(APIView):
    permission_classes = []; authentication_classes = []
    def post(self, request):
        s = PhoneForgotSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response({
            "session_id": s.validated_data["session_id"],
            "detail": "تم إرسال الرمز إلى بريدك الإلكتروني"
        }, status=status.HTTP_200_OK)

class PasswordResetPhoneView(APIView):
    permission_classes = []; authentication_classes = []
    def post(self, request):
        s = PhoneResetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"detail": "تم تغيير كلمة المرور"}, status=status.HTTP_200_OK)