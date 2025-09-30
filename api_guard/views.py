from __future__ import annotations

from datetime import timedelta

from django.utils import timezone as dj_timezone
from django.db import transaction
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import AttendanceRecord, Employee, Salary
from .serializers import (
    GUARD_ROLE_NAMES,
    ReportSerializer,
    RequestSerializer,
    ResolveLocationSerializer,
    AttendanceCheckSerializer,
    GuardTokenObtainPairSerializer,
    UsernameForgotSerializer,
    UsernameResetSerializer,
    EmployeeMeSerializer,
    AttendanceCheckSerializer,
    ResolveLocationSerializer,
)

User = get_user_model()


# =========================
# Auth
# =========================
 

from .models import AttendanceRecord, Employee, Salary, Report, ReportAttachment, Request


User = get_user_model()


_GUARD_ROLE_NAMES_CI = {name.casefold() for name in GUARD_ROLE_NAMES}


def _require_guard_employee(user):
    role_name = (getattr(getattr(user, "role", None), "name", "") or "").strip()
    if role_name.casefold() not in _GUARD_ROLE_NAMES_CI:
        raise PermissionDenied("الدخول متاح لحراس الأمن فقط")
    try:
        return Employee.objects.select_related("user", "user__role").get(user=user)
    except Employee.DoesNotExist as exc:
        raise NotFound("لا يوجد ملف موظف مرتبط بهذا الحساب") from exc


class GuardLoginView(TokenObtainPairView):
    serializer_class = GuardTokenObtainPairSerializer


class PasswordForgotUsernameView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        s = UsernameForgotSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response({
            "session_id": s.validated_data["session_id"],
            "detail": "تم إرسال الرمز إلى بريدك الإلكتروني"
        }, status=status.HTTP_200_OK)


class PasswordResetUsernameView(APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, request):
        s = UsernameResetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response({"detail": "تم تغيير كلمة المرور"}, status=status.HTTP_200_OK)


