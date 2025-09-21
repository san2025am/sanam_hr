# في ملف api_guard/serializers.py

from rest_framework import serializers
from django.db import transaction # لاستخدام transaction لضمان سلامة البيانات

# في ملف api_guard/serializers.py
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed

from django.conf import settings

from .emailer import send_email_otp

import re, secrets, hashlib
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
# from .models import PasswordResetSMS  # كما أنشأناه سابقاً
from .models import (
    Role, User, Employee, Location, EmployeeLocationAssignment, Task, Shift,
    AttendanceRecord, Salary, Report, ReportAttachment, Request,
    ViolationRule, EmployeeViolation, Contract, Advance, Custody,
    UniformItem, UniformDelivery, UniformDeliveryItem,PasswordResetSMS
)

User = get_user_model()

def _hash_code(code: str) -> str:
    import hashlib as _h
    return _h.sha256(code.encode()).hexdigest()


GUARD_ROLE_NAMES = {"حارس أمن", "حارس الامن", "Security Guard", "Guard"}  # غطِّ الأسماء المحتملة



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

        # إنشاء الجلسة والكود
        code = f"{secrets.randbelow(1_000_000):06d}"

        # لو كان موديل PasswordResetSMS يشترط phone غير فارغ، خزّن رقم الموظف إن وُجد أو سلسلة فارغة.
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

        from django.conf import settings
        try:
            from .emailer import send_email_otp
            send_email_otp(user.email, subject, body)
        except Exception as e:
            if getattr(settings, "DEBUG_SMS_ECHO", False):
                attrs["session_id"] = rec.id
                attrs["_debug_code"] = code
                attrs["_send_error"] = str(e)
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

# api_guard/serializers.py (أضِف هذا)


class LocationMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "client_name"]

# ابقِه كما هو
class SalaryMiniSerializer(serializers.ModelSerializer):
    total_salary = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    class Meta:
        model = Salary
        fields = ["base_salary", "bonuses", "overtime", "deductions", "total_salary", "pay_date"]

# عدّل هنا: احذف source من salary وأضف allow_null لتحمل عدم وجود سجل راتب
class EmployeeMeSerializer(serializers.ModelSerializer):
    username   = serializers.CharField(source="user.username", read_only=True)
    email      = serializers.EmailField(source="user.email", read_only=True)
    role       = serializers.CharField(source="user.role.name", read_only=True)
    role_label = serializers.SerializerMethodField()
    locations  = LocationMiniSerializer(many=True, read_only=True)

    # كان: salary = SalaryMiniSerializer(source="salary", read_only=True)
    salary     = SalaryMiniSerializer(read_only=True, allow_null=True)

    class Meta:
        model  = Employee
        fields = [
            "id", "username", "email", "role", "role_label",
            "full_name", "national_id", "phone_number",
            "hire_date", "bank_name", "bank_account",
            "locations", "salary",
        ]

    def get_role_label(self, obj):
        return obj.user.role.__str__() if getattr(obj.user, "role", None) else None
