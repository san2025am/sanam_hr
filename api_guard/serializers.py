# في ملف api_guard/serializers.py

from rest_framework import serializers
from .models import User, Employee, Role
from django.db import transaction # لاستخدام transaction لضمان سلامة البيانات

# في ملف api_guard/serializers.py
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed

GUARD_ROLE_NAMES = {"حارس أمن", "حارس الامن", "Security Guard", "Guard"}  # غطِّ الأسماء المحتملة

class GuardTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    يصدر JWT فقط إذا كان دور المستخدم ضمن GUARD_ROLE_NAMES.
    """
    def validate(self, attrs):
        data = super().validate(attrs)  # يتحقق من username/password ويعيد access/refresh
        user = self.user

        role_name = (user.role.name if getattr(user, "role", None) else "").strip()
        if role_name.casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            raise AuthenticationFailed("الحساب ليس له دور حارس أمن، لا يمكن تسجيل الدخول من تطبيق الحارس.", code="not_guard")

        # معلومات إضافية تعود للتطبيق
        data.update({
            "user": {
                "id": user.id,
                "username": user.username,
                "role": role_name,
            }
        })
        return data


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
