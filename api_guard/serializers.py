from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone as dj_timezone
from django.db import transaction
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
    AttendanceRecord, Salary, Report, ReportAttachment, Request, Advance,
    ViolationRule, EmployeeViolation, Contract, Custody,
    UniformItem, UniformDelivery, UniformDeliveryItem, PasswordResetSMS,
    EmployeeShiftAssignment, GeofenceViolationPause,
    UniformItem, UniformDelivery, UniformDeliveryItem,
    ReportMessage,
    LocationPing,
)

User = get_user_model()

_TASK_STATUS_FLOW = ['new', 'accepted', 'in_progress', 'completed']

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
            from core.emailer import send_email_otp
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
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    status_note = serializers.CharField(read_only=True, allow_null=True)
    next_status = serializers.SerializerMethodField()
    next_status_label = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "status",
            "status_label",
            "status_note",
            "next_status",
            "next_status_label",
            "due_date",
            "location_name",
        ]

    def get_next_status(self, obj):
        try:
            idx = _TASK_STATUS_FLOW.index(obj.status)
        except ValueError:
            return None
        if idx + 1 < len(_TASK_STATUS_FLOW):
            return _TASK_STATUS_FLOW[idx + 1]
        return None

    def get_next_status_label(self, obj):
        next_status = self.get_next_status(obj)
        if not next_status:
            return None
        return dict(Task.STATUS_CHOICES).get(next_status)


class GuardTaskUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[choice[0] for choice in Task.STATUS_CHOICES])
    status_note = serializers.CharField(required=False, allow_blank=True, allow_null=True)

class ShiftAssignmentMiniSerializer(serializers.ModelSerializer):
    shift_name    = serializers.CharField(source="shift.name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    location_id   = serializers.CharField(read_only=True, allow_null=True)
    start_time = serializers.SerializerMethodField()
    end_time   = serializers.SerializerMethodField()
    checkin_grace        = serializers.IntegerField(read_only=True)
    checkout_grace       = serializers.IntegerField(read_only=True)
    checkout_grace_hours = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True)
    pre_shift_buffer_minutes  = serializers.IntegerField(read_only=True)
    post_shift_buffer_minutes = serializers.IntegerField(read_only=True)
    unrestricted         = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeShiftAssignment
        fields = [
            "id", "date", "shift_name", "location_name", "location_id",
            "start_time", "end_time",
            "checkin_grace", "checkout_grace", "checkout_grace_hours",
            "pre_shift_buffer_minutes", "post_shift_buffer_minutes",
            "unrestricted", "active", "notes",
        ]

    def get_start_time(self, obj):
        value = obj.start_time or getattr(obj.shift, "start_time", None)
        return value.strftime("%H:%M") if value else None

    def get_end_time(self, obj):
        value = obj.end_time or getattr(obj.shift, "end_time", None)
        return value.strftime("%H:%M") if value else None

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
    badge_code              = serializers.CharField(read_only=True, allow_null=True)
    profile_photo_url       = serializers.SerializerMethodField()

    tasks  = serializers.SerializerMethodField()
    shifts = serializers.SerializerMethodField()
    shift_assignments = serializers.SerializerMethodField()
    # إضافات: قائمة المخالفات وخلاصة تفصيلية للخصومات
    violations = serializers.SerializerMethodField()
    salary_deduction_details = serializers.SerializerMethodField()
    # حقول إضافية للحساب البنكي للمستفيد والإقامة
    beneficiary_name = serializers.CharField(read_only=True, allow_null=True)
    beneficiary_bank_name = serializers.CharField(read_only=True, allow_null=True)
    beneficiary_iban = serializers.CharField(read_only=True, allow_null=True)
    beneficiary_relation = serializers.CharField(read_only=True, allow_null=True)
    residency_number = serializers.CharField(read_only=True, allow_null=True)
    residency_issue_date = serializers.DateField(read_only=True, allow_null=True)
    residency_expiry_date = serializers.DateField(read_only=True, allow_null=True)

    class Meta:
        model  = Employee
        fields = [
            "id", "username", "email", "role", "role_label",
            "full_name", "national_id", "phone_number",
            "hire_date", "bank_name", "bank_account",
            "beneficiary_name", "beneficiary_bank_name", "beneficiary_iban", "beneficiary_relation",
            "residency_number", "residency_issue_date", "residency_expiry_date",
            "id_expiry_date", "date_of_birth_gregorian",
            "employee_instructions", "location_instructions",
            "supervisor_name", "supervisor_phone",
            "locations", "salary", "tasks", "shifts",
            "shift_assignments", "violations", "salary_deduction_details",
            "badge_code", "profile_photo_url",
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

    def get_profile_photo_url(self, obj):
        photo = getattr(obj, 'profile_photo', None)
        if not photo:
            return None
        try:
            request = self.context.get('request')
        except Exception:
            request = None
        url = photo.url if hasattr(photo, 'url') else None
        if not url:
            return None
        if request is not None:
            try:
                return request.build_absolute_uri(url)
            except Exception:
                return url
        return url

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
                "pre_shift_buffer_minutes": getattr(a, "pre_shift_buffer_minutes", 0),
                "post_shift_buffer_minutes": getattr(a, "post_shift_buffer_minutes", 0),
            })
        return out

    def _dec_str(self, value) -> str | None:
        if value in (None, ""):
            return None
        try:
            from decimal import Decimal, ROUND_HALF_UP
            d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return format(d.normalize(), "f")
        except Exception:
            return str(value)

    def get_violations(self, obj):
        qs = (EmployeeViolation.objects
              .filter(employee=obj)
              .select_related("rule", "location")
              .order_by("-occurred_at"))
        out = []
        for v in qs:
            out.append({
                "id": v.id,
                "rule_title": getattr(v.rule, "title", "") or "",
                "description": v.description or "",
                "occurred_at": v.occurred_at.isoformat() if v.occurred_at else None,
                "status": v.status,
                "deduction_value": self._dec_str(getattr(v, "deduction_value", None)),
                "location_name": getattr(v.location, "name", None),
            })
        return out

    def get_salary_deduction_details(self, obj):
        """
        تُرجع قائمة تفصيلية لمصادر الخصومات: مخالفات/سلف/نموذج زي.
        الحقول: {source, reason, amount, date, reference_id, reference_label}
        """
        items: list[dict] = []

        # 1) مخالفات برصيد خصم
        vio_qs = (EmployeeViolation.objects
                  .filter(employee=obj)
                  .select_related("rule")
                  .order_by("-occurred_at"))
        for v in vio_qs:
            try:
                amt = getattr(v, "deduction_value", None)
                if amt is None:
                    continue
                # تجاهل الصفر أو السالب
                from decimal import Decimal
                if Decimal(str(amt)) <= Decimal("0"):
                    continue
            except Exception:
                pass
            items.append({
                "source": "violation",
                "reason": getattr(v.rule, "title", "") or (v.description or "مخالفة"),
                "amount": self._dec_str(getattr(v, "deduction_value", None)),
                "date": v.occurred_at.isoformat() if v.occurred_at else None,
                "reference_id": v.id,
                "reference_label": f"Violation #{v.id}",
            })

        # 2) سلف معتمدة (تُضاف للخصومات وفق الإشارة)
        adv_qs = (Advance.objects
                  .filter(employee=obj, status='approved')
                  .order_by("-approved_at", "-created_at"))
        for a in adv_qs:
            items.append({
                "source": "advance",
                "reason": (a.reason or "سلفة معتمدة"),
                "amount": self._dec_str(a.amount),
                "date": (a.approved_at or a.created_at).isoformat() if (a.approved_at or a.created_at) else None,
                "reference_id": a.id,
                "reference_label": f"Advance #{a.id}",
            })

        # 3) زي رسمي مدفوع بالخصم ومغلق
        uni_qs = (UniformDelivery.objects
                  .filter(employee=obj, is_finalized=True, payment_method='deduction')
                  .order_by("-delivery_date", "-id"))
        for u in uni_qs:
            items.append({
                "source": "uniform",
                "reason": "خصم قيمة زي رسمي",
                "amount": self._dec_str(u.total_value),
                "date": u.delivery_date.isoformat() if u.delivery_date else None,
                "reference_id": u.id,
                "reference_label": f"Uniform #{u.id}",
            })

        # ترتيب تنازلي بالتاريخ إن أمكن
        def _key(x):
            return x.get("date") or ""
        try:
            items.sort(key=_key, reverse=True)
        except Exception:
            pass
        return items


