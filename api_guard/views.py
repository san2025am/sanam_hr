# في ملف api_guard/views.py

from time import timezone
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

from .models import AttendanceRecord, Employee,Salary


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
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        action   = ser.validated_data["action"]
        employee = ser.validated_data["employee"]
        location = ser.validated_data["location_obj"]
        lat      = ser.validated_data["lat"]
        lng      = ser.validated_data["lng"]
        acc      = ser.validated_data.get("accuracy")
        dist     = ser.validated_data.get("distance_m")
        now      = timezone.now()

        if action == "check_in":
            # امنع تكرار حضور مفتوح
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time").first())
            if open_rec:
                return Response(
                    {"detail": "لديك سجل حضور مفتوح بالفعل. سجّل الانصراف أولًا.",
                     "record_id": str(open_rec.id)},
                    status=status.HTTP_400_BAD_REQUEST
                )

            rec = AttendanceRecord.objects.create(
                employee=employee,
                location=location,
                check_in_time=now,
                notes=f"in lat={lat}, lng={lng}, acc={acc}, dist={dist}"
            )
            return Response({
                "detail": "تم تسجيل الحضور بنجاح.",
                "record_id": str(rec.id),
                "employee": employee.full_name,
                "location": location.name,
                "within_radius": True,
                "distance": round(dist or 0.0, 2),
            }, status=status.HTTP_201_CREATED)

        # check_out
        rec = (AttendanceRecord.objects
               .filter(employee=employee, check_out_time__isnull=True)
               .order_by("-check_in_time").first())
        if not rec:
            return Response({"detail": "لا يوجد سجل حضور مفتوح لإقفاله."},
                            status=status.HTTP_400_BAD_REQUEST)

        rec.check_out_time = now
        note_suffix = f" | out lat={lat}, lng={lng}, acc={acc}, dist={dist}"
        rec.notes = (rec.notes or "") + note_suffix
        # لو الحضور لم يُسجل موقعاً لأي سبب، ثبّت الموقع
        rec.location = rec.location or location
        rec.save(update_fields=["check_out_time", "notes", "location"])

        return Response({
            "detail": "تم تسجيل الانصراف بنجاح.",
            "record_id": str(rec.id),
            "employee": employee.full_name,
            "location": rec.location.name if rec.location else None,
            "within_radius": True,
            "distance": round(dist or 0.0, 2),
        }, status=status.HTTP_200_OK)


class ResolveLocationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = ResolveLocationSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=400)

        employee = ser.validated_data["employee"]
        lat = ser.validated_data["lat"]
        lng = ser.validated_data["lng"]

        found = ser.find_best_location(employee, lat, lng)
        if not found:
            return Response({"detail": "لا يوجد موقع مكلَّف به ضمن النطاق."}, status=404)

        loc, dist, mode = found
        la, ln = (None, None)
        if loc.gps_coordinates:
            try:
                la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
            except Exception:
                pass

        data = {
            "detail": "تم تحديد الموقع",
            "location_id": str(loc.id),      # ← مهم: UUID كنص
            "name": loc.name,
            "client_name": loc.client_name,
            "lat": la, "lng": ln,
            "radius": float(loc.gps_radius),
            "distance": round(dist, 2),
            "mode": mode,  # polygon | radius
        }
        return Response(data, status=200)
