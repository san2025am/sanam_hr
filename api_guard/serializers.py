from rest_framework import serializers
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
from datetime import timedelta
from django.utils import timezone as dj_timezone

# إن كان لديك جدول تعيينات للوردية:
try:
    from .models import EmployeeShiftAssignment
    HAS_ASSIGN = True
except Exception:
    HAS_ASSIGN = False


from django.db.models import Q
# ...



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
            expires_at=dj_timezone.now() + timedelta(minutes=10),
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

    # نعيد وقت البداية/النهاية الفعلي (من التعيين أو من الوردية)
    start_time = serializers.SerializerMethodField()
    end_time   = serializers.SerializerMethodField()

    # جديد: حقول السماح نفسها
    checkin_grace          = serializers.IntegerField(read_only=True)
    checkout_grace         = serializers.IntegerField(read_only=True)
    checkout_grace_hours   = serializers.DecimalField(max_digits=4, decimal_places=2, read_only=True)

    # جديد: دلالة جاهزة للواجهة
    unrestricted = serializers.SerializerMethodField()

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
    shift_assignments = serializers.SerializerMethodField()
    def get_shift_assignments(self, obj):
        qs = obj.shift_assignments.select_related("shift","location").filter(active=True)
        return ShiftAssignmentMiniSerializer(qs, many=True).data
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

    # ===== Helpers (داخل الكلاس) =====
    @staticmethod
    def _haversine_m(lat1, lon1, lat2, lon2):
        """حساب المسافة بالمتر بين نقطتين جغرافيتين."""
        from math import radians, sin, cos, asin, sqrt
        R = 6371000.0  # متر
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        return R * c

    @staticmethod
    def _point_in_polygon(point, polygon):
        """
        خوارزمية ray casting بسيطة:
        point: (lat, lng), polygon: [(lat, lng), ...] بترتيب مغلق/مفتوح.
        """
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
    def _in_window(now_local, start_t, end_t, grace_minutes=0, anchor_date=None):
        """
        يتحقق أن now_local داخل نافذة الوردية المرتكزة على anchor_date (إن وُجد).
        يدعم الوردية الليلية + تسامح بالدقائق. بدون أي قيم افتراضية.
        """
        if anchor_date is None:
            base = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            base = now_local.replace(
                year=anchor_date.year, month=anchor_date.month, day=anchor_date.day,
                hour=0, minute=0, second=0, microsecond=0
            )
        start_dt = base.replace(hour=start_t.hour, minute=start_t.minute)
        end_dt   = base.replace(hour=end_t.hour,   minute=end_t.minute)

        # وردية ليلية؟
        if end_t <= start_t:
            end_dt += timedelta(days=1)

        grace = timedelta(minutes=int(grace_minutes or 0))
        inside = (start_dt - grace) <= now_local <= (end_dt + grace)
        return inside, start_dt, end_dt

    
    # ====== Validation ======
    def validate(self, attrs):
        request = self.context["request"]
        user = request.user

        # الموظف
        try:
            employee = Employee.objects.get(user=user)
        except Employee.DoesNotExist:
            raise serializers.ValidationError("لا يوجد ملف موظف مرتبط بهذا الحساب.")

        # الموقع (جرّب بالـ pk ثم uuid لدعم الحالتين)
        try:
            location = Location.objects.get(id=attrs["location_id"])
        except Location.DoesNotExist:
            try:
                location = Location.objects.get(uuid=attrs["location_id"])
            except Location.DoesNotExist:
                raise serializers.ValidationError("الموقع غير موجود.")

        lat, lng = attrs["lat"], attrs["lng"]
        acc = attrs.get("accuracy", 9999.0)

        # سياسة الدقة: لا تتجاوز نصف القطر إن كان محددًا
        if getattr(location, "gps_radius", None):
            try:
                if acc > float(location.gps_radius):
                    raise serializers.ValidationError("دقة الموقع ضعيفة. الرجاء المحاولة مرة أخرى بالقرب من الموقع.")
            except (TypeError, ValueError):
                pass  # تجاهل لو القيمة غير قابلة للتحويل

        # فحص المضلّع أولًا إن مُفعّل
        inside_polygon = None
        if getattr(location, "use_polygon", False) and getattr(location, "polygon_coords", None):
            try:
                poly = location.polygon_coords
                # إن كانت JSON نصيّة:
                # if isinstance(poly, str):
                #     import json; poly = json.loads(poly)
                polygon = [(float(p[0]), float(p[1])) for p in poly]
                inside_polygon = self._point_in_polygon((lat, lng), polygon)
            except Exception:
                raise serializers.ValidationError("تنسيق المضلّع غير صالح في إعدادات الموقع.")
            if not inside_polygon:
                raise serializers.ValidationError("النقطة خارج حدود الموقع المحددة (Polygon).")

        # إن لم يُستخدم المضلع نطبق فحص نصف القطر
        if not (getattr(location, "use_polygon", False) and inside_polygon):
            if not getattr(location, "gps_coordinates", None):
                raise serializers.ValidationError("إحداثيات الموقع غير مُعرّفة. راجع لوحة الإدارة.")
            try:
                loc_lat, loc_lng = [float(x.strip()) for x in location.gps_coordinates.split(",", 1)]
            except Exception:
                raise serializers.ValidationError("تنسيق إحداثيات الموقع غير صحيح في لوحة الإدارة.")
            dist = self._haversine_m(lat, lng, loc_lat, loc_lng)
            attrs["distance_m"] = dist
            try:
                radius = float(location.gps_radius)
            except Exception:
                radius = 0.0
            if radius and dist > radius:
                raise serializers.ValidationError(f"خارج النطاق المسموح ({radius}م). المسافة: {round(dist)}م.")

        # ===== حساب الوردية الحالية =====
        # ===== حساب الوردية الحالية =====
        now_aware = dj_timezone.now()
        now_local = dj_timezone.localtime(now_aware)
        action = (attrs.get("action") or "").strip().lower()

        current_shift = None
        shift_start_dt = shift_end_dt = None

        if HAS_ASSIGN:
            assign_qs = (EmployeeShiftAssignment.objects
                        .select_related("shift", "location")
                        .filter(employee=employee, active=True))

            for a in assign_qs:
                sh = getattr(a, "shift", None)
                if not sh:
                    continue

                start_t = getattr(a, "start_time", None) or getattr(sh, "start_time", None)
                end_t   = getattr(a, "end_time",   None) or getattr(sh, "end_time",   None)
                if not (start_t and end_t):
                    continue

                # ===== السماحات =====
                if (a.checkin_grace is None and
                    a.checkout_grace is None and
                    a.checkout_grace_hours is None):
                    # كل الحقول فارغة ⇒ السماح لأي وقت
                    ok, sdt, edt = True, None, None
                else:
                    if action == "check_in":
                        grace_minutes = int(a.checkin_grace or 0)
                    else:  # check_out
                        if a.checkout_grace_hours is not None:
                            grace_minutes = int(round(float(a.checkout_grace_hours) * 60))
                        elif a.checkout_grace is not None:
                            grace_minutes = int(a.checkout_grace)
                        else:
                            grace_minutes = 0

                    anchor = getattr(a, "date", None) or None
                    ok, sdt, edt = self._in_window(
                        now_local, start_t, end_t,
                        grace_minutes=grace_minutes,
                        anchor_date=anchor
                    )

                if not ok:
                    continue

                # تحقق من الموقع (إن كان محددًا في التعيين)
                if getattr(a, "location_id", None) and a.location_id != location.id:
                    continue

                current_shift, shift_start_dt, shift_end_dt = sh, sdt, edt
                break


        # 2) لا تعتمد على جدول Shift العام (لا يوجد سقوط افتراضي)
        if current_shift is None:
            raise serializers.ValidationError("خارج أوقات الوردية الحالية.")

        # تعبئة المخرجات
        attrs["employee"] = employee
        attrs["location_obj"] = location
        attrs["current_shift"] = current_shift
        attrs["shift_window_start"] = shift_start_dt
        attrs["shift_window_end"] = shift_end_dt
        return attrs


    # (اختياري) إنشاء سجل الحضور هنا بدل الـ View
    def create(self, validated_data):
        from .models import AttendanceRecord  # استيراد محلي لتجنّب الدورات
        if validated_data["action"] == "check_in":
            rec = AttendanceRecord.objects.create(
                employee=validated_data["employee"],
                location=validated_data["location_obj"],
                shift=validated_data.get("current_shift"),
                check_in_time=dj_timezone.now(),
                notes=(
                    f"in lat={validated_data['lat']}, "
                    f"lng={validated_data['lng']}, "
                    f"acc={validated_data.get('accuracy')}, "
                    f"dist={round(validated_data.get('distance_m') or 0.0, 2)}"
                ),
            )
            return rec
        return None  # check_out تتم في الـ View بالتحديث

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
        qs = Location.objects.filter(assigned_employees=employee)
        best = None  # (loc, distance_m, reason)

        for loc in qs:
            # Polygon أولًا
            if getattr(loc, "use_polygon", False) and loc.polygon_coords:
                try:
                    poly = loc.polygon_coords
                    # if isinstance(poly, str):
                    #     poly = json.loads(poly)
                    polygon = [(float(p[0]), float(p[1])) for p in poly]
                    if point_in_polygon((lat, lng), polygon):
                        return loc, 0.0, "polygon"
                except Exception:
                    pass

            # دائرة نصف قطر
            if loc.gps_coordinates:
                try:
                    la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
                except Exception:
                    continue
                dist = haversine_m(lat, lng, la, ln)
                if dist <= float(loc.gps_radius):
                    if (best is None) or (dist < best[1]):
                        best = (loc, dist, "radius")

        return best