# =========================
# Attendance / Resolve
# =========================


class AttendanceCheckSerializer(serializers.Serializer):
    # نقبل location_id كنص/رقم، ونسمح أيضًا بحقل بديل "location"
    location_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    location = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    action = serializers.ChoiceField(choices=[
        ("check_in", "check_in"),
        ("check_out", "check_out"),
        ("early_check_out", "early_check_out"),
    ])
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    accuracy = serializers.FloatField(required=False, min_value=0, default=9999)
    provider = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_mock = serializers.BooleanField(required=False, default=False)
    location_age_ms = serializers.IntegerField(required=False, allow_null=True)
    integrity_verdict = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    integrity_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    # مفاتيح البصمة القديمة/الجديدة
    biometric_verified = serializers.BooleanField(required=False, default=False)
    biometric_method = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    biometric_attempts = serializers.IntegerField(required=False, min_value=0, default=0)
    bio_ok = serializers.BooleanField(required=False)              # بديل قديم
    bio_method = serializers.CharField(required=False, allow_blank=True, allow_null=True)  # بديل قديم

    # ===== أدوات مساعدة هندسية (كما لديك) =====
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
        """
        إرجاع (start_dt, end_dt) وفق القاعدة:
        - إذا كانت الوردية تعبر منتصف الليل (end_t < start_t) فاليوم المرجعي D هو يوم البداية دائمًا.
        - عند عدم تحديد anchor_date نختار D تلقائيًا:
          • إذا now_local.time() < end_t (في ساعات الصباح قبل نهاية الوردية الليلية) ⇒ D = تاريخ اليوم السابق.
          • خلاف ذلك ⇒ D = تاريخ now_local.
        - تُضاف يوم واحد لنهاية الوردية الليلية.
        """
        if anchor_date is None:
            base_date = now_local.date()
            if end_t <= start_t:
                # overnight: لو نحن قبل end_t صباحًا، انسبها لليوم السابق D
                try:
                    current_t = now_local.timetz() if hasattr(now_local, 'timetz') else now_local.time()
                except Exception:
                    current_t = now_local.time()
                if current_t < end_t:
                    from datetime import timedelta as _td
                    base_date = base_date - _td(days=1)
        else:
            base_date = anchor_date

        base = now_local.replace(year=base_date.year, month=base_date.month, day=base_date.day,
                                 hour=0, minute=0, second=0, microsecond=0)
        start_dt = base.replace(hour=start_t.hour, minute=start_t.minute)
        end_dt   = base.replace(hour=end_t.hour,   minute=end_t.minute)
        if end_t <= start_t:
            from datetime import timedelta as _td
            end_dt += _td(days=1)
        return start_dt, end_dt

    # ===== التحقق =====
    def validate(self, attrs):
        resolved_location = getattr(self.context.get('request', None), '_resolved_location', None)
        request = self.context["request"]
        user    = request.user

        # الموظف
        try:
            employee = Employee.objects.get(user=user)
        except Employee.DoesNotExist:
            raise serializers.ValidationError("لا يوجد ملف موظف مرتبط بهذا الحساب.")

        # الموقع: استخدم الموقع المحلول مبكرًا إن وُجد، وإلا حلّه هنا بمرونة
        location = self.context.get("resolved_location")
        if location is None:
            raw_loc = (attrs.get("location_id") or attrs.get("location") or "")
            if isinstance(raw_loc, str):
                raw_loc = raw_loc.strip()
            if not raw_loc:
                raise serializers.ValidationError({"location_id": "موقع غير محدد."})

            # جرّب كما هو (يدعم نص/رقم)
            try:
                location = resolved_location or Location.objects.get(id=attrs["location_id"])

            except Exception:
                location = None
            # وإن فشل، جرّب int
            if location is None:
                try:
                    location = resolved_location or Location.objects.get(id=attrs["location_id"])

                except Exception:
                    location = None

            if location is None:
                raise serializers.ValidationError({"location_id": "الموقع غير موجود أو مُعرّف غير صالح."})

        lat = attrs["lat"]; lng = attrs["lng"]
        acc = attrs.get("accuracy", 9999.0)
        action = (attrs.get("action") or "").strip().lower()

        # ===== تطبيع/قبول مفاتيح البصمة القديمة/الجديدة =====
        bio_ok = bool(attrs.get("biometric_verified") or attrs.get("bio_ok"))
        bio_method = (attrs.get("biometric_method") or attrs.get("bio_method") or "")
        bio_method = (bio_method or "").lower().strip()
        if not bio_ok:
            attrs.update({"employee": employee, "location_obj": location})
            raise serializers.ValidationError({"biometric_verified": "التحقق البيومتري مطلوب."})
        if bio_method not in {"fingerprint", "face", "pin"}:
            attrs.update({"employee": employee, "location_obj": location})
            raise serializers.ValidationError({"biometric_method": "طريقة غير صالحة. المقبول: fingerprint/face/pin"})

        # ===== منع مواقع وهمية (إن وصلت من التطبيق) =====
        if bool(attrs.get("is_mock", False)):
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ تم رصد استخدام موقع وهمي (Mock).",
            })
            return attrs

        # ===== Play Integrity (تحقق اختياري على الخادم) =====
        from django.conf import settings as _settings
        enforced = bool(getattr(_settings, "ENFORCE_PLAY_INTEGRITY", False))
        allowed = set(getattr(_settings, "INTEGRITY_ALLOWED_VERDICTS", []) or [])
        verdict = (attrs.get("integrity_verdict") or "").strip()
        if enforced and (not verdict or (allowed and verdict not in allowed)):
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ فشل التحقق من سلامة الجهاز/التطبيق (Integrity)",
            })
            return attrs

        # ===== فحص الهوية/العقد كما في كودك الأصلي (بدون تغيير) =====
        today = dj_timezone.localdate()
        if getattr(employee, "id_expiry_date", None):
            if employee.id_expiry_date < today:
                attrs.update({
                    "employee": employee, "location_obj": location,
                    "blocked": True,
                    "blocked_reason": "⚠️ لا يمكن التسجيل: الهوية منتهية.",
                })
                return attrs

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
                "blocked_reason": "⚠️ لا يوجد عقد نشط.",
            })
            return attrs

        # ===== فحص الموقع (نفس منطقك مع إرجاع رسائل واضحة) =====
        violation_messages = []
        violation_codes: list[str] = []
        attrs["violation"] = False
        attrs["violation_reason"] = None
        attrs["violation_codes"] = violation_codes
        attrs["location_radius_m"] = None
        attrs["location_center_lat"] = None
        attrs["location_center_lng"] = None

        # تحقق من الدقة الدنيا العامة مع احترام نصف قطر الموقع (نأخذ الأصغر كحد أدنى عملي)
        from django.conf import settings as _settings
        try:
            min_acc = float(getattr(_settings, "MIN_GPS_ACCURACY_M", 50) or 50)
        except Exception:
            min_acc = 50.0
        try:
            site_radius = float(getattr(location, "gps_radius", None) or 0.0)
        except Exception:
            site_radius = 0.0
        effective_min_acc = min(min_acc, site_radius) if site_radius > 0 else min_acc
        if acc > effective_min_acc:
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ دقة GPS منخفضة.",
            })
            return attrs

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
                violation_messages.append(
                    "⚠️ تم رصد الجهاز خارج حدود الموقع المعتمد. يرجى العودة إلى الموقع بأسرع وقت."
                )
                violation_codes.append("outside_polygon")

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
            attrs["location_radius_m"] = radius
            attrs["location_center_lat"] = loc_lat
            attrs["location_center_lng"] = loc_lng
            if radius and dist > radius:
                violation_messages.append(
                    "⚠️ جهازك خارج نطاق الموقع المسموح به. ستُسجّل مخالفة في حال استمرار الابتعاد لأكثر من المدة المسموح بها."
                )
                violation_codes.append("outside_radius")

        # رفض صارم إذا كانت سياسة الموقع تفرض ذلك
        reject_geofence = False
        try:
            cfg = getattr(location, "monitoring_config", None)
            reject_geofence = bool(getattr(cfg, "reject_outside_geofence", False))
        except Exception:
            reject_geofence = False
        if ("outside_polygon" in violation_codes or "outside_radius" in violation_codes) and reject_geofence:
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ خارج حدود/نطاق الموقع.",
                "violation": True,
                "violation_reason": " ".join(violation_messages) if violation_messages else None,
                "violation_codes": violation_codes,
            })
            return attrs

        # ===== حساب نافذة الوردية (كما لديك) =====
        now_aware = dj_timezone.now()
        now_local = dj_timezone.localtime(now_aware)

        current_shift = None
        allowed_start = allowed_end = None
        current_assignment = None

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

            if getattr(a, "location_id", None) and a.location_id != location.id:
                continue

            anchor = getattr(a, "date", None) or None
            # استخدم مرساة تلقائية بالاعتماد على now_local لضمان دعم الوردية الليلية
            start_dt, end_dt = self._anchor_times(now_local, start_t, end_t, anchor_date=None)
            pre_buf_min = int(getattr(a, "pre_shift_buffer_minutes", 0) or 0)
            post_buf_min = int(getattr(a, "post_shift_buffer_minutes", 0) or 0)
            pre_buffer = timedelta(minutes=pre_buf_min)
            post_buffer = timedelta(minutes=post_buf_min)
            window_start = start_dt - pre_buffer
            window_end = end_dt + post_buffer

            try:
                if not (window_start <= now_local <= window_end):
                    continue
            except Exception:
                continue
            if action == "check_in" and now_local > end_dt:
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
                win_l = window_start
                win_r = end_dt
            else:
                if action == "check_in":
                    grace_min = int(a.checkin_grace or 0)
                    win_l = window_start
                    grace_end = start_dt + timedelta(minutes=grace_min) if grace_min > 0 else start_dt
                    win_r = min(window_end, grace_end)
                    ok = (win_l <= now_local <= win_r)
                elif action in ("check_out", "early_check_out"):
                    # تفسير السياسة المطلوبة:
                    # - إذا تم تحديد سماح الانصراف (بالدقائق أو الساعات)، فإن الانصراف العادي مسموح
                    #   بعد مرور هذه المدة من بداية الوردية، حتى لو كان قبل وقت نهاية الوردية.
                    # - إذا تُركت حقول السماح فارغة، يبقى الانصراف العادي منوطًا بنهاية الوردية.
                    has_hours = (a.checkout_grace_hours is not None)
                    has_minutes = (a.checkout_grace is not None)
                    if has_hours:
                        threshold_min = int(round(float(a.checkout_grace_hours) * 60))
                    elif has_minutes:
                        threshold_min = int(a.checkout_grace)
                    else:
                        threshold_min = None
                    earliest_by_threshold = (
                        start_dt + timedelta(minutes=threshold_min)
                        if threshold_min is not None else None
                    )
                    earliest = earliest_by_threshold if earliest_by_threshold is not None else end_dt
                    win_l = earliest
                    win_r = window_end
                    if action == "check_out":
                        ok = (win_l <= now_local <= window_end)
                    else:
                        ok = (window_start <= now_local <= window_end)

            if not ok:
                if action == "check_in":
                    reason = (f"⚠️ لا يمكن تسجيل الحضور الآن. "
                              f"الفترة المسموحة كانت من {win_l.strftime('%H:%M')} إلى {win_r.strftime('%H:%M')}."
                              if win_l and win_r else "⚠️ لا يمكن تسجيل الحضور في هذا الوقت.")
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
                    "current_assignment": a,
                    "shift_within_window": False,
                })
                return attrs

            current_shift, allowed_start, allowed_end = sh, win_l, win_r
            current_assignment = a
            break

        if current_shift is None:
            attrs.update({
                "employee": employee, "location_obj": location,
                "blocked": True,
                "blocked_reason": "⚠️ خارج أوقات الوردية الحالية. يرجى مراجعة المشرف.",
                "shift_window_start": None, "shift_window_end": None,
                "current_shift": None,
                "current_assignment": None,
                "shift_within_window": False,
            })
            return attrs

        # قيود إضافية كما لديك
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

        if violation_messages:
            attrs["violation"] = True
            attrs["violation_reason"] = " ".join(violation_messages)
        else:
            attrs["violation"] = False
            attrs["violation_reason"] = None

        # حقول موحّدة نهائية
        attrs.update({
            "employee": employee,
            "location_obj": location,
            "current_shift": current_shift,
            "current_assignment": current_assignment,
            "shift_window_start": allowed_start,
            "shift_window_end": allowed_end,
            "blocked": False,
            "blocked_reason": None,
            "now_local": now_local,
            "shift_within_window": True,
            "biometric_verified": bio_ok,
            "biometric_method": bio_method,
            "provider": attrs.get("provider"),
            "is_mock": bool(attrs.get("is_mock", False)),
            "location_age_ms": attrs.get("location_age_ms"),
            "integrity_verdict": attrs.get("integrity_verdict"),
            "integrity_token": attrs.get("integrity_token"),
        })
        return attrs

    def create(self, validated_data):
        """
        يُنشئ سجل الحضور لأي من check_in / check_out / early_check_out.
        """
        now_local = validated_data.get("now_local") or dj_timezone.localtime(dj_timezone.now())
        action = validated_data["action"]
        employee = validated_data["employee"]
        location = validated_data["location_obj"]

        # ملاحظات تدقيقية موحدة
        base_notes = (
            f"{action} lat={validated_data['lat']}, lng={validated_data['lng']}, "
            f"acc={validated_data.get('accuracy')}, "
            f"dist={round(validated_data.get('distance_m') or 0.0, 2)}"
        )

        # عند الانصراف يجب إغلاق السجل المفتوح بدلاً من إنشاء سجل جديد
        if action in ["check_out", "early_check_out"]:
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time")
                        .first())
            if open_rec:
                open_rec.check_out_time = now_local
                open_rec.check_type = action
                open_rec.early_checkout = (action == "early_check_out")
                # حدّث معلومات الموقع/التتبّع الأخيرة
                open_rec.location = location or open_rec.location
                open_rec.shift = validated_data.get("current_shift") or open_rec.shift
                open_rec.biometric_verified = validated_data.get("biometric_verified", False)
                open_rec.biometric_method = validated_data.get("biometric_method", "")
                open_rec.biometric_attempts = validated_data.get("biometric_attempts", 0)
                open_rec.is_violation = bool(validated_data.get("violation", False))
                # أضف الملاحظات بدل استبدالها
                note = (open_rec.notes or "").strip()
                open_rec.notes = (note + (" | " if note else "") + base_notes).strip()
                # حقول الأمان/الموقع
                open_rec.lat = validated_data.get("lat")
                open_rec.lng = validated_data.get("lng")
                open_rec.accuracy = validated_data.get("accuracy")
                open_rec.location_age_ms = validated_data.get("location_age_ms")
                open_rec.provider = validated_data.get("provider")
                open_rec.is_mock = bool(validated_data.get("is_mock", False))
                open_rec.integrity_verdict = validated_data.get("integrity_verdict")
                # احفظ التحديث
                open_rec.save()
                return open_rec

        # الحالة الافتراضية: إنشاء سجل جديد (الحضور أو غياب سجل مفتوح عند الانصراف)
        kwargs = {
            "employee": employee,
            "location": location,
            "shift": validated_data.get("current_shift"),
            "biometric_verified": validated_data.get("biometric_verified", False),
            "biometric_method": validated_data.get("biometric_method", ""),
            "biometric_attempts": validated_data.get("biometric_attempts", 0),
            "is_violation": bool(validated_data.get("violation", False)),
            "notes": base_notes,
            "check_type": action,
        }
        if action == "check_in":
            kwargs["check_in_time"] = now_local
        elif action in ["check_out", "early_check_out"]:
            # في حال عدم وجود سجل مفتوح لسبب ما، سجّل وقت الانصراف فقط كتدقيق
            kwargs["check_in_time"] = now_local  # لتفادي null، يمكن تعديله بسياسات لاحقة
            kwargs["check_out_time"] = now_local
            kwargs["early_checkout"] = (action == "early_check_out")
        else:
            raise ValueError(f"Unknown action: {action}")

        rec = AttendanceRecord.objects.create(**kwargs)
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
        """
        Locate the best matching site for the employee based on coordinates.
        Shared between resolve-location and location ping endpoints.
        """
        qs = Location.objects.filter(assigned_employees=employee)
        best = None  # (loc, distance_m, mode, within_radius)

        for loc in qs:
            # polygon check first
            if getattr(loc, "use_polygon", False) and loc.polygon_coords:
                try:
                    poly = loc.polygon_coords
                    if isinstance(poly, str):
                        poly = json.loads(poly)
                    polygon = [(float(p[0]), float(p[1])) for p in poly]
                    if _point_in_polygon((lat, lng), polygon):
                        return loc, 0.0, "polygon", True
                    else:
                        distances = [
                            _haversine_m(lat, lng, float(p[0]), float(p[1]))
                            for p in polygon
                        ]
                        if distances:
                            dist = min(distances)
                            if (best is None) or (dist < best[1]):
                                best = (loc, dist, "polygon", False)
                except Exception:
                    pass

            # fallback to circular radius
            if loc.gps_coordinates:
                try:
                    la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
                except Exception:
                    continue
                dist = _haversine_m(lat, lng, la, ln)
                try:
                    radius = float(loc.gps_radius)
                except Exception:
                    radius = 0.0
                within_radius = radius <= 0 or dist <= radius
                if within_radius:
                    if (best is None) or (dist < best[1]) or (best and not best[3]):
                        best = (loc, dist, "radius", True)
                else:
                    if (best is None) or (dist < best[1]) or (best and not best[3] and dist < best[1]):
                        best = (loc, dist, "radius", False)

        return best


