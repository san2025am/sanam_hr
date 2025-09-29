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
from datetime import timedelta



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

    def _deny(self, *, action, detail, reason_code, start=None, end=None, now=None, extra=None):
        payload = {
            "ok": False,
            "performed": False,      # لم تُنفّذ العملية
            "action": action,
            "detail": detail,        # نص مهذّب للمستخدم
            "reason_code": reason_code,
        }
        wnd = {}
        if start is not None: wnd["from"] = start
        if end   is not None: wnd["to"]   = end
        if now   is not None: wnd["now"]  = now
        if wnd: payload["window"] = wnd
        if extra: payload.update(extra)
        # نرجع 200 حتى لا يظهر "HTTP 400" في التطبيق
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        ser = AttendanceCheckSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            # أخطاء إدخال (حقول ناقصة/قيمة غير صالحة) — نعيد 200 برسالة لطيفة أيضاً
            return Response({
                "ok": False, "performed": False,
                "action": request.data.get("action"),
                "detail": "تعذر معالجة الطلب. الرجاء التحقق من الحقول المدخلة.",
                "errors": ser.errors
            }, status=status.HTTP_200_OK)

        action   = ser.validated_data["action"]
        employee = ser.validated_data["employee"]
        location = ser.validated_data["location_obj"]
        lat      = ser.validated_data["lat"]
        lng      = ser.validated_data["lng"]
        acc      = ser.validated_data.get("accuracy")
        dist     = ser.validated_data.get("distance_m")

        # الوقت الحالي للتطبيق: نحفظ كل من التوقيت العام والتوقيت المحلي
        now       = dj_timezone.now()
        now_local = dj_timezone.localtime(now)

        start_dt = ser.validated_data.get("shift_window_start")
        end_dt   = ser.validated_data.get("shift_window_end")
        blocked  = ser.validated_data.get("blocked")
        reason   = ser.validated_data.get("blocked_reason")

        # لو الـ serializer قرر المنع، نرجع رسالة فقط بدون تنفيذ
        if blocked:
            return self._deny(
                action=action,
                detail=reason or "⚠️ لا يمكن تنفيذ العملية في الوقت الحالي.",
                reason_code="business_rule_violation",
                start=start_dt, end=end_dt, now=now_local
            )

        # ===== تنفيذ العمليات =====
        if action == "check_in":
            # تأكد من عدم وجود تسجيل حضور سابق في نفس اليوم (لمنع تكرار الحضور في الوردية)
            # نحسب بداية ونهاية اليوم المحلي الحالي
            try:
                today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                today_end   = today_start + timedelta(days=1)
                existing = AttendanceRecord.objects.filter(
                    employee=employee,
                    check_in_time__gte=today_start,
                    check_in_time__lt=today_end
                ).exists()
                if existing:
                    return self._deny(
                        action=action,
                        detail="⚠️ تم تسجيل حضور مسبقًا اليوم، لا يمكن تسجيل حضور آخر في نفس الوردية.",
                        reason_code="already_checked_in_today",
                        start=start_dt, end=end_dt, now=now_local
                    )
            except Exception:
                pass

            # تحقق من عدم وجود تسجيل حضور لنفس الوردية (نفس الشيفت) حتى لا يحدث أكثر من حضور في الوردية الواحدة
            try:
                current_shift = ser.validated_data.get("current_shift")
                if current_shift is not None:
                    exists_for_shift = AttendanceRecord.objects.filter(
                        employee=employee,
                        shift=current_shift
                    ).exists()
                    if exists_for_shift:
                        return self._deny(
                            action=action,
                            detail="⚠️ تم تسجيل حضور لهذه الوردية مسبقًا، لا يمكن تسجيل حضور آخر لنفس الوردية.",
                            reason_code="already_checked_in_shift",
                            start=start_dt, end=end_dt, now=now_local
                        )
            except Exception:
                pass
            # إذا كان هناك سجل حضور مفتوح مسبقًا فلا يُسمح بتسجيل حضور جديد
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

            rec = ser.save()  # إنشاء سجل الحضور
            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل حضورك بنجاح.",
                "note": ("الوردية غير مقيّدة زمنيًا."
                         if start_dt is None and end_dt is None
                         else (f"الفترة المسموحة للحضور: {start_dt.strftime('%H:%M')} → {end_dt.strftime('%H:%M')}" if start_dt and end_dt else "")),
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(location.id) if getattr(location, "id", None) else None,
                "location_name": getattr(location, "name", None),
            }, status=status.HTTP_201_CREATED)

        elif action == "check_out":
            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(action=action, detail="لا يوجد سجل حضور مفتوح لإقفاله.", reason_code="no_open_record")

            # نحفظ وقت الانصراف بالتوقيت المحلي لضمان توافقه مع عرض الواجهة
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
            reason_txt = (request.data.get("early_reason") or "").strip()
            file_obj = request.FILES.get("early_attachment")
            if not reason_txt:
                return self._deny(action=action, detail="يجب كتابة سبب الانصراف المبكر.", reason_code="early_checkout_reason_required")

            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(action=action, detail="لا يوجد سجل حضور مفتوح لإقفاله.", reason_code="no_open_record")

            # نحفظ وقت الانصراف بالتوقيت المحلي لضمان توافقه مع عرض الواجهة
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

        # إجراء غير مدعوم
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
            "location_id": str(loc.id),  # UUID كنص
            "name": loc.name,
            "client_name": loc.client_name,
            "lat": la, "lng": ln,
            "radius": float(loc.gps_radius),
            "distance": round(dist, 2),
            "mode": mode,  # polygon | radius
        }
        return Response(data, status=200)