class GuardLoginAndProfileView(APIView):
    """
    بديل سريع: يعيد التوكنات + ملف الموظف في رد واحد.
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
        if (role_name or "").strip().casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            return Response({"detail": "الدخول متاح لحُراس الأمن فقط"}, status=403)

        try:
            employee = Employee.objects.select_related("user", "user__role").get(user=user)
            Salary.objects.get_or_create(employee=employee)
        except Employee.DoesNotExist:
            return Response({"detail": "لا يوجد ملف موظف مرتبط بهذا المستخدم"}, status=404)

        emp_data = EmployeeMeSerializer(employee).data
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


class GuardMeView(APIView):
    """يعيد بيانات الموظف الحالي."""
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


# =========================
# Attendance
# =========================

class AttendanceCheckAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _deny(self, *, action, detail, reason_code,
              start=None, end=None, now=None, extra=None):
        payload = {
            "ok": False,
            "performed": False,
            "action": action,
            "detail": detail,
            "reason_code": reason_code,
        }
        wnd = {}
        if start is not None: wnd["from"] = start
        if end   is not None: wnd["to"]   = end
        if now   is not None: wnd["now"]  = now
        if wnd: payload["window"] = wnd
        if extra: payload.update(extra)
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        ser = AttendanceCheckSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            # صياغة رسالة مفصلة بدل "تحقق من الحقول"
            err_text = []
            for field, msgs in ser.errors.items():
                if isinstance(msgs, (list, tuple)):
                    msgs = ", ".join([str(m) for m in msgs])
                err_text.append(f"{field}: {msgs}")
            nice = "؛ ".join(err_text) if err_text else "الرجاء التحقق من الحقول المدخلة."
            return Response({
                "ok": False, "performed": False,
                "action": request.data.get("action"),
                "detail": f"تعذر معالجة الطلب. {nice}",
                "errors": ser.errors
            }, status=status.HTTP_200_OK)

        # استخراج القيم
        action   = ser.validated_data.get("action")
        employee = ser.validated_data.get("employee")
        location = ser.validated_data.get("location_obj")
        lat      = ser.validated_data.get("lat")
        lng      = ser.validated_data.get("lng")
        acc      = ser.validated_data.get("accuracy")
        dist     = ser.validated_data.get("distance_m")

        now       = dj_timezone.now()
        now_local = dj_timezone.localtime(now)

        start_dt  = ser.validated_data.get("shift_window_start")
        end_dt    = ser.validated_data.get("shift_window_end")
        blocked   = ser.validated_data.get("blocked")
        reason    = ser.validated_data.get("blocked_reason")

        if blocked:
            return self._deny(
                action=action,
                detail=reason or "⚠️ لا يمكن تنفيذ العملية في الوقت الحالي.",
                reason_code="business_rule_violation",
                start=start_dt, end=end_dt, now=now_local
            )

        # ===== تنفيذ الإجراءات =====
        if action == "check_in":
            # منع تسجيل حضور جديد إن وُجد سجل مفتوح
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time").first())
            if open_rec:
                return self._deny(
                    action=action,
                    detail="⚠️ تم تسجيل حضور مسبقًا، لا يمكن تسجيل حضور آخر قبل الانصراف.",
                    reason_code="already_checked_in",
                    start=start_dt, end=end_dt, now=now_local
                )

            # منع تعدد الحضور في نفس اليوم
            today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end   = today_start + timedelta(days=1)
            if AttendanceRecord.objects.filter(
                employee=employee,
                check_in_time__gte=today_start,
                check_in_time__lt=today_end
            ).exists():
                return self._deny(
                    action=action,
                    detail="⚠️ تم تسجيل حضور مسبقًا اليوم.",
                    reason_code="already_checked_in_today",
                    start=start_dt, end=end_dt, now=now_local
                )

            # إنشاء السجل
            rec = ser.save()
            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل حضورك بنجاح.",
                "note": ("الوردية غير مقيّدة زمنيًا."
                         if start_dt is None and end_dt is None
                         else (f"الفترة المسموحة للحضور: {start_dt.strftime('%H:%M')} → {end_dt.strftime('%H:%M')}"
                               if start_dt and end_dt else "")),
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(location.id) if getattr(location, "id", None) else None,
                "location_name": getattr(location, "name", None),
            }, status=status.HTTP_201_CREATED)

        elif action == "check_out":
            # منع الانصراف العادي إذا كان هناك انصراف مبكر اليوم
            today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end   = today_start + timedelta(days=1)
            if AttendanceRecord.objects.filter(
                employee=employee,
                check_in_time__gte=today_start, check_in_time__lt=today_end,
                early_checkout=True
            ).exists():
                return self._deny(
                    action=action,
                    detail="⚠️ تم تسجيل انصراف مبكر اليوم؛ لا يمكن الانصراف العادي.",
                    reason_code="early_checkout_done",
                    start=start_dt, end=end_dt, now=now_local
                )

            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(action=action, detail="لا يوجد سجل حضور مفتوح لإقفاله.", reason_code="no_open_record")

            rec.check_out_time = now_local
            rec.notes = (rec.notes or "") + f" | out lat={lat}, lng={lng}, acc={acc}, dist={dist}"
            rec.location = rec.location or location
            rec.save(update_fields=["check_out_time", "notes", "location"])

            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل انصرافك بنجاح.",
                "note": ("الوردية غير مقيّدة زمنيًا."
                         if (start_dt is None and end_dt is None)
                         else (f"يمكن الانصراف اعتبارًا من: {start_dt.strftime('%H:%M')}" if start_dt else "")),
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(rec.location.id) if rec.location else None,
                "location_name": getattr(rec.location, "name", None) if rec.location else None,
            }, status=status.HTTP_200_OK)

        elif action == "early_check_out":
            # يجب وجود سجل حضور مفتوح
            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(action=action, detail="لا يوجد سجل حضور مفتوح لإقفاله.", reason_code="no_open_record")

            # مرّة واحدة يوميًا
            today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end   = today_start + timedelta(days=1)
            if AttendanceRecord.objects.filter(
                employee=employee,
                check_in_time__gte=today_start, check_in_time__lt=today_end,
                early_checkout=True
            ).exists():
                return self._deny(
                    action=action,
                    detail="⚠️ تم تسجيل انصراف مبكر مسبقًا اليوم.",
                    reason_code="early_checkout_once_per_day",
                    start=start_dt, end=end_dt, now=now_local
                )

            reason_txt = (request.data.get("early_reason") or "").strip()
            file_obj   = request.FILES.get("early_attachment")
            if not reason_txt:
                return self._deny(action=action, detail="يجب كتابة سبب الانصراف المبكر.", reason_code="early_checkout_reason_required")

            rec.check_out_time = now_local
            rec.early_checkout = True
            rec.early_reason   = reason_txt
            if file_obj:
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
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(rec.location.id) if rec.location else None,
                "location_name": getattr(rec.location, "name", None) if rec.location else None,
            }, status=status.HTTP_200_OK)

        return self._deny(action=action, detail="إجراء غير مدعوم.", reason_code="unsupported_action")


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
            "location_id": str(loc.id),
            "name": loc.name,
            "client_name": loc.client_name,
            "lat": la, "lng": ln,
            "radius": float(loc.gps_radius),
            "distance": round(dist, 2),
            "mode": mode,  # polygon | radius
        }
        return Response(data, status=200)


class GuardReportListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReportSerializer

    def get_queryset(self):
        employee = _require_guard_employee(self.request.user)
        return (
            Report.objects
            .filter(employee=employee)
            .select_related("location")
            .prefetch_related("attachments")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        employee = _require_guard_employee(self.request.user)
        with transaction.atomic():
            report = serializer.save(employee=employee)
            self._save_attachments(report)
        return report

    def _save_attachments(self, report):
        files = self.request.FILES.getlist("attachments")
        for uploaded in files:
            ReportAttachment.objects.create(
                report=report,
                file=uploaded,
                file_type=self._detect_file_type(uploaded),
            )

    @staticmethod
    def _detect_file_type(uploaded):
        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type.startswith("video/"):
            return "video"
        return "image"


class GuardRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RequestSerializer

    def get_queryset(self):
        employee = _require_guard_employee(self.request.user)
        return (
            Request.objects
            .filter(employee=employee)
            .select_related("approver")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        employee = _require_guard_employee(self.request.user)
        serializer.save(employee=employee)