class LocationPingSerializer(ResolveLocationSerializer):
    recorded_at = serializers.DateTimeField(required=False)


class GeofenceViolationPauseRequestSerializer(serializers.Serializer):
    ACTION_CHOICES = (
        ("pause", "pause"),
        ("resume", "resume"),
    )

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    duration_minutes = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=24 * 60,
        help_text="مدة الإيقاف بالدقائق (بين 1 و 1440 دقيقة).",
    )
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=500)
    location_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        request = self.context["request"]
        try:
            employee = Employee.objects.select_related("user").get(user=request.user)
        except Employee.DoesNotExist:
            raise serializers.ValidationError({"detail": "لا يوجد ملف موظف مرتبط بالحساب."})

        location_obj = None
        location_id = attrs.get("location_id")
        if location_id:
            try:
                location_obj = Location.objects.get(id=location_id)
            except Location.DoesNotExist:
                raise serializers.ValidationError({"location_id": "الموقع غير موجود."})

        action = attrs.get("action")
        duration = attrs.get("duration_minutes")
        if action == "pause":
            if duration is None:
                raise serializers.ValidationError({"duration_minutes": "حدد مدة الإيقاف بالدقائق."})
            if duration <= 0:
                raise serializers.ValidationError({"duration_minutes": "المدة يجب أن تكون أكبر من صفر."})
        else:
            attrs["duration_minutes"] = None

        reason = attrs.get("reason")
        if reason is not None:
            reason = reason.strip()
            attrs["reason"] = reason

        attrs["employee"] = employee
        attrs["location_obj"] = location_obj
        return attrs


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


