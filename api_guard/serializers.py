# في ملف api_guard/serializers.py

from rest_framework import serializers
from .models import PasswordResetSMS, User, Employee, Role
from django.db import transaction # لاستخدام transaction لضمان سلامة البيانات

# في ملف api_guard/serializers.py
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed

import re, secrets, hashlib
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import serializers
# from .models import PasswordResetSMS  # كما أنشأناه سابقاً
from .models import Employee      # <-- عدِّل المسار حسب مكان موديل Employee لديك

GUARD_ROLE_NAMES = {"حارس أمن", "حارس الامن", "Security Guard", "Guard"}  # غطِّ الأسماء المحتملة

get_user_model
def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()

def _normalize_phone(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('+'):
        return '+' + re.sub(r'\D', '', raw)
    return re.sub(r'\D', '', raw)

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

class PhoneForgotSerializer(serializers.Serializer):
    phone = serializers.CharField()
    guards_only = False

    def validate(self, attrs):
        raw = attrs["phone"].strip()
        want = _digits(raw)

        # ابحث بأي صيغة، ثم طابق بالأرقام فقط
        qs = Employee.objects.select_related("user", "user__role")\
             .filter(phone_number__icontains=want[-7:])  # آخر 7 أرقام كبحث أولي
        match = None
        for emp in qs:
            if _digits(emp.phone_number) == want:
                match = emp
                break
        if not match:
            # محاولة أخيرة: طابق أول/آخر 9-10 أرقام
            for emp in Employee.objects.select_related("user","user__role").all():
                if _digits(emp.phone_number).endswith(want[-9:]):
                    match = emp
                    break
        if not match:
            raise serializers.ValidationError("لا يوجد موظف مرتبط بهذا الرقم")

        user = match.user
        if not user.is_active:
            raise serializers.ValidationError("الحساب غير مُفعل")

        if self.guards_only:
            rn = (getattr(user.role, "name", "") or "").strip()
            if rn.casefold() not in {"حارس أمن".casefold(), "حارس الامن".casefold(), "security guard", "guard"}:
                raise serializers.ValidationError("هذه الميزة متاحة لحُرّاس الأمن فقط")

        code = f"{secrets.randbelow(1000000):06d}"
        rec = PasswordResetSMS.objects.create(
            user=user, phone=raw, code_hash=_hash_code(code),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        # TODO: send_sms(raw, f"رمز الاستعادة: {code} (صالح 10 دقائق)")
        attrs["session_id"] = rec.id
        return attrs

class PhoneResetSerializer(serializers.Serializer):
    session_id = serializers.IntegerField()
    code = serializers.CharField(min_length=4, max_length=6)
    new_password = serializers.CharField(min_length=6)

    def validate(self, attrs):
        sid = attrs["session_id"]; code = attrs["code"]
        try:
            rec = PasswordResetSMS.objects.select_related("user").get(id=sid, is_used=False)
        except PasswordResetSMS.DoesNotExist:
            raise serializers.ValidationError("الجلسة غير صالحة")

        if rec.expires_at < timezone.now():
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

class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['name']

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['full_name', 'national_id', 'phone_number']

class UserProfileSerializer(serializers.ModelSerializer):
    # نستخدم Serializers متداخلة لعرض بيانات من جداول أخرى
    employee = EmployeeSerializer(read_only=True)
    role = RoleSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'role', 'employee']


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        # سنعرض جميع الحقول المتاحة في الموديل
        fields = ['id', 'name', 'description'] 
        
class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Serializer لإنشاء مستخدم جديد مع ملف الموظف الخاص به.
    """
    # حقل لكلمة المرور (للكتابة فقط، لا يتم عرضه عند قراءة البيانات)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    
    # حقول الموظف التي نريد إدخالها عند التسجيل
    full_name = serializers.CharField(write_only=True, required=True)
    national_id = serializers.CharField(write_only=True, required=True)
    phone_number = serializers.CharField(write_only=True, required=True)
    
    # حقل لتحديد دور المستخدم الجديد
    role_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = User
        # الحقول التي سيتم استقبالها في الطلب
        fields = ('username', 'email', 'password', 'full_name', 'national_id', 'phone_number', 'role_id')

    def create(self, validated_data):
        """
        تجاوز دالة create الافتراضية للتعامل مع إنشاء User و Employee معًا.
        """
        # نستخدم transaction.atomic لضمان أنه إما أن تنجح العمليتان معًا أو تفشلان معًا
        with transaction.atomic():
            # استخراج بيانات الموظف والدور
            full_name = validated_data.pop('full_name')
            national_id = validated_data.pop('national_id')
            phone_number = validated_data.pop('phone_number')
            role_id = validated_data.pop('role_id')
            
            # الحصول على كائن الدور (Role)
            try:
                role = Role.objects.get(id=role_id)
            except Role.DoesNotExist:
                raise serializers.ValidationError({'role_id': 'الدور المحدد غير موجود.'})

            # إنشاء المستخدم (User)
            # نستخدم create_user لضمان تشفير كلمة المرور بشكل صحيح
            user = User.objects.create_user(
                username=validated_data['username'],
                email=validated_data['email'],
                password=validated_data['password'],
                role=role
            )

            # إنشاء الموظف (Employee) وربطه بالمستخدم
            Employee.objects.create(
                user=user,
                full_name=full_name,
                national_id=national_id,
                phone_number=phone_number
            )
            
            return user
