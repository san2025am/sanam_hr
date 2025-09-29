# في ملف api_guard/views.py

from django.utils import timezone as dj_timezone
from django.db import transaction
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

    # تحويل التاريخ لـ ISO محلي (حتى لا تختلط أيام الوردية الليلية على الواجهة)
    @staticmethod
    def _iso_minutes(dt):
        if dt is None:
            return None
        try:
            return dj_timezone.localtime(dt).isoformat(timespec="minutes")
        except Exception:
            return str(dt)

    @classmethod
    def _window(cls, start, end, now):
        return {
            "from": cls._iso_minutes(start),
            "to": cls._iso_minutes(end),
            "now": cls._iso_minutes(now),
        }

    def _deny(self, *, action, detail, reason_code,
              start=None, end=None, now=None, extra=None):
        payload = {
            "ok": False,
            "performed": False,    # لم تُنفّذ العملية
            "action": action,
            "detail": detail,      # نص واضح بالعربي
            "reason_code": reason_code,
        }
        if any(v is not None for v in (start, end, now)):
            payload["window"] = self._window(start, end, now)
        if extra:
            payload.update(extra)
        # نرجع 200 حتى لا يظهر 400 في التطبيق
        return Response(payload, status=status.HTTP_200_OK)

    @transaction.atomic
    def post(self, request):
        ser = AttendanceCheckSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            # أخطاء إدخال (قيم ناقصة/غير صحيحة) — نعيد 200 برسالة لطيفة
            return Response({
                "ok": False,
                "performed": False,
                "action": request.data.get("action"),
                "detail": "تعذّر معالجة الطلب. الرجاء التحقق من الحقول المدخلة.",
                "errors": ser.errors
            }, status=status.HTTP_200_OK)

        v         = ser.validated_data
        action    = v["action"]
        employee  = v["employee"]
        location  = v["location_obj"]
        lat       = v["lat"]
        lng       = v["lng"]
        acc       = v.get("accuracy")
        dist      = v.get("distance_m")

        now       = dj_timezone.now()
        now_local = dj_timezone.localtime(now)

        start_dt  = v.get("shift_window_start")
        end_dt    = v.get("shift_window_end")
        blocked   = v.get("blocked")
        reason    = v.get("blocked_reason")

        # المنع المهذّب القادم من الـ Serializer (خارج النطاق/النافذة/دقة ضعيفة/خارج وردية…)
        if blocked:
            return self._deny(
                action=action,
                detail=reason or "⚠️ لا يمكن تنفيذ العملية في الوقت الحالي.",
                reason_code="business_rule_violation",
                start=start_dt, end=end_dt, now=now_local,
                extra={
                    "location_id": str(getattr(location, "id", "")),
                    "location_name": getattr(location, "name", ""),
                    "client_name": getattr(location.client, "name", "") if getattr(location, "client", None) else "",
                }
            )

        # ===== تنفيذ الإجراءات =====

        # 1) تسجيل حضور
        if action == "check_in":
            # (اختياري) إغلاق أي سجل مفتوح تلقائيًا حتى لا تتكرر السجلات
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time").first())
            if open_rec:
                open_rec.check_out_time = now
                open_rec.notes = (open_rec.notes or "") + f" | auto-out lat={lat}, lng={lng}, acc={acc}, dist={dist}"
                open_rec.location = open_rec.location or location
                open_rec.save(update_fields=["check_out_time", "notes", "location"])

            rec = ser.create(v)  # ينشئ سجل الحضور
            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل حضورك بنجاح.",
                "note": (
                    "الوردية غير مقيّدة زمنيًا."
                    if (start_dt is None and end_dt is None)
                    else (
                        f"الفترة المسموحة للحضور: "
                        f"{dj_timezone.localtime(start_dt).strftime('%H:%M')} → "
                        f"{dj_timezone.localtime(end_dt).strftime('%H:%M')}"
                        if (start_dt and end_dt) else ""
                    )
                ),
                "record_id": str(rec.id) if rec else None,
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location": getattr(location, "name", str(location.pk)),
                "window": self._window(start_dt, end_dt, now),
            }, status=status.HTTP_201_CREATED)

        # 2) تسجيل انصراف
        if action == "check_out":
            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(
                    action=action,
                    detail="لا يوجد سجل حضور مفتوح لإقفاله.",
                    reason_code="no_open_record",
                    start=start_dt, end=end_dt, now=now_local
                )

            rec.check_out_time = now
            rec.notes = (rec.notes or "") + f" | out lat={lat}, lng={lng}, acc={acc}, dist={dist}"
            rec.location = rec.location or location
            rec.save(update_fields=["check_out_time", "notes", "location"])

            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل انصرافك بنجاح.",
                "note": (
                    "الوردية غير مقيّدة زمنيًا."
                    if (start_dt is None and end_dt is None)
                    else (f"يمكن الانصراف اعتبارًا من: {dj_timezone.localtime(start_dt).strftime('%H:%M')}" if start_dt else "")
                ),
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location": getattr(rec.location, "name", None) if rec.location else None,
                "window": self._window(start_dt, end_dt, now),
            }, status=status.HTTP_200_OK)

        # 3) انصراف مبكر
        if action == "early_check_out":
            reason_txt = (request.data.get("early_reason") or "").strip()
            file_obj   = request.FILES.get("early_attachment")
            if not reason_txt:
                return self._deny(
                    action=action,
                    detail="يجب كتابة سبب الانصراف المبكر.",
                    reason_code="early_checkout_reason_required",
                    start=start_dt, end=end_dt, now=now_local
                )

            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(
                    action=action,
                    detail="لا يوجد سجل حضور مفتوح لإقفاله.",
                    reason_code="no_open_record",
                    start=start_dt, end=end_dt, now=now_local
                )

            rec.check_out_time = now
            # حقول اختيارية حسب نموذجك:
            if hasattr(rec, "early_checkout"):
                rec.early_checkout = True
            if hasattr(rec, "early_reason"):
                rec.early_reason = reason_txt
            else:
                rec.notes = (rec.notes or "") + f" | early_reason={reason_txt}"
            if file_obj and hasattr(rec, "early_attachment"):
                rec.early_attachment = file_obj

            rec.notes = (rec.notes or "") + f" | early-out lat={lat}, lng={lng}, acc={acc}, dist={dist}"
            rec.location = rec.location or location
            rec.save()

            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل الانصراف المبكر.",
                "early_checkout": True,
                "early_reason": reason_txt,
                "record_id": str(rec.id),
                "window": self._window(start_dt, end_dt, now),
            }, status=status.HTTP_200_OK)

        # إجراء غير مدعوم
        return self._deny(
            action=action,
            detail="إجراء غير مدعوم.",
            reason_code="unsupported_action",
            start=start_dt, end=end_dt, now=now_local
        )
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
            "location_id": str(loc.id),  # UUID كنص
            "name": loc.name,
            "client_name": loc.client_name,
            "lat": la, "lng": ln,
            "radius": float(loc.gps_radius),
            "distance": round(dist, 2),
            "mode": mode,  # polygon | radius
        }
        return Response(data, status=200)

