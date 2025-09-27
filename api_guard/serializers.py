from rest_framework import serializers
from django.utils import timezone
from django.contrib.auth import get_user_model
from datetime import timedelta
import re, secrets

from .utils.geo import haversine_m, point_in_polygon

from .models import (
    EmployeeShiftAssignment, Role, User, Employee, Location, EmployeeLocationAssignment, Task, Shift,
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

class TaskMiniSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = Task
        fields = ["id", "title", "description", "status", "due_date", "location_name"]


# --- Shift assignment (mini) ---
class ShiftAssignmentMiniSerializer(serializers.ModelSerializer):
    shift_name    = serializers.CharField(source="shift.name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)

    # نريد وقت البداية/النهاية الفعلي:
    start_time = serializers.SerializerMethodField()
    end_time   = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeShiftAssignment
        fields = ["id", "date", "shift_name", "location_name", "start_time", "end_time", "active", "notes"]

    def get_start_time(self, obj):
        # لو معيّن وقت مخصص في الإسناد استخدمه، وإلا وقت الوردية
        return (obj.start_time or getattr(obj.shift, "start_time", None))

    def get_end_time(self, obj):
        return (obj.end_time or getattr(obj.shift, "end_time", None))

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
    employee_instructions   = serializers.CharField( source="instructions", read_only=True, allow_blank=True, allow_null=True)
    location_instructions   = serializers.SerializerMethodField()
    supervisor_name         = serializers.SerializerMethodField()
    supervisor_phone        = serializers.SerializerMethodField()

    tasks  = serializers.SerializerMethodField()
    shifts = serializers.SerializerMethodField()

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
            "tasks", "shifts",
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
    
    # ======= الجديد: المهام =======
    def get_tasks(self, obj):
        # إن كنت ما زلت تستخدم Task.assigned_to (حسب وصفك)
        tasks_qs = (Task.objects
                    .filter(assigned_to=obj)
                    .select_related("location")
                    .order_by("-due_date", "-id"))
        return TaskMiniSerializer(tasks_qs, many=True).data

        # ملاحظة: لو لاحقًا تحوّلت إلى جدول إسناد مهام Many-to-Many،
        # غيّر أعلاه إلى:
        # tasks_qs = (EmployeeTaskAssignment.objects
        #             .filter(employee=obj)
        #             .select_related("task", "task__location")
        #             .order_by("-task__due_date", "-task__id"))
        # return TaskMiniSerializer([a.task for a in tasks_qs], many=True).data

    # ======= الجديد: الورديات =======
    def get_shifts(self, obj):
        qs = (
            EmployeeShiftAssignment.objects
            .filter(employee=obj)                           # كل الورديات (نشطة/غير نشطة)
            .select_related("shift", "location")
            .order_by("-date", "-id")                      # الأحدث أولًا
        )

        out = []
        for a in qs:
            sh = a.shift
            # لو الإسناد عنده وقت مخصص خذه، وإلا خذ وقت الوردية الأصلية:
            start = getattr(a, "start_time", None) or (getattr(sh, "start_time", None) if sh else None)
            end   = getattr(a, "end_time",   None) or (getattr(sh, "end_time",   None) if sh else None)

            out.append({
                "id": a.id,
                "date": a.date.isoformat() if a.date else None,
                "shift_name": getattr(sh, "name", "") or "",
                "location_name": getattr(a.location, "name", "") or "",
                "start_time": start.strftime("%H:%M") if start else None,
                "end_time":   end.strftime("%H:%M")   if end   else None,
                # حقّل الاسم بغض النظر عن تسمية الحقل في الموديل
                "active": bool(getattr(a, "is_active", getattr(a, "active", True))),
                "notes": a.notes or "",
            })
        return out




class AttendanceCheckSerializer(serializers.Serializer):
    location_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=[("check_in", "check_in"), ("check_out", "check_out")])
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    accuracy = serializers.FloatField(required=False, min_value=0, default=9999)

    def validate(self, attrs):
        request = self.context["request"]
        user = request.user
        try:
            employee = Employee.objects.get(user=user)
        except Employee.DoesNotExist:
            raise serializers.ValidationError("لا يوجد ملف موظف مرتبط بهذا الحساب.")

        try:
            location = Location.objects.get(id=attrs["location_id"])
        except Location.DoesNotExist:
            raise serializers.ValidationError("الموقع غير موجود.")

        lat, lng = attrs["lat"], attrs["lng"]
        acc = attrs.get("accuracy", 9999.0)

        # سياسة الدقة: الدقة يجب ألا تتجاوز نصف قطر الموقع
        if location.gps_radius and acc > float(location.gps_radius):
            raise serializers.ValidationError("دقة الموقع ضعيفة. الرجاء المحاولة مرة أخرى بالقرب من الموقع.")

        # فحص المضلّع أولاً إن مُفعّل
        inside_polygon = None
        if location.use_polygon and location.polygon_coords and len(location.polygon_coords) >= 3:
            try:
                polygon = [(float(p[0]), float(p[1])) for p in location.polygon_coords]
                inside_polygon = point_in_polygon((lat, lng), polygon)
            except Exception:
                raise serializers.ValidationError("تنسيق المضلّع غير صالح في إعدادات الموقع.")

            if not inside_polygon:
                raise serializers.ValidationError("النقطة خارج حدود الموقع المحددة (Polygon).")

        # إن لم يُستخدم المضلّع: فحص نصف القطر
        if not (location.use_polygon and inside_polygon):
            if not location.gps_coordinates:
                raise serializers.ValidationError("إحداثيات الموقع غير مُعرّفة. راجع لوحة الإدارة.")
            try:
                loc_lat, loc_lng = [float(x.strip()) for x in location.gps_coordinates.split(",", 1)]
            except Exception:
                raise serializers.ValidationError("تنسيق إحداثيات الموقع غير صحيح في لوحة الإدارة.")
            dist = haversine_m(lat, lng, loc_lat, loc_lng)
            attrs["distance_m"] = dist
            if dist > float(location.gps_radius):
                raise serializers.ValidationError(f"خارج النطاق المسموح ({location.gps_radius}م). المسافة: {round(dist)}م.")

        attrs["employee"] = employee
        attrs["location_obj"] = location
        return attrs

   
    def create(self, validated):
    # لن نستعملها في هذا السيناريو لأننا أنجزنا الإنشاء في الـ View.
    # لو أردت إبقاءها: أرجع instance فقط.
        from .models import AttendanceRecord
        if validated["action"] == "check_in":
            return AttendanceRecord.objects.create(
                employee=validated["employee"],
                location=validated["location_obj"],
                check_in_time=timezone.now(),
                notes=f"in lat={validated['lat']}, lng={validated['lng']}, acc={validated.get('accuracy')}, dist={validated.get('distance_m')}"
            )
    # للـ check_out ننجزها في الـ View لأنها تحتاج البحث عن آخر سجل مفتوح.




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
            raise serializers.ValidationError("لا يوجد ملف موظف مرتبط بهذا الحساب.")
        attrs["employee"] = employee
        return attrs

    def find_best_location(self, employee, lat, lng):
        # المواقع المكلّف بها الموظف فقط
        qs = Location.objects.filter(assigned_employees=employee)

        best = None  # (loc, distance_m, reason)
        for loc in qs:
            # Polygon أولًا
            inside_poly = False
            if getattr(loc, "use_polygon", False) and loc.polygon_coords:
                poly = [(float(p[0]), float(p[1])) for p in loc.polygon_coords]
                inside_poly = point_in_polygon((lat, lng), poly)
                if inside_poly:
                    return loc, 0.0, "polygon"  # داخل الحدود

            # وإلا دائرة نصف قطر
            if loc.gps_coordinates:
                try:
                    la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
                except Exception:
                    continue
                dist = haversine_m(lat, lng, la, ln)
                if dist <= float(loc.gps_radius):
                    # خذ الأقرب
                    if (best is None) or (dist < best[1]):
                        best = (loc, dist, "radius")

        return best  # قد يكون None

