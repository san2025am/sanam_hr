from __future__ import annotations

import json
import re
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone as dj_timezone
from django.db.models import Q

from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

# ========================
# محاولات لاستخدام أدوات هندسية جاهزة؛ مع بدائل داخلية
# ========================
try:
    from .utils.geo import haversine_m as _hv, point_in_polygon as _pip
except Exception:
    _hv = None
    _pip = None

def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    if _hv:
        return _hv(lat1, lon1, lat2, lon2)
    # fallback بسيط
    from math import radians, sin, cos, asin, sqrt
    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def _point_in_polygon(point, polygon) -> bool:
    if _pip:
        return _pip(point, polygon)
    # fallback (ray casting)
    x, y = point
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if min(p1y, p2y) < y <= max(p1y, p2y) and x <= max(p1x, p2x):
            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y + 1e-12) + p1x
            if p1x == p2x or x <= xinters:
                inside = not inside
        p1x, p1y = p2x, p2y
    return inside


from .models import (
    Role, User, Employee, Location, EmployeeLocationAssignment, Task, Shift,
    AttendanceRecord, Salary, Report, ReportAttachment, Request,
    ViolationRule, EmployeeViolation, Contract, Advance, Custody,
    UniformItem, UniformDelivery, UniformDeliveryItem, PasswordResetSMS,
    EmployeeShiftAssignment,
)

User = get_user_model()

# =========================
# Auth / Guard login
# =========================

GUARD_ROLE_NAMES = {"حارس أمن", "حارس الامن", "Security Guard", "Guard", "guard"}

class GuardTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT فقط إذا كان الدور حارس أمن"""
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        role_name = (user.role.name if getattr(user, "role", None) else "").strip()
        if role_name.casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            raise AuthenticationFailed(
                "الحساب ليس له دور حارس أمن، لا يمكن تسجيل الدخول من تطبيق الحارس.",
                code="not_guard"
            )
        data.update({"user": {"id": user.id, "username": user.username, "role": role_name}})
        return data

# =========================
# Forgot / Reset via Username + Email
# =========================

def _hash_code(code: str) -> str:
    import hashlib as _h
    return _h.sha256(code.encode()).hexdigest()

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

class UsernameForgotSerializer(serializers.Serializer):
    """يستقبل اسم المستخدم → يعثر على الحساب → يرسل كود إلى user.email"""
    username = serializers.CharField()

    def validate(self, attrs):
        uname = attrs["username"].strip()
        try:
            user = User.objects.select_related("role").get(username__iexact=uname)
        except User.DoesNotExist:
            raise serializers.ValidationError({"username": "لا يوجد مستخدم بهذا الاسم"})

        if not user.is_active:
            raise serializers.ValidationError({"detail": "الحساب غير مُفعل"})
        if not (user.email and user.email.strip()):
            raise serializers.ValidationError({"detail": "لا يوجد بريد إلكتروني مرتبط بهذا الحساب"})

        code = f"{secrets.randbelow(1_000_000):06d}"
        phone_val = getattr(getattr(user, "employee", None), "phone_number", "") or ""
        rec = PasswordResetSMS.objects.create(
            user=user,
            phone=phone_val,
            code_hash=_hash_code(code),
            expires_at=dj_timezone.now() + timedelta(minutes=10),
        )

        subject = "رمز استعادة كلمة المرور - سنام الأمن"
        body = f"رمز استعادة كلمة المرور الخاص بك هو: {code}\nصالح لمدة 10 دقائق.\n"
        try:
            from .emailer import send_email_otp
            send_email_otp(user.email, subject, body)
        except Exception:
            from django.conf import settings
            if getattr(settings, "DEBUG_SMS_ECHO", False):
                attrs["session_id"] = rec.id
                attrs["_debug_code"] = code
                return attrs
            raise serializers.ValidationError({"detail": "تعذر إرسال البريد الإلكتروني، حاول لاحقًا"})

        attrs["session_id"] = rec.id
        return attrs

class UsernameResetSerializer(serializers.Serializer):
    """التحقق من الكود وتغيير كلمة المرور"""
    session_id = serializers.IntegerField()
    code = serializers.CharField(min_length=4, max_length=6)
    new_password = serializers.CharField(min_length=6)

    def validate(self, attrs):
        sid = attrs["session_id"]; code = attrs["code"]
        try:
            rec = PasswordResetSMS.objects.select_related("user").get(id=sid, is_used=False)
        except PasswordResetSMS.DoesNotExist:
            raise serializers.ValidationError({"detail": "الجلسة غير صالحة"})

        if rec.expires_at and rec.expires_at < dj_timezone.now():
            raise serializers.ValidationError({"detail": "انتهت صلاحية الرمز"})
        if rec.attempts >= 5:
            raise serializers.ValidationError({"detail": "تجاوزت عدد المحاولات"})

        rec.attempts += 1
        rec.save(update_fields=["attempts"])

        if rec.code_hash != _hash_code(code):
            raise serializers.ValidationError({"code": "رمز غير صحيح"})

        attrs["record"] = rec
        return attrs

    def save(self, **kwargs):
        rec: PasswordResetSMS = self.validated_data["record"]
        user = rec.user
        user.set_password(self.validated_data["new_password"])
        user.save()
        rec.is_used = True
        rec.save(update_fields=["is_used"])
        return user

# =========================
# EmployeeMe payload (للجوال)
# =========================

class TaskMiniSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)
    class Meta:
        model = Task
        fields = ["id", "title", "description", "status", "due_date", "location_name"]

class ShiftAssignmentMiniSerializer(serializers.ModelSerializer):
    shift_name    = serializers.CharField(source="shift.name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    start_time = serializers.SerializerMethodField()
    end_time   = serializers.SerializerMethodField()
    checkin_grace        = serializers.IntegerField(read_only=True)
    checkout_grace       = serializers.IntegerField(read_only=True)
    checkout_grace_hours = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True)
    unrestricted         = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeShiftAssignment
        fields = [
            "id", "date", "shift_name", "location_name",
            "start_time", "end_time",
            "checkin_grace", "checkout_grace", "checkout_grace_hours",
            "unrestricted", "active", "notes",
        ]

    def get_start_time(self, obj):
        return (obj.start_time or getattr(obj.shift, "start_time", None))

    def get_end_time(self, obj):
        return (obj.end_time or getattr(obj.shift, "end_time", None))

    def get_unrestricted(self, obj):
        return (obj.checkin_grace is None
                and obj.checkout_grace is None
                and obj.checkout_grace_hours is None)

class LocationMiniSerializer(serializers.ModelSerializer):
    instructions = serializers.CharField(source="instructions", allow_null=True, required=False)
    class Meta:
        model = Location
        fields = ["id", "name", "client_name", "instructions"]

class SalaryMiniSerializer(serializers.ModelSerializer):
    base_salary  = serializers.SerializerMethodField()
    bonuses      = serializers.SerializerMethodField()
    overtime     = serializers.SerializerMethodField()
    deductions   = serializers.SerializerMethodField()
    total_salary = serializers.SerializerMethodField()
    class Meta:
        model  = Salary
        fields = ["base_salary", "bonuses", "overtime", "deductions", "total_salary", "pay_date"]
    def _as_str(self, v): return None if v is None else str(v)
    def get_base_salary (self, o): return self._as_str(getattr(o, "base_salary",  None))
    def get_bonuses     (self, o): return self._as_str(getattr(o, "bonuses",      None))
    def get_overtime    (self, o): return self._as_str(getattr(o, "overtime",     None))
    def get_deductions  (self, o): return self._as_str(getattr(o, "deductions",   None))
    def get_total_salary(self, o): return self._as_str(getattr(o, "total_salary", None))

class EmployeeMeSerializer(serializers.ModelSerializer):
    username   = serializers.CharField(source="user.username", read_only=True)
    email      = serializers.EmailField(source="user.email",   read_only=True, allow_null=True)
    role       = serializers.CharField(source="user.role.name", read_only=True, allow_null=True)
    role_label = serializers.SerializerMethodField()
    locations  = serializers.SerializerMethodField()
    salary     = serializers.SerializerMethodField()

    id_expiry_date          = serializers.DateField(read_only=True, allow_null=True)
    date_of_birth_gregorian = serializers.DateField(read_only=True, allow_null=True)
    employee_instructions   = serializers.CharField(source="instructions", read_only=True, allow_blank=True, allow_null=True)
    location_instructions   = serializers.SerializerMethodField()
    supervisor_name         = serializers.SerializerMethodField()
    supervisor_phone        = serializers.SerializerMethodField()

    tasks  = serializers.SerializerMethodField()
    shifts = serializers.SerializerMethodField()
    shift_assignments = serializers.SerializerMethodField()

    class Meta:
        model  = Employee
        fields = [
            "id", "username", "email", "role", "role_label",
            "full_name", "national_id", "phone_number",
            "hire_date", "bank_name", "bank_account",
            "id_expiry_date", "date_of_birth_gregorian",
            "employee_instructions", "location_instructions",
            "supervisor_name", "supervisor_phone",
            "locations", "salary", "tasks", "shifts",
            "shift_assignments",
        ]

    def get_shift_assignments(self, obj):
        qs = obj.shift_assignments.select_related("shift", "location").filter(active=True)
        return ShiftAssignmentMiniSerializer(qs, many=True).data

    def get_role_label(self, obj):
        return str(getattr(obj.user, "role", "")) or None

    def get_locations(self, obj):
        qs = EmployeeLocationAssignment.objects.select_related("location").filter(employee=obj)
        out = []
        for a in qs:
            if a.location:
                out.append({
                    "id": a.location.id,
                    "name": a.location.name,
                    "client_name": getattr(a.location, "client_name", "") or "",
                    "instructions": getattr(a.location, "instructions", "") or "",
                })
        return out

    def get_salary(self, obj):
        last = Salary.objects.filter(employee=obj).order_by("-pay_date", "-id").first()
        return SalaryMiniSerializer(last).data if last else {
            "base_salary": None, "bonuses": None, "overtime": None,
            "deductions": None, "total_salary": None, "pay_date": None
        }

    def get_location_instructions(self, obj):
        qs = EmployeeLocationAssignment.objects.filter(employee=obj).select_related("location")
        return [getattr(a.location, "instructions", "") or "" for a in qs if a.location]

    def get_supervisor_name(self, obj):
        return getattr(obj.supervisor, "full_name", None) if obj.supervisor else None

    def get_supervisor_phone(self, obj):
        return getattr(obj.supervisor, "phone_number", None) if obj.supervisor else None

    def get_tasks(self, obj):
        tasks_qs = Task.objects.filter(assigned_to=obj).select_related("location").order_by("-due_date", "-id")
        return TaskMiniSerializer(tasks_qs, many=True).data

    def get_shifts(self, obj):
        qs = (EmployeeShiftAssignment.objects
              .filter(employee=obj)
              .select_related("shift", "location")
              .order_by("-date", "-id"))
        out = []
        for a in qs:
            sh = a.shift
            start = getattr(a, "start_time", None) or (getattr(sh, "start_time", None) if sh else None)
            end   = getattr(a, "end_time",   None) or (getattr(sh, "end_time",   None) if sh else None)
            out.append({
                "id": a.id,
                "date": a.date.isoformat() if a.date else None,
                "shift_name": getattr(sh, "name", "") or "",
                "location_name": getattr(a.location, "name", "") or "",
                "start_time": start.strftime("%H:%M") if start else None,
                "end_time":   end.strftime("%H:%M")   if end   else None,
                "active": bool(getattr(a, "is_active", getattr(a, "active", True))),
                "notes": a.notes or "",
            })
        return out


# =========================
# Attendance / Resolve
# =========================


class AttendanceCheckSerializer(serializers.Serializer):
    location_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    action = serializers.ChoiceField(choices=[
        ("check_in", "check_in"),
        ("check_out", "check_out"),
        ("early_check_out", "early_check_out"),
    ])
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    accuracy = serializers.FloatField(required=False, min_value=0, default=9999)

    # ===== أدوات مساعدة هندسية =====
    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        from math import radians, sin, cos, asin, sqrt
        R = 6371000.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return R * c

    @staticmethod
    def _point_in_polygon(point, polygon):
        x, y = point
        inside = False
        n = len(polygon)
        if n < 3:
            return False
        p1x, p1y = polygon[0]
        for i in range(1, n + 1):
            p2x, p2y = polygon[i % n]
            if min(p1y, p2y) < y <= max(p1y, p2y) and x <= max(p1x, p2x):
                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y + 1e-12) + p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
            p1x, p1y = p2x, p2y
        return inside

    @staticmethod
    def _anchor_times(now_local, start_t, end_t, anchor_date=None):
        """إرجاع (start_dt, end_dt) مع دعم الوردية الليلية."""
        if anchor_date is None:
            base = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            base = now_local.replace(year=anchor_date.year, month=anchor_date.month, day=anchor_date.day,
                                     hour=0, minute=0, second=0, microsecond=0)
        start_dt = base.replace(hour=start_t.hour, minute=start_t.minute)
        end_dt   = base.replace(hour=end_t.hour,   minute=end_t.minute)
        if end_t <= start_t:
            end_dt += timedelta(days=1)
        return start_dt, end_dt

    # ===== التحقق =====
    def validate(self, attrs):
        request = self.context["request"]
        user    = request.user

        # الموظف
        try:
            employee = Employee.objects.get(user=user)
        except Employee.DoesNotExist:
            raise serializers.ValidationError("لا يوجد ملف موظف مرتبط بهذا الحساب.")

        # الموقع
        try:
            location = Location.objects.get(id=attrs["location_id"])
        except Location.DoesNotExist:
            raise serializers.ValidationError({"location_id": "الموقع غير موجود أو مُعرّف غير صالح."})

        lat = attrs["lat"]; lng = attrs["lng"]
        acc = attrs.get("accuracy", 9999.0)
        action = (attrs.get("action") or "").strip().lower()

        # ===== فحص الهوية =====
        today = dj_timezone.localdate()
        if getattr(employee, "id_expiry_date", None):
            if employee.id_expiry_date < today:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ لا يمكن التسجيل: الهوية منتهية.",
                })
                return attrs

        # ===== فحص العقد (موجود + موقّع + نشِط) =====
        contracts_qs = Contract.objects.filter(employee=employee)
        if not contracts_qs.exists():
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ لا يمكن التسجيل: لا يوجد عقد.",
            })
            return attrs

        if contracts_qs.filter(is_signed=False).exists():
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ لا يمكن التسجيل: يوجد عقد غير موقَّع. يرجى استكمال التوقيع.",
            })
            return attrs

        has_active_signed = contracts_qs.filter(
            is_signed=True
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        ).exists()
        if not has_active_signed:
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ لا يمكن التسجيل: لا يوجد عقد نشط.",
            })
            return attrs

        # ===== فحص الموقع (دقة/مضلّع/نصف قطر) =====
        if getattr(location, "gps_radius", None):
            try:
                if acc > float(location.gps_radius):
                    attrs.update({
                        "employee": employee, "location_obj": location,
                        "blocked": True,
                        "blocked_reason": "⚠️ دقة تحديد الموقع ضعيفة. اقترب من الموقع وحاول مجددًا.",
                    })
                    return attrs
            except (TypeError, ValueError):
                pass

        inside_polygon = None
        if getattr(location, "use_polygon", False) and getattr(location, "polygon_coords", None):
            try:
                poly = location.polygon_coords
                polygon = [(float(p[0]), float(p[1])) for p in poly]
                inside_polygon = self._point_in_polygon((lat, lng), polygon)
            except Exception:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ تنسيق حدود الموقع غير صالح. راجع الإدارة.",
                })
                return attrs
            if not inside_polygon:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ أنت خارج حدود الموقع المحددة.",
                })
                return attrs

        if not (getattr(location, "use_polygon", False) and inside_polygon):
            if not getattr(location, "gps_coordinates", None):
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ لم تُعرّف إحداثيات الموقع.",
                })
                return attrs
            try:
                loc_lat, loc_lng = [float(x.strip()) for x in location.gps_coordinates.split(",", 1)]
            except Exception:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ تنسيق إحداثيات الموقع غير صحيح.",
                })
                return attrs
            dist = self._haversine_m(lat, lng, loc_lat, loc_lng)
            attrs["distance_m"] = dist
            try:
                radius = float(location.gps_radius)
            except Exception:
                radius = 0.0
            if radius and dist > radius:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": f"⚠️ خارج النطاق المسموح ({int(radius)}م). المسافة الحالية: {int(round(dist))}م.",
                })
                return attrs

        # ===== حساب نافذة الوردية =====
        now_aware = dj_timezone.now()
        now_local = dj_timezone.localtime(now_aware)

        current_shift = None
        allowed_start = allowed_end = None

        assign_qs = (EmployeeShiftAssignment.objects
                     .select_related("shift", "location")
                     .filter(employee=employee, active=True)
                     .order_by("-date", "-start_time", "-end_time"))

        for a in assign_qs:
            sh = getattr(a, "shift", None)
            if not sh:
                continue

            start_t = getattr(a, "start_time", None) or getattr(sh, "start_time", None)
            end_t   = getattr(a, "end_time",   None) or getattr(sh, "end_time",   None)
            if not (start_t and end_t):
                continue

            # لو التعيين مرتبط بموقع محدد تأكد أنه نفس الموقع
            if getattr(a, "location_id", None) and a.location_id != location.id:
                continue

            anchor = getattr(a, "date", None) or None
            start_dt, end_dt = self._anchor_times(now_local, start_t, end_t, anchor_date=anchor)

            # يجب أن يغطي الوقت الحالي
            try:
                if not (start_dt <= now_local <= end_dt):
                    continue
            except Exception:
                continue

            ok = False
            win_l = win_r = None

            unrestricted = (
                a.checkin_grace is None and
                a.checkout_grace is None and
                a.checkout_grace_hours is None
            )

            if unrestricted:
                ok = True
                win_l = None
                win_r = None
            else:
                if action == "check_in":
                    grace_min = int(a.checkin_grace or 0)
                    win_l = start_dt
                    win_r = start_dt + timedelta(minutes=grace_min)
                    ok = (win_l <= now_local <= win_r)
                elif action in ("check_out", "early_check_out"):
                    # الانصراف العادي: بعد السماح | الانصراف المبكر: سيتحقق لاحقاً من الحضور أولاً
                    if a.checkout_grace_hours is not None:
                        threshold_min = int(round(float(a.checkout_grace_hours) * 60))
                    elif a.checkout_grace is not None:
                        threshold_min = int(a.checkout_grace)
                    else:
                        threshold_min = 0
                    earliest = start_dt + timedelta(minutes=threshold_min)
                    win_l, win_r = earliest, None
                    ok = (now_local >= earliest) if action == "check_out" else True

            if not ok:
                if action == "check_in":
                    reason = (f"⚠️ لا يمكن تسجيل الحضور الآن. "
                              f"فترة السماح انتهت عند {(start_dt + timedelta(minutes=int(a.checkin_grace or 0))).strftime('%H:%M')}.")
                else:
                    if a.checkout_grace_hours is not None:
                        reason = f"⚠️ لا يمكن تسجيل الانصراف قبل مرور {a.checkout_grace_hours} ساعة من بداية الوردية."
                    elif a.checkout_grace is not None:
                        reason = f"⚠️ لا يمكن تسجيل الانصراف قبل مرور {a.checkout_grace} دقيقة من بداية الوردية."
                    else:
                        reason = "⚠️ الانصراف غير مسموح في الوقت الحالي."
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True, "blocked_reason": reason,
                    "shift_window_start": win_l, "shift_window_end": win_r,
                    "current_shift": sh,
                })
                return attrs

            current_shift, allowed_start, allowed_end = sh, win_l, win_r
            break

        if current_shift is None:
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ خارج أوقات الوردية الحالية. يرجى مراجعة المشرف.",
                "shift_window_start": None, "shift_window_end": None,
                "current_shift": None,
            })
            return attrs

        # ===== قيود إضافية خاصة بالأفعال =====
        # منع الحضور مرتين في نفس اليوم
        if action == "check_in":
            day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + timedelta(days=1)
            if AttendanceRecord.objects.filter(
                employee=employee,
                check_in_time__gte=day_start,
                check_in_time__lt=day_end
            ).exists():
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ تم تسجيل حضور مسبقًا اليوم.",
                    "current_shift": current_shift,
                    "shift_window_start": allowed_start, "shift_window_end": allowed_end,
                })
                return attrs

        # الانصراف المبكر: يجب أن يوجد سجل مفتوح + لم يُسجّل مبكرًا اليوم
        if action == "early_check_out":
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time").first())
            if not open_rec:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ لا يمكن الانصراف المبكر قبل تسجيل الحضور.",
                })
                return attrs

            # مرة واحدة في اليوم
            day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + timedelta(days=1)
            if AttendanceRecord.objects.filter(
                employee=employee,
                early_checkout=True,
                check_out_time__gte=day_start,
                check_out_time__lt=day_end
            ).exists():
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ تم تسجيل انصراف مبكر مرة اليوم.",
                })
                return attrs

        attrs.update({
            "employee": employee,
            "location_obj": location,
            "current_shift": current_shift,
            "shift_window_start": allowed_start,
            "shift_window_end": allowed_end,
            "blocked": False,
            "blocked_reason": None,
            "now_local": now_local,
        })
        return attrs

    def create(self, validated_data):
        """يُنشئ سجل الحضور عند check_in فقط."""
        if validated_data["action"] != "check_in":
            return None

        now_local = validated_data.get("now_local") or dj_timezone.localtime(dj_timezone.now())
        rec = AttendanceRecord.objects.create(
            employee=validated_data["employee"],
            location=validated_data["location_obj"],
            shift=validated_data.get("current_shift"),
            check_in_time=now_local,
            notes=(
                f"in lat={validated_data['lat']}, lng={validated_data['lng']}, "
                f"acc={validated_data.get('accuracy')}, "
                f"dist={round(validated_data.get('distance_m') or 0.0, 2)}"
            ),
        )
        return rec

class ResolveLocationSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    accuracy = serializers.FloatField(required=False, min_value=0, default=9999)

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        try:
            employee = Employee.objects.get(user=user)
        except Employee.DoesNotExist:
            raise serializers.ValidationError({"detail": "لا يوجد ملف موظف مرتبط بهذا الحساب."})
        attrs["employee"] = employee
        return attrs

    def find_best_location(self, employee: Employee, lat: float, lng: float):
        qs = Location.objects.filter(assigned_employees=employee)
        best = None  # (loc, distance_m, mode)

        for loc in qs:
            # polygon أولاً
            if getattr(loc, "use_polygon", False) and loc.polygon_coords:
                try:
                    poly = loc.polygon_coords
                    if isinstance(poly, str):
                        poly = json.loads(poly)
                    polygon = [(float(p[0]), float(p[1])) for p in poly]
                    if _point_in_polygon((lat, lng), polygon):
                        return loc, 0.0, "polygon"
                except Exception:
                    pass

            # دائرة نصف قطر
            if loc.gps_coordinates:
                try:
                    la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
                except Exception:
                    continue
                dist = _haversine_m(lat, lng, la, ln)
                if dist <= float(loc.gps_radius):
                    if (best is None) or (dist < best[1]):
                        best = (loc, dist, "radius")

        return best
<<<<<<< HEAD
=======


class ReportAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = ReportAttachment
        fields = ["id", "file", "file_url", "file_type", "uploaded_at"]
        read_only_fields = ["id", "file", "file_url", "file_type", "uploaded_at"]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url


class ReportSerializer(serializers.ModelSerializer):
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), allow_null=True, required=False
    )
    location_name = serializers.CharField(source="location.name", read_only=True)
    report_type_display = serializers.CharField(source="get_report_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    attachments = ReportAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Report
        fields = [
            "id",
            "report_type",
            "report_type_display",
            "description",
            "status",
            "status_display",
            "created_at",
            "closed_at",
            "location",
            "location_name",
            "attachments",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "created_at",
            "closed_at",
            "location_name",
            "attachments",
        ]


class RequestSerializer(serializers.ModelSerializer):
    request_type_display = serializers.CharField(source="get_request_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    approver_name = serializers.CharField(source="approver.full_name", read_only=True)

    class Meta:
        model = Request
        fields = [
            "id",
            "request_type",
            "request_type_display",
            "description",
            "status",
            "status_display",
            "approval_notes",
            "approver_name",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "approval_notes",
            "approver_name",
            "created_at",
        ]
>>>>>>> ab2c0cb (التقارير والطلبات)
