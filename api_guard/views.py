# في ملف api_guard/views.py

from rest_framework.views import APIView
from rest_framework.response import Response

from rest_framework_simplejwt.views import TokenObtainPairView
# ... (الـ Views الأخرى مثل الخاصة بنفاذ)


from .serializers import (
    GUARD_ROLE_NAMES,
  AttendanceCheckSerializer,
    GuardTokenObtainPairSerializer,
    ResolveLocationSerializer,
    UsernameForgotSerializer,
    UsernameResetSerializer,
    EmployeeMeSerializer
 
)
from rest_framework.permissions import IsAuthenticated


from django.contrib.auth import get_user_model

from api_guard import serializers
User = get_user_model()


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

# أضف هذا الاستيراد أعلى الملف

# عدّل المسار حسب مكان موديل Employee لديك

class GuardMeView(APIView):
    """
    يعيد بيانات الموظف الحارس الحالي (حسب التوكن).
    يدعم POST (ويمكن دعم GET أيضًا إن رغبت).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        u = request.user
        role = getattr(getattr(u, "role", None), "name", "") or ""
        if role.strip().casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        try:
            emp = Employee.objects.select_related("user", "user__role").get(user=u)
        except Employee.DoesNotExist:
            return Response({"detail": "لا يوجد ملف موظف"}, status=status.HTTP_404_NOT_FOUND)

        return Response(EmployeeMeSerializer(emp).data, status=status.HTTP_200_OK)
    permission_classes = [IsAuthenticated]

    def post(self, request):
        u = request.user
        role_name = (getattr(getattr(u, "role", None), "name", "") or "").strip().casefold()
        if role_name not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            return Response({"detail": "غير مصرح"}, status=status.HTTP_403_FORBIDDEN)

        try:
            emp = Employee.objects.select_related("user", "user__role").get(user=u)
        except Employee.DoesNotExist:
            return Response({"detail": "لا يوجد ملف موظف"}, status=status.HTTP_404_NOT_FOUND)

        return Response(EmployeeMeSerializer(emp).data, status=status.HTTP_200_OK)
    

    
    

class AttendanceCheckAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = AttendanceCheckSerializer(data=request.data, context={"request": request})
        if ser.is_valid():
            try:
                rec, msg = ser.save()  # تُعيد (record, message)
            except serializers.ValidationError as e:
                return Response({"detail": e.detail if hasattr(e, "detail") else str(e)},
                                status=status.HTTP_400_BAD_REQUEST)
            return Response({
                "detail": msg,
                "record_id": str(rec.id),
                "employee": rec.employee.full_name,
                "location": rec.location.name if rec.location else None,
                "check_in_time": rec.check_in_time,
                "check_out_time": rec.check_out_time,
            }, status=status.HTTP_200_OK)
        return Response({"detail": ser.errors if ser.errors else "بيانات غير صالحة"}, status=400)




class ResolveLocationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ResolveLocationSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=400)

        employee = ser.validated_data["employee"]
        lat = ser.validated_data["lat"]
        lng = ser.validated_data["lng"]
        acc = ser.validated_data.get("accuracy", None)

        found = ser.find_best_location(employee, lat, lng)
        if not found:
            return Response({"detail": "لا يوجد موقع مكلَّف به ضمن النطاق."}, status=404)

        loc, dist, mode = found
        # استرجع lat/lng/radius الموحدة
        la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)] if loc.gps_coordinates else (None, None)
        data = {
            "location_id": loc.id,
            "name": loc.name,
            "client_name": loc.client_name,
            "lat": la, "lng": ln,
            "radius": float(loc.gps_radius),
            "distance": round(dist, 2),
            "mode": mode,  # "polygon" أو "radius"
        }
        return Response({"detail": "تم تحديد الموقع", **data}, status=200)
