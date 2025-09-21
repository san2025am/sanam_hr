# في ملف api_guard/views.py

from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework_simplejwt.views import TokenObtainPairView
# ... (الـ Views الأخرى مثل الخاصة بنفاذ)



from .serializers import (
    GuardTokenObtainPairSerializer,
    UsernameForgotSerializer,
    UsernameResetSerializer,
    EmployeeMeSerializer
 
)

from rest_framework import permissions, status
from django.shortcuts import get_object_or_404



from django.contrib.auth import authenticate
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Employee,Salary


class GuardLoginView(TokenObtainPairView):
    serializer_class = GuardTokenObtainPairSerializer



class PasswordForgotUsernameView(APIView):
    permission_classes = []; authentication_classes = []
    def post(self, request):
        s = UsernameForgotSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response({
            "session_id": s.validated_data["session_id"],
            "detail": "تم إرسال الرمز إلى بريدك الإلكتروني"
        }, status=status.HTTP_200_OK)

class PasswordResetUsernameView(APIView):
    permission_classes = []; authentication_classes = []
    def post(self, request):
        s = UsernameResetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"detail": "تم تغيير كلمة المرور"}, status=status.HTTP_200_OK)
    


class GuardLoginAndProfileView(APIView):
    """
    POST /api/v1/auth/guard/login/
    body: { "username": "...", "password": "..." }
    returns: { access, refresh, user: {...}, employee: {...} }
    (مسموح فقط لمن دوره guard)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            return Response({"detail": "اسم المستخدم/كلمة المرور مطلوبة"}, status=400)

        user = authenticate(request, username=username, password=password)
        if not user:
            return Response({"detail": "بيانات دخول غير صحيحة"}, status=401)

        if not user.is_active:
            return Response({"detail": "الحساب غير مُفعل"}, status=403)

        role_name = getattr(getattr(user, "role", None), "name", None)
        if role_name != "guard":
            return Response({"detail": "الدخول متاح لحُراس الأمن فقط"}, status=403)

        # جهّز بيانات الموظف
        try:
            employee = Employee.objects.select_related(
                "user", "user__role", "salary"
            ).prefetch_related("locations").get(user=user)
            Salary.objects.get_or_create(employee=employee) 

        except Employee.DoesNotExist:
            return Response({"detail": "لا يوجد ملف موظف مرتبط بهذا المستخدم"}, status=404)

        emp_data = EmployeeMeSerializer(employee).data

        # أنشئ توكنات JWT
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        return Response({
            "access": str(access),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": role_name,
                "role_label": str(user.role) if getattr(user, "role", None) else None,
            },
            "employee": emp_data
        }, status=200)