class ReportMessageSerializer(serializers.ModelSerializer):
    """عنصر في سجل التقرير (تعليمات/ملاحظات)."""
    sender_name = serializers.SerializerMethodField()

    class Meta:
        model = ReportMessage
        fields = [
            "id", "text", "is_instruction", "stage", "created_at", "sender_name", "sender_role_name"
        ]
        read_only_fields = fields

    def get_sender_name(self, obj):
        if obj.sender_employee:
            return obj.sender_employee.full_name
        if obj.sender_user:
            return obj.sender_user.get_username()
        return "النظام"


class ReportSerializer(serializers.ModelSerializer):
    location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), allow_null=True, required=False
    )
    location_name = serializers.CharField(source="location.name", read_only=True)
    report_type_display = serializers.CharField(source="get_report_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    attachments = ReportAttachmentSerializer(many=True, read_only=True)
    upload_attachments = serializers.ListField(
        child=serializers.FileField(allow_empty_file=False),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text="قائمة ملفات (صور/فيديو) مرفقة مع التقرير",
    )

    # حقول إضافية لواجهة المتابعة والتصعيد
    current_stage = serializers.CharField(read_only=True)
    can_escalate = serializers.SerializerMethodField()
    last_update_at = serializers.SerializerMethodField()
    days_since_update = serializers.SerializerMethodField()
    timeline = ReportMessageSerializer(many=True, read_only=True)

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
            "upload_attachments",
            "current_stage", "can_escalate", "last_update_at", "days_since_update", "timeline",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "created_at",
            "closed_at",
            "location_name",
            "attachments",
            "current_stage", "can_escalate", "last_update_at", "days_since_update", "timeline",
        ]

    def validate_upload_attachments(self, files):
        allowed_prefixes = ("image/", "video/")
        for uploaded in files or []:
            content_type = (getattr(uploaded, "content_type", "") or "").lower()
            if not content_type.startswith(allowed_prefixes):
                raise serializers.ValidationError("يجب أن يكون نوع الملف صورة أو فيديو")
        return files

    def create(self, validated_data):
        # عند إنشاء شكوى/حالة أمنية: ابدأ مرحلة "المشرف" وسجّل ملاحظة نظام
        from django.utils import timezone as dj_tz
        attachments = validated_data.pop("upload_attachments", [])
        report_type = (validated_data.get("report_type") or "").strip()
        report = super().create(validated_data)

        # سجل أولي: أنشأه الحارس (المرسل = الحارس)
        try:
            emp = validated_data.get('employee')
            if emp is None:
                # في حال لم يُمرَّر employee ضمن save(), نحاول قراءته من سياق الطلب
                req = self.context.get('request')
                if req and getattr(req, 'user', None):
                    emp = Employee.objects.filter(user=req.user).first()
            if emp is not None:
                loc_name = getattr(getattr(report, 'location', None), 'name', '') or '—'
                ReportMessage.objects.create(
                    report=report,
                    sender_employee=emp,
                    sender_role_name='الحارس',
                    text=f'تم إنشاء البلاغ من قبل الحارس في موقع: {loc_name}.',
                    is_instruction=False,
                    stage='guard',
                )
        except Exception:
            pass

        if report_type in ("complaint", "security"):
            report.current_stage = "supervisor"
            report.last_routed_at = dj_tz.now()
            report.save(update_fields=["current_stage", "last_routed_at", "updated_at"])
            try:
                supervisor = getattr(getattr(report, 'employee', None), 'supervisor', None) or getattr(emp, 'supervisor', None)
                loc_name = getattr(getattr(report, 'location', None), 'name', '') or '—'
                ReportMessage.objects.create(
                    report=report,
                    sender_employee=supervisor,
                    sender_role_name='المشرف المباشر',
                    text=(f"تم توجيه البلاغ إلى المشرف: {getattr(supervisor, 'full_name', '—')} @ {loc_name}"),
                    is_instruction=False,
                    stage="supervisor",
                )
            except Exception:
                pass
        for uploaded in attachments:
            ReportAttachment.objects.create(
                report=report,
                file=uploaded,
                file_type=self._detect_file_type(uploaded),
            )
        return report

    @staticmethod
    def _detect_file_type(uploaded):
        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type.startswith("video/"):
            return "video"
        return "image"

    # --- Helpers ---
    def get_can_escalate(self, obj):
        from django.utils import timezone as dj_tz
        if obj.report_type not in ("complaint", "security"):
            return False
        # يظهر زر التصعيد فقط عندما يكون في مرحلة الموارد البشرية ومرّ أكثر من 48 ساعة دون رد
        if (obj.current_stage or "") != "hr":
            return False
        if (obj.status or "") not in ("new",):
            return False
        ref = obj.last_response_at or obj.last_routed_at or obj.created_at
        if not ref:
            return False
        return (dj_tz.now() - ref).total_seconds() >= 48 * 3600

    def get_last_update_at(self, obj):
        ref = obj.last_response_at or obj.updated_at or obj.created_at
        return ref.isoformat() if ref else None

    def get_days_since_update(self, obj):
        from django.utils import timezone as dj_tz
        ref = obj.last_response_at or obj.updated_at or obj.created_at
        if not ref:
            return None
        return int((dj_tz.now() - ref).total_seconds() // 86400)

    # -------- Auto-locate helpers for reports --------
    def _auto_pick_location(self, *, employee: Employee, lat: float | None = None, lng: float | None = None):
        """
        يحاول اختيار موقع البلاغ تلقائيًا:
        1) عند توفر lat/lng نستخدم أفضل مطابقة عبر حدود/نصف قطر.
        2) إن لم يتوفر: أقرب/آخر تعيين وردية بموقع محدد.
        3) إن لم يتوفر: تعيين موقع نشط (EmployeeLocationAssignment بلا end_date).
        4) إن لم يتوفر: آخر LocationPing ضمن 24 ساعة.
        """
        # 1) Active employee-location assignment (الموقع المسند)
        try:
            ela = (EmployeeLocationAssignment.objects
                   .select_related('location')
                   .filter(employee=employee, end_date__isnull=True)
                   .order_by('-id')
                   .first())
            if ela and ela.location:
                return ela.location
        except Exception:
            pass
        # 2) Current shift assignment
        try:
            assign = (EmployeeShiftAssignment.objects
                      .select_related('location')
                      .filter(employee=employee, active=True, location__isnull=False)
                      .order_by('-date', '-id')
                      .first())
            if assign and assign.location:
                return assign.location
        except Exception:
            pass
        # 3) Geo (عند توفر الإحداثيات)
        if lat is not None and lng is not None:
            try:
                resolver = ResolveLocationSerializer(context=self.context)
                loc, dist, mode, within = resolver.find_best_location(employee, float(lat), float(lng))
                if loc:
                    return loc
            except Exception:
                pass
        # 4) Recent ping within 24h
        try:
            from django.utils import timezone as dj_tz
            since = dj_tz.now() - dj_tz.timedelta(hours=24)
            ping = (LocationPing.objects
                    .select_related('location')
                    .filter(employee=employee, recorded_at__gte=since)
                    .order_by('-recorded_at')
                    .first())
            if ping and ping.location:
                return ping.location
        except Exception:
            pass
        return None

    def validate(self, attrs):
        """
        تعيين الموقع تلقائيًا عند إنشاء التقرير إذا لم يُحدد.
        يقبل lat/lng اختياريًا ضمن body (إن أُرسلت من العميل).
        """
        loc = attrs.get('location')
        if loc:
            return attrs
        req = self.context.get('request')
        user = getattr(req, 'user', None)
        if not user:
            return attrs
        try:
            emp = Employee.objects.get(user=user)
        except Employee.DoesNotExist:
            return attrs
        # read optional lat/lng from initial_data
        try:
            lat_raw = self.initial_data.get('lat') if hasattr(self, 'initial_data') else None
            lng_raw = self.initial_data.get('lng') if hasattr(self, 'initial_data') else None
            lat = float(lat_raw) if lat_raw is not None else None
            lng = float(lng_raw) if lng_raw is not None else None
        except Exception:
            lat = lng = None
        auto_loc = self._auto_pick_location(employee=emp, lat=lat, lng=lng)
        if auto_loc is not None:
            attrs['location'] = auto_loc
        return attrs


class RequestSerializer(serializers.ModelSerializer):
    request_type_display = serializers.CharField(source="get_request_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    approver_name = serializers.CharField(source="approver.full_name", read_only=True)
    uniform_delivery = serializers.SerializerMethodField()

    payment_method = serializers.CharField(write_only=True, required=False, allow_blank=True)
    uniform_items = serializers.ListField(
        child=serializers.DictField(), write_only=True, required=False
    )
    uniform_location_id = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._uniform_payload = None

    class Meta:
        model = Request
        fields = [
            "id",
            "request_type",
            "request_type_display",
            "description",
            "leave_start",
            "leave_end",
            "leave_hours",
            "leave_deducted",
            "status",
            "status_display",
            "approval_notes",
            "approver_name",
            "created_at",
            "uniform_delivery",
            "payment_method",
            "uniform_items",
            "uniform_location_id",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "approval_notes",
            "approver_name",
            "created_at",
            "leave_hours",
            "leave_deducted",
            "uniform_delivery",
        ]

    def validate(self, attrs):
        request_type = attrs.get("request_type") or getattr(self.instance, "request_type", None)
        leave_start = attrs.get("leave_start", getattr(self.instance, "leave_start", None))
        leave_end = attrs.get("leave_end", getattr(self.instance, "leave_end", None))

        if request_type == 'leave':
            if not leave_start or not leave_end:
                raise serializers.ValidationError("يجب تحديد تاريخ ووقت البداية والنهاية للإجازة")
            if leave_start >= leave_end:
                raise serializers.ValidationError("تاريخ نهاية الإجازة يجب أن يكون بعد تاريخ البداية")
        if request_type == 'uniform':
            items_raw = self.initial_data.get('uniform_items')
            if not items_raw:
                raise serializers.ValidationError({'uniform_items': "يرجى تحديد القطع المطلوبة."})
            if not isinstance(items_raw, list):
                raise serializers.ValidationError({'uniform_items': "صيغة غير صحيحة لقائمة القطع."})

            cleaned_items = []
            for idx, item in enumerate(items_raw):
                if not isinstance(item, dict):
                    raise serializers.ValidationError({'uniform_items': f"البيان رقم {idx + 1} غير صالح."})
                raw_item_id = item.get('item_id') or item.get('item')
                if not raw_item_id:
                    raise serializers.ValidationError({'uniform_items': f"يرجى تحديد القطعة للعنصر رقم {idx + 1}."})
                try:
                    item_id = uuid.UUID(str(raw_item_id))
                except (TypeError, ValueError):
                    raise serializers.ValidationError({'uniform_items': f"معرّف القطعة غير صالح ({raw_item_id})."})

                raw_quantity = item.get('quantity', 1)
                try:
                    quantity = int(raw_quantity)
                except (TypeError, ValueError):
                    raise serializers.ValidationError({'uniform_items': f"الكمية غير صالحة للعنصر رقم {idx + 1}."})
                if quantity <= 0:
                    raise serializers.ValidationError({'uniform_items': f"الكمية يجب أن تكون أكبر من صفر (العنصر رقم {idx + 1})."})

                # المقاس (اختياري)
                raw_size = item.get('size')
                size = None
                if raw_size is not None:
                    s = str(raw_size).strip()
                    if len(s) > 20:
                        raise serializers.ValidationError({'uniform_items': f"المقاس طويل جداً (العنصر رقم {idx + 1})."})
                    size = s or None

                cleaned_items.append({
                    'item_id': item_id,
                    'quantity': quantity,
                    'size': size,
                    'notes': (item.get('notes') or '').strip(),
                })

            payment_method = (self.initial_data.get('payment_method') or 'deduction').strip()
            valid_methods = {choice[0] for choice in UniformDelivery.PAYMENT_METHOD_CHOICES}
            if payment_method not in valid_methods:
                raise serializers.ValidationError({'payment_method': "طريقة الدفع غير مدعومة."})

            location_id = self.initial_data.get('uniform_location_id')
            location_uuid = None
            if location_id:
                try:
                    location_uuid = uuid.UUID(str(location_id))
                except (TypeError, ValueError):
                    raise serializers.ValidationError({'uniform_location_id': "معرّف الموقع غير صالح."})

            self._uniform_payload = {
                'items': cleaned_items,
                'payment_method': payment_method,
                'location_id': location_uuid,
            }
        else:
            self._uniform_payload = None
        return attrs

    def create(self, validated_data):
        employee = validated_data.pop('employee')
        request_type = validated_data.get('request_type')

        if request_type == 'uniform':
            payload = getattr(self, '_uniform_payload', None)
            if not payload:
                raise serializers.ValidationError({'uniform_items': "يرجى تحديد القطع المطلوبة."})

            with transaction.atomic():
                location = None
                location_id = payload.get('location_id')
                if location_id:
                    location = Location.objects.filter(id=location_id).first()

                uniform_delivery = UniformDelivery.objects.create(
                    employee=employee,
                    location=location,
                    payment_method=payload['payment_method'],
                )

                total_value = Decimal('0')
                for item_data in payload['items']:
                    uniform_item = UniformItem.objects.filter(id=item_data['item_id']).first()
                    if not uniform_item:
                        raise serializers.ValidationError({'uniform_items': "أحد القطع المحددة غير موجود."})
                    delivery_item = UniformDeliveryItem.objects.create(
                        delivery=uniform_delivery,
                        item=uniform_item,
                        quantity=item_data['quantity'],
                        size=item_data.get('size') or None,
                        notes=item_data['notes'] or '',
                    )
                    total_value += delivery_item.value

                if uniform_delivery.total_value != total_value:
                    uniform_delivery.total_value = total_value
                    uniform_delivery.save(update_fields=['total_value'])

                description = validated_data.get('description') or "طلب استلام زي"

                return Request.objects.create(
                    employee=employee,
                    request_type='uniform',
                    description=description,
                    uniform_delivery=uniform_delivery,
                )

        return Request.objects.create(employee=employee, **validated_data)

    def get_uniform_delivery(self, obj):
        delivery = getattr(obj, 'uniform_delivery', None)
        if not delivery:
            return None
        return {
            'id': str(delivery.id),
            'payment_method': delivery.payment_method,
            'payment_method_display': delivery.get_payment_method_display(),
            'total_value': str(delivery.total_value),
            'delivery_date': delivery.delivery_date.isoformat() if delivery.delivery_date else None,
            'items': [
                {
                    'id': str(item.id),
                    'item_id': str(item.item_id),
                    'item_name': item.item.name,
                    'quantity': item.quantity,
                    'size': item.size or '',
                    'value': str(item.value),
                    'notes': item.notes or '',
                }
                for item in delivery.items.select_related('item').all()
            ],
        }


class AdvanceSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Advance
        fields = [
            "id",
            "amount",
            "reason",
            "status",
            "status_display",
            "requested_at",
            "approved_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "requested_at",
            "approved_at",
        ]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("قيمة السلفة يجب أن تكون أكبر من صفر")

        employee = self.context.get("employee")
        if not employee:
            return value

        salary, _ = Salary.objects.get_or_create(employee=employee)
        base_salary = salary.base_salary or Decimal('0')
        if base_salary <= 0:
            raise serializers.ValidationError("لم يتم تحديد الراتب الأساسي بعد")

        max_allowed = (base_salary * Decimal('0.20')).quantize(Decimal('0.01'))
        if value - max_allowed > Decimal('0.0001'):
            raise serializers.ValidationError(f"قيمة السلفة لا يمكن أن تتجاوز {max_allowed} (20% من الراتب)")
        return value

    def validate(self, attrs):
        employee = self.context.get("employee")
        if not employee:
            return attrs

        hire_date = employee.hire_date
        if not hire_date:
            raise serializers.ValidationError("يجب تسجيل تاريخ التعيين قبل طلب السلفة")

        days_worked = (dj_timezone.now().date() - hire_date).days
        if days_worked < 30:
            raise serializers.ValidationError("يجب إكمال شهر عمل كامل قبل طلب السلفة")

        return attrs
    
  
class AttendanceMiniSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "employee_id",
            "check_in_time",
            "check_out_time",
            "early_checkout",
            "location_id",
            "location_name",
            "updated_at",
        ]
