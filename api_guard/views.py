from __future__ import annotations

# تعديل شامل: تحويل كل غغغغغغ endpoints إلى POST + تحسينات الحضور والنبضات والجيوفنس
import datetime as dt
import hashlib
import secrets
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Sequence

from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.decorators import parser_classes

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, DatabaseError, transaction
from django.db.models import F, OuterRef, Subquery, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone as dj_timezone
from django.utils import timezone  # لاستخدام timezone.now بصيغة واضحة

from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .utils.response import ok, fail
from .utils.query import OptimizedQuerysetMixin
from api_guard.utils.maps import (
    get_current_shift_window,
    is_location_allowed_for_user,
)

from .models import (
    AttendanceRecord,
    Employee,
    Location,
    Salary,
    Task,
    Report,
    Request,
    Advance,
    TrustedDevice,
    DeviceLoginChallenge,
    UniformItem,
    ViolationRule,
    EmployeeViolation,
    LocationPing,
    LocationMonitoringConfig,
    EmployeeShiftAssignment,
    Shift,
    GeofenceViolationPause,
)

from .serializers import (
    GUARD_ROLE_NAMES,
    AttendanceMiniSerializer,
    ReportSerializer,
    RequestSerializer,
    AdvanceSerializer,
    ResolveLocationSerializer,
    LocationPingSerializer,
    AttendanceCheckSerializer,
    GuardTokenObtainPairSerializer,
    UsernameForgotSerializer,
    UsernameResetSerializer,
    EmployeeMeSerializer,
    TaskMiniSerializer,
    GuardTaskUpdateSerializer,
)

from .emailer import send_email_otp
from .services.attendance import (
    close_stale_attendance_for_employee,
    flag_absent_assignments_for_employee,
)
from .sms import send_sms_twilio

User = get_user_model()
logger = logging.getLogger(__name__)
logger_api = logging.getLogger("api_guard")

# إعدادات الجيوفنس الافتراضية
GEOFENCE_WARNING_MINUTES = int(getattr(settings, "GEOFENCE_OUTSIDE_WARNING_MINUTES", 60))
GEOFENCE_RULE_TITLE = "الخروج عن نطاق الموقع"
GEOFENCE_RULE_DESCRIPTION = (
    "يتم تسجيل هذه المخالفة عند خروج الحارس عن نطاق الموقع المحدد لأكثر من المدة المسموح بها."
)
try:
    GEOFENCE_DEDUCTION_PERCENT = Decimal(str(getattr(settings, "GEOFENCE_OUTSIDE_DEDUCTION_PERCENT", 2)))
except (InvalidOperation, TypeError, ValueError):
    GEOFENCE_DEDUCTION_PERCENT = Decimal("2")
if GEOFENCE_DEDUCTION_PERCENT < 0:
    GEOFENCE_DEDUCTION_PERCENT = Decimal("0")


def _make_aware(dt_value):
    if dt_value is None:
        return None
    if dj_timezone.is_naive(dt_value):
        tz = dj_timezone.get_current_timezone()
        return dj_timezone.make_aware(dt_value, tz)
    return dt_value


def _local_dt(dt_value):
    aware = _make_aware(dt_value)
    if aware is None:
        return None
    return dj_timezone.localtime(aware)


def _local_iso(dt_value):
    local = _local_dt(dt_value)
    return local.isoformat() if local else None


