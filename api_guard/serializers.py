from rest_framework import serializers
from django.utils import timezone
from django.contrib.auth import get_user_model
from datetime import timedelta
import re, secrets

from .models import (
    Role, User, Employee, Location, EmployeeLocationAssignment, Task, Shift,
    AttendanceRecord, Salary, Report, ReportAttachment, Request,
    ViolationRule, EmployeeViolation, Contract, Advance, Custody,
    UniformItem, UniformDelivery, UniformDeliveryItem, PasswordResetSMS
)


User = get_user_model()

# =========================
# Auth / Guard login
# =========================
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed

GUARD_ROLE_NAMES = {"حارس أمن", "حارس الامن", "Security Guard", "Guard"}

class GuardTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT فقط إذا كان الدور حارس أمن"""
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        role_name = (user.role.name if getattr(user, "role", None) else "").strip()
        if role_name.casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            raise AuthenticationFailed("الحساب ليس له دور حارس أمن، لا يمكن تسجيل الدخول من تطبيق الحارس.", code="not_guard")
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
            raise serializers.ValidationError("لا يوجد مستخدم بهذا الاسم")

        if not user.is_active:
            raise serializers.ValidationError("الحساب غير مُفعل")
        if not (user.email and user.email.strip()):
            raise serializers.ValidationError("لا يوجد بريد إلكتروني مرتبط بهذا الحساب")

        code = f"{secrets.randbelow(1_000_000):06d}"
        phone_val = getattr(getattr(user, "employee", None), "phone_number", "") or ""
        rec = PasswordResetSMS.objects.create(
            user=user,
            phone=phone_val,
            code_hash=_hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        # إرسال عبر الإيميل
        subject = "رمز استعادة كلمة المرور - سنام الأمن"
        body = f"رمز استعادة كلمة المرور الخاص بك هو: {code}\nصالح لمدة 10 دقائق.\n"
        try:
            from .emailer import send_email_otp
            send_email_otp(user.email, subject, body)
        except Exception:
            # في وضع التطوير قد ترغب في إعادة الكود
            from django.conf import settings
            if getattr(settings, "DEBUG_SMS_ECHO", False):
                attrs["session_id"] = rec.id
                attrs["_debug_code"] = code
                return attrs
            raise serializers.ValidationError("تعذر إرسال البريد الإلكتروني، حاول لاحقًا")

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
            raise serializers.ValidationError("الجلسة غير صالحة")

        if rec.expires_at and rec.expires_at < timezone.now():
            raise serializers.ValidationError("انتهت صلاحية الرمز")
        if rec.attempts >= 5:
            raise serializers.ValidationError("تجاوزت عدد المحاولات")

        rec.attempts += 1
        rec.save(update_fields=["attempts"])

        if rec.code_hash != _hash_code(code):
            raise serializers.ValidationError("رمز غير صحيح")

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



class LocationMiniSerializer(serializers.ModelSerializer):
    instructions = serializers.CharField(source="instructions", allow_null=True, required=False)

    class Meta:
        model = Location
        fields = ["id", "name", "client_name","instructions"]

class SalaryMiniSerializer(serializers.ModelSerializer):
    # تحويل الأرقام إلى نصوص لتفادي أخطاء النوع في Flutter
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

    # الحقول الجديدة
    id_expiry_date         = serializers.DateField(read_only=True, allow_null=True)
    date_of_birth_gregorian = serializers.DateField(read_only=True, allow_null=True)
    employee_instructions   = serializers.CharField(read_only=True, allow_blank=True, allow_null=True)
    location_instructions   = serializers.SerializerMethodField()
    supervisor_name         = serializers.SerializerMethodField()
    supervisor_phone        = serializers.SerializerMethodField()

    class Meta:
        model  = Employee
        fields = [
            "id", "username", "email", "role", "role_label",
            "full_name", "national_id", "phone_number",
            "hire_date", "bank_name", "bank_account",
            "id_expiry_date", "date_of_birth_gregorian",   # ✅ أضفنا الحقول الجديدة
            "employee_instructions", "location_instructions",
            "supervisor_name", "supervisor_phone",
            "locations", "salary",
        ]

    def get_role_label(self, obj):
        return str(getattr(obj.user, "role", "")) or None

    def get_locations(self, obj):
        qs = (EmployeeLocationAssignment.objects
              .select_related("location")
              .filter(employee=obj))
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
        last = (Salary.objects
                .filter(employee=obj)
                .order_by("-pay_date", "-id")
                .first())
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