def _fmt_time(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        value = value.timetz()
    if isinstance(value, dt.time):
        return value.strftime("%H:%M")
    return str(value)


def _normalize_action_incoming(raw):
    """
    تطبيع أي صيغة واردة إلى:
      check_in | check_out | early_check_out
    """
    if not raw:
        return None
    s = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("checkin", "sign_in", "signin", "check_in"):
        return "check_in"
    if s in ("checkout", "sign_out", "signout", "check_out"):
        return "check_out"
    if s in ("early_checkout", "early_check_out", "early_signout", "early_sign_out"):
        return "early_check_out"
    return None


def _decimal_or_zero(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _format_decimal(value: Decimal) -> str:
    dec = _decimal_or_zero(value)
    quantized = dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(quantized.normalize(), "f")


def _apply_geofence_salary_deduction(employee: Employee, percent: Decimal) -> Decimal:
    percent = _decimal_or_zero(percent)
    if employee is None or percent <= 0:
        return Decimal("0")
    salary, _ = Salary.objects.get_or_create(employee=employee)
    base = salary.base_salary or Decimal("0")
    if base <= 0:
        return Decimal("0")
    deduction = (base * percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if deduction <= 0:
        return Decimal("0")
    Salary.objects.filter(pk=salary.pk).update(deductions=F("deductions") + deduction)
    return deduction


_GUARD_ROLE_NAMES_CI = {name.casefold() for name in GUARD_ROLE_NAMES}
TASK_STATUS_FLOW = ['new', 'accepted', 'in_progress', 'completed']


def _device_hash(raw_id: str) -> str:
    normalized = (raw_id or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").encode("utf-8")).hexdigest()


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    local = local.strip()
    if not local:
        return f"***@{domain}"
    if len(local) <= 2:
        masked_local = local[0] + "*" * max(len(local) - 1, 0)
    else:
        masked_local = f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{masked_local}@{domain}"


def _refresh_existing_trusted_device(instance, *, provided_name: str, now):
    fields = []
    if instance.deleted_at is not None:
        instance.deleted_at = None
        fields.append("deleted_at")
    instance.last_seen_at = now
    fields.append("last_seen_at")
    current_name = (instance.device_name or "").strip()
    if provided_name and provided_name != current_name:
        instance.device_name = provided_name
        fields.append("device_name")
    update_fields = list({*fields, "updated_at"})
    instance.save(update_fields=update_fields)
    return instance


def _ensure_trusted_device(*, user, device_hash: str, device_name: str, now, default_name: str):
    provided_name = (device_name or "").strip()
    existing = (TrustedDevice.all_objects
                .filter(user=user, device_hash=device_hash)
                .first())
    if existing:
        return _refresh_existing_trusted_device(
            existing,
            provided_name=provided_name,
            now=now,
        )

    create_name = provided_name or (default_name or "")
    try:
        return TrustedDevice.objects.create(
            user=user,
            device_hash=device_hash,
            device_name=create_name,
        )
    except IntegrityError:
        existing = (TrustedDevice.all_objects
                    .filter(user=user, device_hash=device_hash)
                    .first())
        if existing:
            return _refresh_existing_trusted_device(
                existing,
                provided_name=provided_name,
                now=now,
            )
        raise


def _enforce_single_trusted_device(*, user, active_device_hash: str, now) -> None:
    others_qs = (TrustedDevice.all_objects
                 .filter(user=user)
                 .exclude(device_hash=active_device_hash))
    if not others_qs.exists():
        return
    alive_qs = others_qs.filter(deleted_at__isnull=True)
    if alive_qs.exists():
        alive_qs.update(deleted_at=now, updated_at=now)


def _require_guard_employee(user):
    role_name = (getattr(getattr(user, "role", None), "name", "") or "").strip()
    if role_name.casefold() not in _GUARD_ROLE_NAMES_CI:
        raise PermissionDenied("الدخول متاح لحراس الأمن فقط")
    try:
        return Employee.objects.select_related("user", "user__role").get(user=user)
    except Employee.DoesNotExist as exc:
        raise NotFound("لا يوجد ملف موظف مرتبط بهذا الحساب") from exc


def _assignment_window_for(
    *,
    employee: Employee,
    location,
    reference: Optional[dt.datetime] = None,
) -> tuple[Optional[EmployeeShiftAssignment], Optional[Shift], Optional[dt.datetime], Optional[dt.datetime]]:
    """
    يعثر على تعيين الوردية الحالي (مع الأخذ بعين الاعتبار السماحات قبل/بعد الوردية).
    """
    if reference is None:
        reference = dj_timezone.now()
    local_reference = _local_dt(reference)
    if local_reference is None:
        return None, None, None, None

    qs = (EmployeeShiftAssignment.objects
          .select_related("shift", "location")
          .filter(employee=employee, active=True))
    if location is not None:
        qs = qs.filter(Q(location__isnull=True) | Q(location=location))
    qs = qs.order_by("-date", "-id")

    for assignment in qs:
        shift = assignment.shift
        if shift is None:
            continue

        start_t = assignment.start_time or shift.start_time
        end_t = assignment.end_time or shift.end_time
        if not (start_t and end_t):
            continue

        anchor = assignment.date or None
        start_dt, end_dt = AttendanceCheckSerializer._anchor_times(local_reference, start_t, end_t, anchor_date=anchor)
        pre_buf_min = int(getattr(assignment, "pre_shift_buffer_minutes", 0) or 0)
        post_buf_min = int(getattr(assignment, "post_shift_buffer_minutes", 0) or 0)
        window_start = start_dt - timedelta(minutes=pre_buf_min)
        window_end = end_dt + timedelta(minutes=post_buf_min)

        try:
            within_window = window_start <= local_reference <= window_end
        except Exception:
            within_window = False

        if within_window:
            return assignment, shift, window_start, window_end

    return None, None, None, None


def _build_shift_payload(
    *,
    employee: Optional[Employee],
    shift: Optional[Shift],
    assignment: Optional[EmployeeShiftAssignment],
    allowed_start: Optional[dt.datetime],
    allowed_end: Optional[dt.datetime],
    location: Optional[Location],
    within_shift: Optional[bool],
) -> dict:
    """
    يبني حمولة وصف الوردية المعروضة للعميل.
    يعيد قاموسًا صغيرًا آمنًا للاستخدام في الواجهة.
    """
    try:
        payload: dict[str, object] = {}
        if shift is not None:
            name = getattr(shift, "name", None)
            if name:
                payload["name"] = name

        if assignment is not None:
            try:
                asg_loc = getattr(assignment, "location", None)
                if asg_loc is not None:
                    payload["assignment_location_name"] = getattr(asg_loc, "name", None)
                    try:
                        matches = (getattr(asg_loc, "id", None) == getattr(location, "id", None))
                        payload["matches_location"] = matches
                    except Exception:
                        pass
            except Exception:
                pass

        if allowed_start is not None:
            payload["window_start"] = _local_iso(allowed_start)
        if allowed_end is not None:
            payload["window_end"] = _local_iso(allowed_end)

        if within_shift is not None:
            payload["within_shift"] = bool(within_shift)

        return payload
    except Exception:
        return {}


def _monitoring_details(
    location,
    *,
    employee: Optional[Employee] = None,
):
    """
    يعيد (payload, active, grace_minutes, ping_seconds, outside_seconds, rule, config, pause).
    """
    config: Optional[LocationMonitoringConfig] = None
    rule: Optional[ViolationRule] = None
    active = False
    ping_seconds: Optional[int] = None
    grace_minutes = GEOFENCE_WARNING_MINUTES

    pause = GeofenceViolationPause.active_for(employee=employee, location=location) if location else None

    if location:
        try:
            config = location.monitoring_config  # type: ignore[attr-defined]
        except LocationMonitoringConfig.DoesNotExist:
            config = None
        except DatabaseError as exc:
            logger.warning("Monitoring config unavailable for location %s: %s", getattr(location, "id", None), exc)
            return ({
                "active": False,
                "violation_grace_minutes": GEOFENCE_WARNING_MINUTES,
                "default_violation_grace_minutes": GEOFENCE_WARNING_MINUTES,
            }, False, GEOFENCE_WARNING_MINUTES, None, None, None, None, None)

    if config:
        rule = getattr(config, "violation_rule", None)
        active = bool(config.is_active)
        if active:
            ping_val = int(config.ping_interval_seconds or 0)
            ping_seconds = ping_val if ping_val > 0 else None
            grace_val = int(config.violation_grace_minutes or 0)
            if grace_val > 0:
                grace_minutes = grace_val
        else:
            ping_seconds = None

    outside_seconds: Optional[int] = None
    if ping_seconds:
        outside_seconds = max(60, ping_seconds // 2 or 1)

    payload: dict[str, object] = {
        "active": active,
        "violation_grace_minutes": grace_minutes,
        "default_violation_grace_minutes": GEOFENCE_WARNING_MINUTES,
    }
    if ping_seconds:
        payload["ping_interval_seconds"] = ping_seconds
    if outside_seconds:
        payload["suggested_outside_ping_seconds"] = outside_seconds
    if config:
        payload["config_id"] = str(config.id)
    if rule:
        payload["violation_rule_id"] = str(rule.id)
        payload["violation_rule_title"] = rule.title
        payload["violation_rule_action"] = rule.default_action
    if pause:
        payload.update({
            "violation_paused": True,
            "violation_pause_reason": pause.reason,
            "violation_pause_started_at": _local_iso(pause.pause_started_at),
            "violation_pause_until": _local_iso(pause.pause_until),
            "violation_pause_duration_minutes": pause.duration_minutes,
            "violation_pause_location_id": str(getattr(pause.location, "id", "")) if pause.location else None,
        })
    else:
        payload["violation_paused"] = False
        payload["violation_pause_reason"] = None
        payload["violation_pause_started_at"] = None
        payload["violation_pause_until"] = None
        payload["violation_pause_duration_minutes"] = None
        payload["violation_pause_location_id"] = None
    return payload, active, grace_minutes, ping_seconds, outside_seconds, rule, config, pause


# =============== المصادقة وكلمة المرور ===============

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
            return ok({"detail": "اسم المستخدم/كلمة المرور مطلوبة"})

        user = authenticate(request, username=username, password=password)
        if not user:
            return ok({"detail": "بيانات دخول غير صحيحة"})
        if not user.is_active:
            return ok({"detail": "الحساب غير مُفعل"})

        role_name = getattr(getattr(user, "role", None), "name", None)
        if (role_name or "").strip().casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            return ok({"detail": "الدخول متاح لحُراس الأمن فقط"})

        try:
            employee = Employee.objects.select_related("user", "user__role").get(user=user)
            Salary.objects.get_or_create(employee=employee)
        except Employee.DoesNotExist:
            return ok({"detail": "لا يوجد ملف موظف مرتبط بهذا المستخدم"})

        device_id = (request.data.get("device_id") or "").strip()
        device_name = (request.data.get("device_name") or "").strip()
        challenge_id_raw = request.data.get("challenge_id")
        otp_code_raw = request.data.get("otp_code")
        challenge_id = (challenge_id_raw or "").strip()
        otp_code = (otp_code_raw or "").strip()

        if not device_id:
            return ok({"detail": "معرّف الجهاز مفقود. يرجى تحديث التطبيق."})

        now = dj_timezone.now()
        device_hash = _device_hash(device_id)
        other_user_entry = (
            TrustedDevice.objects
            .filter(device_hash=device_hash)
            .exclude(user=user)
            .first()
        )
        if other_user_entry:
            return ok({
                "detail": "هذا الجهاز مسجل مسبقًا لحساب آخر. يرجى تسجيل الخروج من الحساب السابق أو التواصل مع الإدارة.",
                "code": "device_used_by_another_user",
            }, status=status.HTTP_403_FORBIDDEN)
        trusted_devices_qs = TrustedDevice.objects.filter(user=user)
        trusted_entry = trusted_devices_qs.filter(device_hash=device_hash).first()

        active_trusted_device = None

        if not trusted_devices_qs.exists():
            active_trusted_device = _ensure_trusted_device(
                user=user,
                device_hash=device_hash,
                device_name=device_name,
                now=now,
                default_name="الجهاز الرئيسي",
            )
        elif trusted_entry:
            active_trusted_device = _ensure_trusted_device(
                user=user,
                device_hash=device_hash,
                device_name=device_name,
                now=now,
                default_name=trusted_entry.device_name or device_name or "الجهاز الرئيسي",
            )
        else:
            if challenge_id and otp_code:
                try:
                    challenge = DeviceLoginChallenge.objects.get(
                        id=challenge_id,
                        user=user,
                        device_hash=device_hash,
                        verified_at__isnull=True,
                    )
                except (DeviceLoginChallenge.DoesNotExist, ValueError):
                    return Response({"detail": "طلب التحقق غير صالح"})

                if challenge.is_expired:
                    return ok({"detail": "انتهت صلاحية رمز التحقق"})
                if challenge.attempts >= 5:
                    return ok({"detail": "تم تجاوز عدد المحاولات المسموح بها"})

                if _hash_code(otp_code) != challenge.code_hash:
                    challenge.attempts += 1
                    challenge.save(update_fields=["attempts", "updated_at"])
                    return ok({"detail": "رمز التحقق غير صحيح"})

                challenge.verified_at = now
                if device_name and not challenge.device_name:
                    challenge.device_name = device_name
                challenge.save(update_fields=["verified_at", "device_name", "updated_at"])

                active_trusted_device = _ensure_trusted_device(
                    user=user,
                    device_hash=device_hash,
                    device_name=device_name or challenge.device_name,
                    now=now,
                    default_name="جهاز موثّق",
                )
            else:
                email = (user.email or "").strip()
                if not email:
                    return ok({
                        "detail": "هذا الجهاز غير موثوق ويستلزم التحقق، لكن لا يوجد بريد إلكتروني لإرسال الرمز. يرجى التواصل مع المسؤول لتحديث بياناتك.",
                        "code": "no_email_available",
                    })

                code = f"{secrets.randbelow(1_000_000):06d}"
                expires_at = now + timedelta(minutes=10)
                challenge = DeviceLoginChallenge.objects.create(
                    user=user,
                    device_hash=device_hash,
                    device_name=device_name,
                    code_hash=_hash_code(code),
                    expires_at=expires_at,
                )
                subject = "رمز توثيق جهاز جديد"
                body = (
                    "عزيزي المستخدم،\n\n"
                    "تم محاولة تسجيل الدخول من جهاز جديد. رمز التحقق الخاص بك هو:\n"
                    f"{code}\n\n"
                    "الرمز صالح لمدة 10 دقائق. إذا لم تكن أنت من حاول تسجيل الدخول، يرجى تجاهل هذه الرسالة."
                )
                try:
                    send_email_otp(email, subject, body)
                except Exception:
                    if getattr(settings, "DEBUG_SMS_ECHO", False):
                        return ok({
                            "requires_verification": True,
                            "challenge_id": str(challenge.id),
                            "detail": "تعذر إرسال البريد الإلكتروني، تم عرض الرمز مباشرة لأغراض الاختبار.",
                            "destination": "debug",
                            "delivery": "debug",
                            "debug_code": code,
                        }, status=status.HTTP_202_ACCEPTED)
                    challenge.delete(hard=True)
                    return Response({
                        "detail": "تعذر إرسال رمز التحقق. يرجى المحاولة لاحقًا أو التواصل مع الإدارة لتوثيق الجهاز.",
                        "code": "otp_delivery_failed",
                    }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

                masked_email = _mask_email(email)
                return Response({
                    "requires_verification": True,
                    "challenge_id": str(challenge.id),
                    "detail": "هذا الجهاز غير مسجّل ضمن أجهزتك الموثوقة. تم إرسال رمز تحقق إلى بريدك الإلكتروني.",
                    "destination": masked_email,
                    "delivery": "email",
                })

        if active_trusted_device:
            _enforce_single_trusted_device(
                user=user,
                active_device_hash=active_trusted_device.device_hash,
                now=now,
            )

        try:
            emp_data = EmployeeMeSerializer(employee).data
        except DatabaseError as exc:
            logger.exception("Failed to serialize employee profile during guard login: %s", exc)
            return ok({
                "detail": "الخادم غير جاهز بالكامل. يرجى إعادة المحاولة بعد تطبيق التحديثات أو التواصل مع الدعم الفني.",
                "code": "backend_not_ready",
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
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
        })


class GuardMeView(APIView):
    """يعيد بيانات الموظف الحالي — تم تحويله إلى POST."""
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
# Attendance (POST-only)
# =========================
class AttendanceCheckAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (JSONParser, FormParser, MultiPartParser)

    def _deny(
        self,
        *,
        action=None,
        detail: str = "",
        reason_code: str | None = None,
        start=None,
        end=None,
        now=None,
        monitoring: dict | None = None,
        extra: dict | None = None,
        status_code: int = status.HTTP_200_OK,
    ):
        """يرجع استجابة مهيكلة موحّدة للأخطاء مع حقل detail دائماً.
        لا نستخدم 4xx افتراضيًا كي لا تكسر واجهات قديمة؛ نعطي 200 مع ok=false.
        """
        payload = {
            "ok": False,
            "performed": False,
            "action": action,
            "detail": detail or "تعذر تنفيذ الطلب.",
        }
        if reason_code:
            payload["reason_code"] = reason_code
        if start is not None:
            payload["shift_window_start"] = _local_iso(start)
        if end is not None:
            payload["shift_window_end"] = _local_iso(end)
        if now is not None:
            payload["now"] = _local_iso(now)
        if monitoring:
            payload["monitoring"] = monitoring
        if extra:
            # ضم الحقول الإضافية تحت مفتاح extra لتجنّب تضارب المفاتيح
            payload["extra"] = extra

        return Response(payload, status=status_code)

    def _safe_data(self, request):
        """
        قراءة آمنة لبيانات الطلب:
        - إذا كان Content-Type = text/plain أو غير محدد، نحاول json.loads من الجسم مباشرة.
        - وإلا نستخدم request.data (DRF parser).
        الهدف: تجنب Unsupported media type قبل الوصول للـ view.
        """
        try:
            ct = (request.content_type or "").lower()
        except Exception:
            ct = ""

        if (not ct) or ct.startswith("text/plain"):
            try:
                raw = request.body.decode("utf-8") if hasattr(request, "body") else None
            except Exception:
                raw = None
            if raw:
                import json
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, (dict, list)) else {}
                except Exception:
                    return {}
            # لا يوجد جسم نصي صالح؛ أعد قاموسًا فارغًا
            return {}

        # لباقي الأنواع، اعتمد على DRF parsers
        try:
            return request.data
        except Exception:
            # في حال فشل الـ parser، لا نفشل النداء ونعود ببيانات فارغة
            return {}

    def _early_payload_validation(self, request):
        """
        تحقّق مبكّر للحمولة:
        - يطبّع action
        - يقرأ GPS ويتحقق من الدقة
        - يحلّ location_id (نص/رقم) أو يلتقط تلقائيًا أقرب موقع ضمن نصف قطره
        - يقبل مفاتيح البصمة القديمة/الجديدة + alias + fallback
        - يتحقق من جهاز العميل إن كان مفعّلًا
        - يكتب لوج عربي مختصر
        - يملأ request._resolved_location ويهذّب data للاستخدام اللاحق
        """
        # استخدم _safe_data لدعم text/plain
        data = getattr(self, "_safe_data", lambda r: r.data)(request)

        # 1) تطبيع الإجراء
        def _normalize_action_incoming(v):
            if not v:
                return None
            x = str(v).strip().lower()
            mapping = {
                "checkin": "check_in", "check_in": "check_in",
                "checkout": "check_out", "check_out": "check_out",
                "early_checkout": "early_check_out",
                "early-checkout": "early_check_out",
                "early_check_out": "early_check_out",
            }
            return mapping.get(x)

        normalized_action = _normalize_action_incoming(data.get("action"))
        if normalized_action is None:
            return Response({
                "ok": False, "performed": False,
                "action": data.get("action"),
                "detail": "إجراء غير معروف",
                "reason_code": "INVALID_ACTION",
            }, status=status.HTTP_200_OK)

        # 2) GPS أولًا (نحتاجه للالتقاط التلقائي للموقع لاحقًا)
        try:
            acc = float(data.get("accuracy") or 0.0)
            lat = float(data.get("lat"))
            lng = float(data.get("lng"))
        except Exception:
            return self._deny(
                action=normalized_action,
                detail="إحداثيات غير صحيحة",
                reason_code="INVALID_COORDINATES"
            )

        MIN_ACC = 100.0
        if acc > MIN_ACC:
            return self._deny(
                action=normalized_action,
                detail="دقة GPS منخفضة",
                reason_code="GPS_ACCURACY_LOW",
                extra={"min_required": int(MIN_ACC), "accuracy": acc}
            )

        # 3) حلّ الموقع: (location_id نص/رقم) ثم fallback تلقائي لأقرب موقع ضمن نصف قطره
        #    - لا نرفض مباشرةً إن لم يوجد، بل نحاول الالتقاط من الإحداثيات.
        raw_loc_field = data.get("location_id") or data.get("location")
        raw_loc = raw_loc_field.strip() if isinstance(raw_loc_field, str) else raw_loc_field
        location = None

        # محاولة بالـ pk كما هو (يدعم نص/رقم)، ثم كـ int
        try:
            from .models import Location
        except Exception:
            try:
                from models import Location  # في حال هيكلة مختلفة
            except Exception:
                Location = None

        if Location is not None and raw_loc not in (None, "", 0, "0"):
            try:
                location = Location.objects.filter(pk=raw_loc).first()
            except Exception:
                location = None
            if location is None:
                try:
                    location = Location.objects.filter(pk=int(raw_loc)).first()
                except Exception:
                    location = None

        # إن لم يُعثر عليه، جرّب الالتقاط التلقائي من الإحداثيات باحترام نصف القطر
        if Location is not None and location is None:
            from math import radians, sin, cos, asin, sqrt

            def haversine_m(lat1, lon1, lat2, lon2):
                R = 6371000.0
                dlat = radians(lat2 - lat1)
                dlon = radians(lon2 - lon1)
                a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
                c = 2 * asin(sqrt(a))
                return R * c

            candidates = Location.objects.exclude(gps_coordinates__isnull=True)\
                                        .exclude(gps_coordinates__exact="")
            best = None
            best_d = None
            for L in candidates:
                try:
                    loc_lat, loc_lng = [float(x.strip()) for x in L.gps_coordinates.split(",", 1)]
                    d = haversine_m(lat, lng, loc_lat, loc_lng)
                    # احترم نصف القطر إن مٌعرّف
                    try:
                        radius = float(getattr(L, "gps_radius") or 0.0)
                    except Exception:
                        radius = 0.0
                    if radius and d > radius:
                        continue
                    if best is None or d < best_d:
                        best, best_d = L, d
                except Exception:
                    continue

            if best is not None:
                location = best
                # نحدّث data ليكمل التيار بقيَم صحيحة
                data["location_id"] = getattr(location, "id", None)

        # إن بقي None بعد كل المحاولات → رفض مع رسالة واضحة
        if location is None:
            return self._deny(
                action=normalized_action,
                detail="موقع غير محدد: مُعرّف الموقع غير صالح ولا يوجد موقع مناسب بالقرب.",
                reason_code="INVALID_LOCATION",
                extra={"got": (raw_loc if raw_loc not in (None, "", 0, "0") else None)}
            )

        # 4) مفاتيح البصمة (قديم/جديد) + alias + fallback آمن
        raw_ok = data.get("bio_ok")
        raw_ok2 = data.get("biometric_verified")
        bio_ok = bool(raw_ok if raw_ok is not None else raw_ok2)

        raw_method = (data.get("bio_method") or data.get("biometric_method") or "")
        bio_method = str(raw_method).lower().strip()

        alias = {
            "faceid": "face", "face_id": "face", "facial": "face",
            "touchid": "fingerprint", "touch_id": "fingerprint", "fp": "fingerprint",
            "code": "pin", "passcode": "pin", "password": "pin", "pin_code": "pin",
            "strong": "fingerprint", "weak": "pin"
        }
        bio_method = alias.get(bio_method, bio_method)

        # لو نجح التحقق ولم تصل طريقة، اعتبرها PIN (fallback)
        if bio_ok and bio_method == "":
            bio_method = "pin"

        if not bio_ok:
            return Response({
                "ok": False,
                "performed": False,
                "detail": "التحقق البيومتري فشل، لا يمكن تنفيذ العملية.",
                "reason_code": "BIO_FAIL",
            }, status=status.HTTP_403_FORBIDDEN)

        if bio_method not in ("fingerprint", "face", "pin"):
            return self._deny(
                action=normalized_action,
                detail="طريقة البصمة غير معروفة",
                reason_code="BIO_METHOD_UNKNOWN",
                extra={"accepted": ["fingerprint", "face", "pin"], "got": (bio_method or None)},
            )

        # 5) الجهاز (اختياري)
        device_hash = request.headers.get("X-Device-Hash") or data.get("device_hash")
        # لا تفشل إذا لم تتوفر دوال الربط في نسخة الخادم — اعتبرها غير مفعّلة
        try:
            binding_enabled = bool(self._device_binding_enabled())
        except AttributeError:
            binding_enabled = False
        if binding_enabled:
            try:
                is_allowed = bool(self._is_device_allowed(request.user, device_hash or ""))
            except AttributeError:
                # إذا لم تتوفر دالة الفحص، اسمح افتراضًا لتجنب تعطل الخدمة
                is_allowed = True
            if not device_hash or not is_allowed:
                return self._deny(
                    action=normalized_action,
                    detail="جهاز غير موثّق",
                    reason_code="DEVICE_NOT_TRUSTED"
                )

        # 6) لوج عربي للتشخيص
        try:
            usr = getattr(request, "user", None)
            uid = getattr(usr, "id", None) or getattr(usr, "pk", None)
            logger_api.info(
                "[حضور] المستخدم=%s الجهاز=%s الإجراء=%s الموقع=%s acc=%s",
                uid, device_hash, normalized_action, getattr(location, "id", raw_loc), acc
            )
        except Exception:
            pass

        # 7) تمرير القيم المحلولة للخطوات التالية
        request._resolved_location = location
        try:
            data["action"] = normalized_action
            data["bio_ok"] = bio_ok
            data["bio_method"] = bio_method
            data["location_id"] = getattr(location, "id", raw_loc)
        except Exception:
            pass

        return None


    def _enforce_shift_and_location(self, request):
        # استخدم القراءة الآمنة بدل request.data لتجنّب UnsupportedMediaType عند text/plain
        data = self._safe_data(request)

        normalized_action = _normalize_action_incoming(data.get("action"))
        if normalized_action is None:
            return self._deny(action=data.get("action"), detail="إجراء غير معروف", reason_code="INVALID_ACTION"), None

        # نافذة الوردية
        start, end, unrestricted, pre_buf, post_buf = get_current_shift_window(request.user)
        # Django 5 أزال timezone.utc؛ استخدم datetime.timezone.utc
        now_utc = dj_timezone.now().astimezone(dt.timezone.utc)
        if not unrestricted and start and end:
            start_buf = start - timedelta(minutes=pre_buf or 0)
            end_buf = end + timedelta(minutes=post_buf or 0)
            if not (start_buf <= now_utc <= end_buf):
                return self._deny(action=normalized_action, detail="خارج وقت الوردية", reason_code="OUTSIDE_SHIFT_WINDOW"), None

        # إحداثيات + الموقع
        try:
            lat = float(data.get("lat"))
            lng = float(data.get("lng"))
        except Exception:
            return self._deny(action=normalized_action, detail="إحداثيات غير صحيحة", reason_code="INVALID_COORDINATES"), None

        allowed, reason, _loc_id = is_location_allowed_for_user(request.user, lat, lng)
        if not allowed:
            return self._deny(action=normalized_action, detail=reason or "الموقع غير مسموح", reason_code="LOCATION_DENIED"), None

        return None, normalized_action

    # ===== دعم ربط الأجهزة (اختياري) =====
    def _device_binding_enabled(self) -> bool:
        """
        يحدد ما إذا كان تقييد الأجهزة مفعّلًا. يأخذ القيمة من الإعداد
        ENABLE_DEVICE_BINDING (افتراضيًا False)
        """
        try:
            return bool(getattr(settings, "ENABLE_DEVICE_BINDING", False))
        except Exception:
            return False

    def _is_device_allowed(self, user, device_hash: str) -> bool:
        """
        يتحقق إن كان الجهاز مسموحًا للمستخدم. نقبل كلا الصيغتين: الخام والمُهشّرة.
        """
        if not self._device_binding_enabled():
            return True
        if not device_hash:
            return False
        try:
            hashed = _device_hash(device_hash)
        except Exception:
            hashed = device_hash
        try:
            return TrustedDevice.objects.filter(
                user=user,
                deleted_at__isnull=True,
                device_hash__in=[device_hash, hashed],
            ).exists()
        except Exception:
            return False

    def post(self, request):
        # تنظيف (اختياري)
        cleanup_employee = (
            Employee.objects.select_related("user", "supervisor")
            .filter(user=request.user)
            .first()
        )
        if cleanup_employee:
            cleanup_now = dj_timezone.now()
            flag_absent_assignments_for_employee(cleanup_employee, as_of=cleanup_now, notify=True)
            close_stale_attendance_for_employee(cleanup_employee, as_of=cleanup_now, notify=True)

        prelim = self._early_payload_validation(request)
        if prelim is not None:
            return prelim

        early_fail, normalized_action = self._enforce_shift_and_location(request)
        if early_fail is not None:
            return early_fail

        # استخدم البيانات الآمنة التي تتعامل مع text/plain JSON أيضًا
        safe_data = self._safe_data(request)
        # طبّع location_id إلى نص لتجنّب خطأ "Not a valid string" حتى إن لم نستخدمه
        if isinstance(safe_data, dict) and 'location_id' in safe_data:
            try:
                val = safe_data.get('location_id')
                if val is None or (isinstance(val, str) and val.strip() == ''):
                    # اتركه كما هو (الحقل اختياري)
                    pass
                else:
                    safe_data['location_id'] = str(val)
            except Exception:
                # في أسوأ الأحوال احذف الحقل لتترك مهمة تحديد الموقع للسياق
                try:
                    safe_data.pop('location_id', None)
                except Exception:
                    pass
        ser = AttendanceCheckSerializer(
            data=safe_data,
            context={
                "request": request,
                "resolved_location": getattr(request, "_resolved_location", None),
                "normalized_bio": getattr(request, "_normalized_bio", None),
            },
        )
        if not ser.is_valid():
            # رسالة مفصلة
            err_text = []
            nice_hint = None
            for field, msgs in ser.errors.items():
                final_msgs = []
                for msg in (msgs if isinstance(msgs, (list, tuple)) else [msgs]):
                    msg_text = str(msg)
                    final_msgs.append(msg_text)
                    final_lower = msg_text.casefold()
                    if "valid uuid" in final_lower or "uuid" in final_lower:
                        nice_hint = ("تعذر تحديد موقع العمل. يرجى التأكد من اختيار الموقع الصحيح "
                                     "أو إعادة محاولة تحديد الموقع تلقائيًا ثم إعادة المحاولة.")
                err_text.append(f"{field}: {', '.join(final_msgs)}")

            nice = nice_hint or ("؛ ".join(err_text) if err_text else "الرجاء التحقق من الحقول المدخلة.")
            return Response({
                "ok": False, "performed": False,
                "action": normalized_action or safe_data.get("action"),
                "detail": f"تعذر معالجة الطلب. {nice}",
                "errors": ser.errors,
                "reason_code": "INVALID_PAYLOAD",
            }, status=status.HTTP_200_OK)

        if not ser.validated_data.get("biometric_verified", False):
            return Response(
                {
                    "ok": False,
                    "performed": False,
                    "detail": "التحقق البيومتري فشل، لا يمكن تسجيل الحضور.",
                    "reason_code": "BIO_FAIL",
                },
                status=status.HTTP_403_FORBIDDEN,
            )


        # القيم
        action            = normalized_action or ser.validated_data.get("action")
        employee          = ser.validated_data.get("employee")
        location          = ser.validated_data.get("location_obj")
        lat               = ser.validated_data.get("lat")
        lng               = ser.validated_data.get("lng")
        acc               = ser.validated_data.get("accuracy")
        raw_dist          = ser.validated_data.get("distance_m")
        dist              = float(raw_dist) if raw_dist is not None else 0.0
        radius            = ser.validated_data.get("location_radius_m")
        center_lat        = ser.validated_data.get("location_center_lat")
        center_lng        = ser.validated_data.get("location_center_lng")
        current_shift_obj = ser.validated_data.get("current_shift")
        current_assignment= ser.validated_data.get("current_assignment")

        (monitoring_payload,
         monitoring_active,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         monitoring_rule,
         monitoring_config,
         monitoring_pause) = _monitoring_details(location, employee=employee)

        shift_payload = _build_shift_payload(
            employee=employee,
            shift=current_shift_obj,
            assignment=current_assignment,
            allowed_start=ser.validated_data.get("shift_window_start"),
            allowed_end=ser.validated_data.get("shift_window_end"),
            location=location,
            within_shift=ser.validated_data.get("shift_within_window"),
        )

        violation_flag    = bool(ser.validated_data.get("violation", False))
        violation_reason  = ser.validated_data.get("violation_reason")
        violation_codes   = list(ser.validated_data.get("violation_codes") or [])

        now       = dj_timezone.now()
        now_local = _local_dt(now)

        start_dt  = ser.validated_data.get("shift_window_start")
        end_dt    = ser.validated_data.get("shift_window_end")
        blocked   = ser.validated_data.get("blocked")
        reason    = ser.validated_data.get("blocked_reason")
        within_shift_window = bool(ser.validated_data.get("shift_within_window"))

        monitoring_payload = dict(monitoring_payload or {})
        monitoring_payload.update({
            "within_shift_window": within_shift_window,
            "shift_window_start": _local_iso(start_dt),
            "shift_window_end": _local_iso(end_dt),
        })
        monitoring_should_follow = bool(monitoring_active and within_shift_window)

        if blocked:
            return self._deny(
                action=action,
                detail=reason or "⚠️ لا يمكن تنفيذ العملية في الوقت الحالي.",
                reason_code="BUSINESS_RULE_VIOLATION",
                start=start_dt, end=end_dt, now=now_local,
                monitoring=monitoring_payload,
                extra={
                    "should_monitor_location": monitoring_should_follow,
                    "shift": shift_payload,
                },
            )

        violation_escalated = False

        if action == "check_in":
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time").first())
            if open_rec:
                return self._deny(
                    action=action,
                    detail="⚠️ تم تسجيل حضور مسبقًا، لا يمكن تسجيل حضور آخر قبل الانصراف.",
                    reason_code="ALREADY_CHECKED_IN",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

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
                    reason_code="ALREADY_CHECKED_IN_TODAY",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

            rec = ser.save()
            update_fields = []
            if getattr(rec, "check_type", None) != action:
                rec.check_type = action
                update_fields.append("check_type")
            if getattr(rec, "timestamp", None) is None:
                rec.timestamp = now
                update_fields.append("timestamp")
            if getattr(rec, "is_violation", False):
                rec.is_violation = False
                update_fields.append("is_violation")
            if update_fields:
                rec.save(update_fields=update_fields)

            if violation_flag:
                _ = _apply_geofence_salary_deduction(employee, GEOFENCE_DEDUCTION_PERCENT)  # إن أردت الخصم فورًا
                violation_escalated = False  # الإنذار عند check_out/early حسب المدة

            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل حضورك بنجاح.",
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(location.id) if getattr(location, "id", None) else None,
                "location_name": getattr(location, "name", None),
                "distance_m": round(dist, 2) if raw_dist is not None else None,
                "location_center": {"lat": center_lat, "lng": center_lng, "radius_m": radius},
                "violation": violation_flag,
                "violation_reason": violation_reason,
                "violation_codes": violation_codes,
                "violation_warning_minutes": monitoring_grace_minutes,
                "violation_outside_minutes": None,
                "violation_escalated": violation_escalated,
                "monitoring": monitoring_payload,
                "should_monitor_location": monitoring_should_follow,
            }, status=status.HTTP_201_CREATED)

        if action == "check_out":
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
                    reason_code="EARLY_CHECKOUT_DONE",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(
                    action=action,
                    detail="لا يوجد سجل حضور مفتوح لإقفاله.",
                    reason_code="NO_OPEN_RECORD",
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

            rec.check_out_time = now_local
            rec.notes = (rec.notes or "") + f" | out lat={lat}, lng={lng}, acc={acc}, dist={round(dist, 2)}"
            rec.location = rec.location or location
            rec.check_type = action
            rec.timestamp = rec.timestamp or now
            update_fields = ["check_out_time", "notes", "location", "check_type", "timestamp"]
            if violation_flag or rec.is_violation:
                rec.is_violation = rec.is_violation or violation_flag
                update_fields.append("is_violation")
            rec.save(update_fields=update_fields)

            violation_outside_minutes = None
            if violation_flag and rec.check_in_time:
                violation_outside_minutes = (now_local - rec.check_in_time).total_seconds() / 60.0
                if violation_outside_minutes >= monitoring_grace_minutes:
                    # تسجيل مخالفة
                    _ = _apply_geofence_salary_deduction(employee, GEOFENCE_DEDUCTION_PERCENT)
                    violation_escalated = True

            LocationPing.objects.filter(employee=employee, violation_triggered=False).delete()

            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل انصرافك بنجاح.",
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(rec.location.id) if rec.location else None,
                "location_name": getattr(rec.location, "name", None) if rec.location else None,
                "distance_m": round(dist, 2) if raw_dist is not None else None,
                "location_center": {"lat": center_lat, "lng": center_lng, "radius_m": radius},
                "violation": violation_flag,
                "violation_reason": violation_reason,
                "violation_codes": violation_codes,
                "violation_warning_minutes": monitoring_grace_minutes,
                "violation_outside_minutes": violation_outside_minutes,
                "violation_escalated": violation_escalated,
                "monitoring": monitoring_payload,
                "should_monitor_location": False,
            }, status=status.HTTP_200_OK)

        if action == "early_check_out":
            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(
                    action=action,
                    detail="لا يوجد سجل حضور مفتوح لإقفاله.",
                    reason_code="NO_OPEN_RECORD",
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

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
                    reason_code="EARLY_CHECKOUT_ONCE_PER_DAY",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

            reason_txt = (request.data.get("early_reason") or request.data.get("note") or "").strip()
            file_obj   = request.FILES.get("early_attachment")
            if not reason_txt:
                return self._deny(
                    action=action,
                    detail="يجب كتابة سبب الانصراف المبكر.",
                    reason_code="EARLY_CHECKOUT_REASON_REQUIRED",
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
                )

            rec.check_out_time = now_local
            rec.early_checkout = True
            rec.early_reason   = reason_txt
            if file_obj:
                rec.early_attachment = file_obj
            rec.notes = (rec.notes or "") + f" | early-out lat={lat}, lng={lng}, acc={acc}, dist={round(dist, 2)}"
            rec.location = rec.location or location
            rec.check_type = action
            rec.timestamp = rec.timestamp or now
            update_fields = ["check_out_time", "early_checkout", "early_reason", "notes", "location", "check_type", "timestamp"]
            if file_obj:
                update_fields.append("early_attachment")
            if violation_flag or rec.is_violation:
                rec.is_violation = rec.is_violation or violation_flag
                update_fields.append("is_violation")
            rec.save(update_fields=update_fields)

            violation_outside_minutes = None
            if violation_flag and rec.check_in_time:
                violation_outside_minutes = (now_local - rec.check_in_time).total_seconds() / 60.0
                if violation_outside_minutes >= monitoring_grace_minutes:
                    _ = _apply_geofence_salary_deduction(employee, GEOFENCE_DEDUCTION_PERCENT)
                    violation_escalated = True

            LocationPing.objects.filter(employee=employee, violation_triggered=False).delete()

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
                "distance_m": round(dist, 2) if raw_dist is not None else None,
                "location_center": {"lat": center_lat, "lng": center_lng, "radius_m": radius},
                "violation": violation_flag,
                "violation_reason": violation_reason,
                "violation_codes": violation_codes,
                "violation_warning_minutes": monitoring_grace_minutes,
                "violation_outside_minutes": violation_outside_minutes,
                "violation_escalated": violation_escalated,
                "monitoring": monitoring_payload,
                "should_monitor_location": False,
            }, status=status.HTTP_200_OK)

        return self._deny(
            action=action,
            detail="إجراء غير مدعوم.",
            reason_code="UNSUPPORTED_ACTION",
            monitoring=monitoring_payload,
            extra={"should_monitor_location": monitoring_should_follow, "shift": shift_payload},
        )


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

        loc, dist, mode, within_radius = found
        la, ln = (None, None)
        if loc.gps_coordinates:
            try:
                la, ln = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
            except Exception:
                pass
        try:
            radius = float(loc.gps_radius)
        except (TypeError, ValueError):
            radius = None

        (monitoring_payload,
         monitoring_active,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         monitoring_rule,
         monitoring_config,
         monitoring_pause) = _monitoring_details(loc, employee=employee)

        assignment, _, window_start, window_end = _assignment_window_for(
            employee=employee,
            location=loc,
            reference=dj_timezone.now(),
        )
        within_shift_window = assignment is not None
        monitoring_payload = dict(monitoring_payload or {})
        monitoring_payload.update({
            "within_shift_window": within_shift_window,
            "shift_window_start": _local_iso(window_start),
            "shift_window_end": _local_iso(window_end),
        })
        data = {
            "detail": "تم تحديد الموقع" if within_radius else "تم العثور على أقرب موقع لكنك خارج النطاق.",
            "location_id": str(loc.id),
            "name": loc.name,
            "client_name": loc.client_name,
            "lat": la, "lng": ln,
            "radius": radius,
            "distance": round(dist, 2),
            "mode": mode,  # polygon | radius
            "within_radius": within_radius,
            "monitoring": monitoring_payload,
            "violation_grace_minutes": monitoring_grace_minutes,
            "should_monitor_location": False,
        }
        return Response(data, status=status.HTTP_200_OK)


class LocationPingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = LocationPingSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)

        employee = ser.validated_data["employee"]
        lat = ser.validated_data["lat"]
        lng = ser.validated_data["lng"]
        accuracy = ser.validated_data.get("accuracy")
        recorded_at = _make_aware(ser.validated_data.get("recorded_at") or dj_timezone.now())

        found = ser.find_best_location(employee, lat, lng)
        if not found:
            return Response({"detail": "لا يوجد موقع مكلَّف به ضمن النطاق."}, status=status.HTTP_404_NOT_FOUND)

        loc, dist, mode, within_radius = found
        radius = None
        if getattr(loc, "gps_radius", None):
            try:
                radius = float(loc.gps_radius)
            except (TypeError, ValueError):
                radius = None

        center_lat = center_lng = None
        if loc.gps_coordinates:
            try:
                center_lat, center_lng = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
            except Exception:
                pass

        (monitoring_payload,
         monitoring_active_config,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         monitoring_rule,
         monitoring_config,
         monitoring_pause) = _monitoring_details(loc, employee=employee)

        assignment, shift_obj, window_start, window_end = _assignment_window_for(
            employee=employee,
            location=loc,
            reference=recorded_at,
        )
        open_attendance = (AttendanceRecord.objects
                           .filter(employee=employee, check_out_time__isnull=True)
                           .order_by("-check_in_time")
                           .first())
        active_attendance = open_attendance
        if active_attendance:
            check_in_aw = _make_aware(active_attendance.check_in_time)
            if recorded_at < check_in_aw:
                active_attendance = None

        within_shift_window = assignment is not None
        tracking_active = bool(monitoring_active_config and within_shift_window and active_attendance)

        monitoring_payload = dict(monitoring_payload or {})
        monitoring_payload.update({
            "within_shift_window": within_shift_window,
            "tracking_active": tracking_active,
            "shift_window_start": _local_iso(window_start),
            "shift_window_end": _local_iso(window_end),
        })

        # تأكد من داخل نافذة الوردية بحسب إعداد شركتك (اختياري)
        start, end, unrestricted, pre_buf, post_buf = get_current_shift_window(request.user)
        # Django 5 compatibility — لا تستخدم timezone.utc
        now = timezone.now().astimezone(dt.timezone.utc)
        if not unrestricted and start and end:
            start_buf = start - timedelta(minutes=pre_buf or 0)
            end_buf = end + timedelta(minutes=post_buf or 0)
            if not (start_buf <= now <= end_buf):
                return fail('خارج وقت الوردية', code='outside_shift', status=400)

        ping = LocationPing.objects.create(
            employee=employee,
            location=loc,
            latitude=lat,
            longitude=lng,
            accuracy=accuracy,
            distance_m=dist,
            within_radius=within_radius,
            recorded_at=recorded_at,
        )

        violation_triggered = False
        outside_minutes = None
        violation_reason = None
        violation_codes: list[str] = []
        paused = bool(monitoring_pause)
        if tracking_active and not within_radius:
            violation_codes = ["outside_polygon"] if mode == "polygon" else ["outside_radius"]
            violation_reason = (
                "تم رصد الجهاز خارج حدود الموقع المعتمد."
                if mode == "polygon"
                else "تم رصد الجهاز خارج نطاق الموقع المسموح به."
            )

            last_inside = (
                LocationPing.objects
                .filter(employee=employee, within_radius=True, recorded_at__lte=recorded_at)
                .order_by('-recorded_at')
                .first()
            )
            outside_start = _make_aware(last_inside.recorded_at) if last_inside else None
            if outside_start is None:
                last_ping = (
                    LocationPing.objects
                    .filter(employee=employee, recorded_at__lte=recorded_at)
                    .order_by('-recorded_at')
                    .first()
                )
                if last_ping and not last_ping.within_radius:
                    outside_start = _make_aware(last_ping.recorded_at)
            if outside_start is None:
                outside_start = recorded_at
            outside_minutes = max(0.0, (recorded_at - outside_start).total_seconds() / 60.0)

            if (not paused) and (outside_minutes >= monitoring_grace_minutes):
                existing_violation = LocationPing.objects.filter(
                    employee=employee,
                    violation_triggered=True,
                    recorded_at__gte=outside_start,
                ).exists()
                if not existing_violation:
                    # تصعيد وخصم إن لزم
                    _ = _apply_geofence_salary_deduction(employee, GEOFENCE_DEDUCTION_PERCENT)
                    ping.violation_triggered = True
                    ping.save(update_fields=["violation_triggered"])
                    violation_triggered = True

        next_ping_seconds = None
        if tracking_active:
            base_next = monitoring_ping_seconds
            outside_next = monitoring_outside_seconds or monitoring_ping_seconds
            candidate = base_next if within_radius else outside_next
            if candidate and candidate > 0:
                next_ping_seconds = candidate

        data = {
            "ok": True,
            "within_radius": within_radius,
            "distance": round(dist, 2) if dist is not None else None,
            "radius": radius,
            "mode": mode,
            "location": {
                "id": str(loc.id),
                "name": loc.name,
                "client_name": getattr(loc, "client_name", ""),
                "center_lat": center_lat,
                "center_lng": center_lng,
            },
            "violation": bool(tracking_active and not within_radius),
            "violation_reason": violation_reason,
            "violation_codes": violation_codes,
            "violation_triggered": violation_triggered,
            "outside_minutes": outside_minutes if tracking_active else None,
            "recorded_at": _local_iso(recorded_at),
            "violation_warning_minutes": monitoring_grace_minutes,
            "monitoring": monitoring_payload,
            "should_monitor_location": tracking_active,
            "next_ping_seconds": next_ping_seconds,
        }
        return Response(data, status=status.HTTP_200_OK)


class AttendanceLastForMeView(APIView):
    """
    تم تحويله إلى POST:
    POST /api/v1/attendance/last/
    يعيد آخر سجل للموظف الحالي. 200 مع البيانات | 204 إذا لا يوجد أي سجل
    """
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _determine_action(record: AttendanceRecord) -> str:
        if record.check_type:
            return record.check_type
        if getattr(record, "early_checkout", False):
            return "early_check_out"
        if record.check_out_time:
            return "check_out"
        return "check_in"

    @staticmethod
    def _shift_window(record: AttendanceRecord) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
        shift = getattr(record, "shift", None)
        reference_dt = (
            record.check_in_time
            or record.timestamp
            or record.created_at
        )
        if not shift or reference_dt is None:
            return None, None

        tz = dj_timezone.get_current_timezone()
        if dj_timezone.is_naive(reference_dt):
            reference_dt = dj_timezone.make_aware(reference_dt, tz)
        local_ref = dj_timezone.localtime(reference_dt, timezone=tz)

        start_naive = dt.datetime.combine(local_ref.date(), shift.start_time)
        end_naive = dt.datetime.combine(local_ref.date(), shift.end_time)

        start = dj_timezone.make_aware(start_naive, tz) if dj_timezone.is_naive(start_naive) else start_naive
        end = dj_timezone.make_aware(end_naive, tz) if dj_timezone.is_naive(end_naive) else end_naive

        if end <= start:
            end = end + timedelta(days=1)

        return start, end

    @staticmethod
    def _effective_local_datetime(record: AttendanceRecord) -> Optional[dt.datetime]:
        candidates = [
            getattr(record, "timestamp", None),
            getattr(record, "updated_at", None),
            getattr(record, "check_out_time", None),
            getattr(record, "check_in_time", None),
            getattr(record, "created_at", None),
        ]
        for candidate in candidates:
            local_dt = _local_dt(candidate)
            if local_dt:
                return local_dt
        return None

    def _serialize_record(
        self,
        record: AttendanceRecord,
        *,
        effective_local: Optional[dt.datetime] = None,
        now_local: Optional[dt.datetime] = None,
    ) -> dict[str, object]:
        base = AttendanceMiniSerializer(record).data
        location_obj = getattr(record, "location", None)
        employee_obj = getattr(record, "employee", None)

        (monitoring_payload,
         monitoring_active,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         _monitoring_rule,
         _monitoring_config,
         _monitoring_pause) = _monitoring_details(location_obj, employee=employee_obj)

        action = self._determine_action(record)
        recorded_at = (
            record.timestamp
            or record.updated_at
            or record.check_out_time
            or record.check_in_time
        )

        shift_start, shift_end = self._shift_window(record)
        assignment_window = _assignment_window_for(
            employee=employee_obj,
            location=location_obj,
            reference=now_local or dj_timezone.now(),
        )
        assignment_obj, _, window_start, window_end = assignment_window
        if window_start is None and shift_start is not None:
            window_start = shift_start
        if window_end is None and shift_end is not None:
            window_end = shift_end

        shift_start_local = _local_dt(window_start) if window_start else None
        shift_end_local = _local_dt(window_end) if window_end else None

        recorded_at_local = _local_dt(recorded_at)
        recorded_at_iso = recorded_at_local.isoformat() if recorded_at_local else None
        timestamp_iso = _local_iso(record.timestamp) if record.timestamp else None
        shift_start_iso = shift_start_local.isoformat() if shift_start_local else None
        shift_end_iso = shift_end_local.isoformat() if shift_end_local else None

        effective_local = effective_local or self._effective_local_datetime(record)
        now_local = now_local or _local_dt(dj_timezone.now())
        is_today = (
            bool(effective_local and now_local)
            and effective_local.date() == now_local.date()
        )
        within_shift = True
        if shift_start_local and shift_end_local and now_local:
            within_shift = shift_start_local <= now_local <= shift_end_local
        monitoring_payload = dict(monitoring_payload or {})
        monitoring_payload.update({
            "within_shift_window": within_shift,
            "shift_window_start": shift_start_iso,
            "shift_window_end": shift_end_iso,
        })
        should_monitor = bool(
            monitoring_active
            and getattr(record, "check_out_time", None) is None
            and within_shift
        )
        next_ping_seconds = None
        if should_monitor:
            base_next = monitoring_ping_seconds
            outside_next = monitoring_outside_seconds or monitoring_ping_seconds
            candidate = base_next if within_shift else outside_next
            if candidate and candidate > 0:
                next_ping_seconds = candidate

        payload: dict[str, object] = {
            "ok": True,
            "detail": f"آخر تسجيل: {'الحضور' if action=='check_in' else ('الانصراف' if action=='check_out' else 'الانصراف المبكر')}.",
            "message": f"آخر تسجيل: {action}.",
            "record_id": str(record.id),
            "action": action,
            "attendance_action": action,
            "type": action,
            "recorded_at": recorded_at_iso,
            "timestamp": timestamp_iso,
            "note": record.notes,
            "notes": record.notes,
            "biometric_verified": record.biometric_verified,
            "biometric_method": record.biometric_method,
            "biometric_attempts": record.biometric_attempts,
            "unrestricted": shift_start is None and shift_end is None,
            "shift_window_start": shift_start_iso,
            "shift_window_end": shift_end_iso,
            "effective_recorded_at": effective_local.isoformat() if effective_local else recorded_at_iso,
            "is_today": is_today,
            "within_shift": within_shift,
            "should_monitor_location": should_monitor,
            "violation": record.is_violation,
            "violation_warning_minutes": monitoring_grace_minutes,
            "monitoring": monitoring_payload,
            "next_ping_seconds": next_ping_seconds,
        }

        shift_payload = _build_shift_payload(
            employee=employee_obj,
            shift=getattr(record, "shift", None),
            assignment=None,
            allowed_start=shift_start,
            allowed_end=shift_end,
            location=location_obj,
            within_shift=within_shift,
        )
        if shift_payload:
            payload["shift"] = shift_payload

        if employee_obj:
            payload["employee"] = getattr(employee_obj, "full_name", None)
            payload.setdefault("employee_id", str(employee_obj.id))

        if location_obj:
            payload["location"] = getattr(location_obj, "name", None)
            payload["location_name"] = getattr(location_obj, "name", None)
            client_name = getattr(location_obj, "client_name", None)
            if client_name:
                payload["client_name"] = client_name
            location_id = getattr(location_obj, "id", None)
            if location_id is not None:
                payload["location_id"] = str(location_id)

        last_ping = (
            LocationPing.objects
            .filter(employee=employee_obj)
            .order_by("-recorded_at")
            .first()
            if employee_obj
            else None
        )
        if last_ping:
            last_ping_local = _local_dt(last_ping.recorded_at)
            payload["last_location_ping"] = {
                "recorded_at": last_ping.recorded_at.isoformat(),
                "recorded_at_local": last_ping_local.isoformat() if last_ping_local else None,
                "latitude": last_ping.latitude,
                "longitude": last_ping.longitude,
                "accuracy": last_ping.accuracy,
                "distance_m": last_ping.distance_m,
                "within_radius": last_ping.within_radius,
                "violation_triggered": last_ping.violation_triggered,
                "is_today": (
                    last_ping_local.date() == now_local.date()
                    if last_ping_local and now_local
                    else None
                ),
            }

        combined = dict(base)
        combined.update(payload)
        return combined

    def post(self, request):
        try:
            emp = Employee.objects.get(user=request.user)
        except Employee.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        rec = (AttendanceRecord.objects
               .filter(employee=emp)
               .select_related("location")
               .order_by("-updated_at", "-id")
               .first())

        if not rec:
            return Response(status=status.HTTP_204_NO_CONTENT)

        effective_local = self._effective_local_datetime(rec)
        now_local = _local_dt(dj_timezone.now())
        shift_start, shift_end = self._shift_window(rec)
        shift_payload = _build_shift_payload(
            employee=emp,
            shift=getattr(rec, "shift", None),
            assignment=None,
            allowed_start=shift_start,
            allowed_end=shift_end,
            location=getattr(rec, "location", None),
            within_shift=None,
        )
        if not effective_local or (now_local and effective_local.date() != now_local.date()):
            return Response(
                {
                    "ok": False,
                    "detail": "لا يوجد سجل حضور لهذا اليوم.",
                    "message": "لا يوجد سجل حضور لهذا اليوم.",
                    "latest_record_id": str(rec.id),
                    "latest_record_action": self._determine_action(rec),
                    "latest_recorded_at": effective_local.isoformat() if effective_local else _local_iso(rec.timestamp),
                    "shift": shift_payload,
                },
                status=status.HTTP_200_OK,
            )

        data = self._serialize_record(rec, effective_local=effective_local, now_local=now_local)
        return Response(data, status=status.HTTP_200_OK)


class AttendanceExistsView(APIView):
    """
    تم تحويله إلى POST:
    POST /api/v1/attendance/exists/  مع body: {"id": "<uuid|string>"}
    200: {"exists": true|false}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pk = (request.data.get("id") or request.data.get("pk") or request.data.get("attendance_id") or "").strip()
        exists = AttendanceRecord.objects.filter(id=pk).exists() if pk else False
        return Response({"exists": bool(exists)}, status=status.HTTP_200_OK)


# =============== التقارير والطلبات والسلف (POST-only لقوائم) ===============

class GuardReportListCreateView(OptimizedQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        - إن كان body يحتوي حقول إنشاء -> إنشاء تقرير
        - إن كان body فارغ أو فيه {list:true} -> إرجاع قائمة تقاريري
        """
        employee = _require_guard_employee(request.user)
        is_list = (request.data.get("list") is True) or (not request.data) or (request.data.get("action") == "list")
        if is_list:
            qs = (Report.objects
                  .filter(employee=employee)
                  .select_related("location")
                  .prefetch_related("attachments")
                  .order_by("-created_at"))
            data = ReportSerializer(qs, many=True).data
            return Response({"results": data}, status=status.HTTP_200_OK)

        ser = ReportSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            ser.save(employee=employee)
        return Response(ser.data, status=status.HTTP_201_CREATED)


class GuardRequestListCreateView(OptimizedQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        POST-only للائحة/إنشاء الطلبات
        """
        employee = _require_guard_employee(request.user)
        is_list = (request.data.get("list") is True) or (not request.data) or (request.data.get("action") == "list")
        if is_list:
            qs = (Request.objects
                  .filter(employee=employee)
                  .select_related("approver")
                  .order_by("-created_at"))
            data = RequestSerializer(qs, many=True).data
            return Response({"results": data}, status=status.HTTP_200_OK)

        ser = RequestSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save(employee=employee)
        return Response(ser.data, status=status.HTTP_201_CREATED)


class GuardAdvanceListCreateView(OptimizedQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        POST-only للائحة/إنشاء السلف
        """
        employee = _require_guard_employee(request.user)
        is_list = (request.data.get("list") is True) or (not request.data) or (request.data.get("action") == "list")
        if is_list:
            qs = Advance.objects.filter(employee=employee).order_by("-requested_at")
            data = AdvanceSerializer(qs, many=True).data
            return Response({"results": data}, status=status.HTTP_200_OK)

        ctx = {"request": request, "employee": employee}
        ser = AdvanceSerializer(data=request.data, context=ctx)
        ser.is_valid(raise_exception=True)
        ser.save(employee=employee)
        return Response(ser.data, status=status.HTTP_201_CREATED)


# =============== المهام (POST-only) ===============

class GuardTaskListView(OptimizedQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        POST-only لجلب المهام. فلتر الحالة يمكن تمريره في body: {"status": "..."} أو {"status": "active"}
        """
        employee = _require_guard_employee(request.user)
        status_filter = (request.data.get('status') or '').strip().lower()
        qs = Task.objects.filter(assigned_to=employee).select_related('location').order_by('-due_date', '-created_at')
        if status_filter:
            if status_filter == 'active':
                qs = qs.exclude(status='completed')
            elif status_filter in {choice[0] for choice in Task.STATUS_CHOICES}:
                qs = qs.filter(status=status_filter)
        data = TaskMiniSerializer(qs, many=True).data
        return Response({"results": data}, status=status.HTTP_200_OK)


class GuardTaskUpdateView(OptimizedQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """
        تحويل PATCH -> POST لتحديث حالة مهمة
        body: {"status": "...", "status_note": "..."}
        """
        employee = _require_guard_employee(request.user)
        try:
            task = Task.objects.select_related('location').get(id=pk, assigned_to=employee)
        except Task.DoesNotExist as exc:
            raise NotFound("لم يتم العثور على المهمة") from exc

        serializer = GuardTaskUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']
        status_note = serializer.validated_data.get('status_note') or ''

        if new_status not in TASK_STATUS_FLOW:
            return Response({"detail": "الحالة الجديدة غير مدعومة."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            current_index = TASK_STATUS_FLOW.index(task.status)
            target_index = TASK_STATUS_FLOW.index(new_status)
        except ValueError:
            return Response({"detail": "لا يمكن تحديث هذه المهمة."}, status=status.HTTP_400_BAD_REQUEST)

        if target_index < current_index:
            return Response({"detail": "لا يمكن الرجوع إلى حالة سابقة."}, status=status.HTTP_400_BAD_REQUEST)

        if target_index > current_index + 1:
            return Response({"detail": "يجب تحديث حالة المهمة بالتسلسل."}, status=status.HTTP_400_BAD_REQUEST)

        updated_fields = []
        if task.status != new_status:
            task.status = new_status
            updated_fields.append('status')

        if status_note != (task.status_note or ''):
            task.status_note = status_note
            updated_fields.append('status_note')

        if updated_fields:
            updated_fields.append('updated_at')
            task.save(update_fields=updated_fields)

        return Response(TaskMiniSerializer(task).data, status=status.HTTP_200_OK)


# =============== الزي (POST-only للقائمة) ===============

class GuardUniformItemListView(OptimizedQuerysetMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        _require_guard_employee(request.user)
        items = UniformItem.objects.order_by('name')
        data = [
            {
                'id': str(item.id),
                'name': item.name,
                'price': str(item.price),
            }
            for item in items
        ]
        return Response({'results': data}, status=status.HTTP_200_OK)


# =============== شاشات المراقبة (Admin) ===============

@staff_member_required
def location_dashboard_view(request):
    return render(
        request,
        "api_guard/location_dashboard.html",
        {
            "warning_minutes": GEOFENCE_WARNING_MINUTES,
        },
    )


@staff_member_required
def location_dashboard_feed(request):
    latest_ping = LocationPing.objects.filter(employee=OuterRef("pk")).order_by("-recorded_at")

    employees = (
        Employee.objects
        .select_related("user", "supervisor")
        .prefetch_related("locations")
        .annotate(
            last_ping_at=Subquery(latest_ping.values("recorded_at")[:1]),
            last_lat=Subquery(latest_ping.values("latitude")[:1]),
            last_lng=Subquery(latest_ping.values("longitude")[:1]),
            last_accuracy=Subquery(latest_ping.values("accuracy")[:1]),
            last_distance=Subquery(latest_ping.values("distance_m")[:1]),
            last_within=Subquery(latest_ping.values("within_radius")[:1]),
            last_violation=Subquery(latest_ping.values("violation_triggered")[:1]),
            last_location_id=Subquery(latest_ping.values("location_id")[:1]),
        )
    )

    location_ids = {emp.last_location_id for emp in employees if getattr(emp, "last_location_id", None)}
    locations_map = {loc.id: loc for loc in Location.objects.filter(id__in=location_ids)}

    now = dj_timezone.now()
    now_local = _local_dt(now) or now
    results = []
    for emp in employees:
        last_recorded_raw = getattr(emp, "last_ping_at", None)
        last_recorded = _local_dt(last_recorded_raw)
        last_lat = getattr(emp, "last_lat", None)
        last_lng = getattr(emp, "last_lng", None)
        if last_recorded is None and last_lat is None and last_lng is None:
            continue

        minutes_since = None
        if last_recorded:
            minutes_since = round((now_local - last_recorded).total_seconds() / 60.0, 1)

        loc = locations_map.get(getattr(emp, "last_location_id", None))
        loc_center = None
        loc_radius = None
        if loc:
            if loc.gps_coordinates:
                try:
                    lat_c, lng_c = [float(x.strip()) for x in loc.gps_coordinates.split(",", 1)]
                    loc_center = {"lat": lat_c, "lng": lng_c}
                except Exception:
                    loc_center = None
            if loc.gps_radius:
                try:
                    loc_radius = float(loc.gps_radius)
                except Exception:
                    loc_radius = None

        results.append({
            "employee_id": emp.id,
            "employee_name": emp.full_name,
            "phone": emp.phone_number,
            "supervisor": getattr(emp.supervisor, "full_name", None),
            "last_ping": {
                "recorded_at": last_recorded.isoformat() if last_recorded else None,
                "latitude": last_lat,
                "longitude": last_lng,
                "accuracy": getattr(emp, "last_accuracy", None),
                "distance_m": getattr(emp, "last_distance", None),
                "within_radius": getattr(emp, "last_within", None),
                "violation_triggered": getattr(emp, "last_violation", None),
                "minutes_since": minutes_since,
            },
            "location": {
                "id": getattr(loc, "id", None),
                "name": getattr(loc, "name", None),
                "client_name": getattr(loc, "client_name", None),
                "center": loc_center,
                "radius": loc_radius,
            },
        })

    return JsonResponse({
        "warning_minutes": GEOFENCE_WARNING_MINUTES,
        "now": now_local.isoformat() if now_local else now.isoformat(),
        "results": results,
    })
