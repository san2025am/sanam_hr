from __future__ import annotations
# تعديل لوقت ارسال النبضات وتحققات
import datetime as dt
import hashlib
import secrets
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from typing import Optional, Sequence

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone as dj_timezone
from django.db import IntegrityError
from django.db.models import F, OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required

from django.contrib.auth import authenticate, get_user_model
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

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
from .services.attendance import close_stale_attendance_for_employee
from .sms import send_sms_twilio


User = get_user_model()


logger = logging.getLogger(__name__)

# Default to 60 minutes (1 hour) so the violation aligns with the business rule
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


def _monitoring_details(
    location,
) -> tuple[dict[str, object], bool, int, Optional[int], Optional[int], Optional[ViolationRule], Optional[LocationMonitoringConfig]]:
    """
    يعيد (payload, active, grace_minutes, ping_seconds, outside_seconds, rule, config).
    """
    config: Optional[LocationMonitoringConfig] = None
    rule: Optional[ViolationRule] = None
    active = False
    ping_seconds: Optional[int] = None
    grace_minutes = GEOFENCE_WARNING_MINUTES

    if location:
        try:
            config = location.monitoring_config  # type: ignore[attr-defined]
        except LocationMonitoringConfig.DoesNotExist:
            config = None

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
    return payload, active, grace_minutes, ping_seconds, outside_seconds, rule, config


def _send_geofence_alert(
    *,
    employee: Employee,
    location,
    reason: str,
    distance: Optional[float],
    radius: Optional[float],
    outside_minutes: Optional[float],
    deduction_percent: Optional[Decimal],
    deduction_value: Optional[Decimal],
    warning_minutes: Optional[int] = None,
) -> None:
    location_name = getattr(location, "name", "الموقع المحدد") if location else "الموقع المحدد"
    client_name = getattr(location, "client_name", "") if location else ""
    distance_txt = f"{round(distance or 0.0, 2)} متر"
    radius_txt = f"{int(radius or 0)} متر"
    duration_txt = ""
    if outside_minutes is not None:
        duration_txt = f" مدة الابتعاد التقريبية {int(round(outside_minutes))} دقيقة."
    deduction_txt = ""
    if deduction_value is not None and deduction_value > 0:
        percent_part = ""
        if deduction_percent is not None and deduction_percent > 0:
            percent_part = f" بنسبة {_format_decimal(deduction_percent)}%"
        deduction_txt = (
            f" تم تطبيق خصم{percent_part}"
            f" بقيمة {_format_decimal(deduction_value)}."
        )

    limit_minutes = warning_minutes or GEOFENCE_WARNING_MINUTES
    message = (
        f"تنبيه مخالفة موقع للحارس {employee.full_name}."
        f" السبب: {reason or 'خارج نطاق الموقع'}."
        f" الموقع: {location_name}"
    )
    if client_name:
        message = f"{message} - العميل: {client_name}"
    message = (
        f"{message}. المسافة الحالية عن مركز الموقع {distance_txt} مقابل نطاق مسموح {radius_txt}."
        f"{duration_txt} يجب عدم تجاوز {limit_minutes} دقيقة خارج النطاق."
        f"{deduction_txt}"
    )

    emails = []
    employee_email = getattr(getattr(employee, "user", None), "email", None)
    if employee_email:
        emails.append(employee_email)
    supervisor = getattr(employee, "supervisor", None)
    supervisor_email = getattr(getattr(supervisor, "user", None), "email", None)
    if supervisor_email:
        emails.append(supervisor_email)
    unique_emails = list({addr for addr in emails if addr})
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    if unique_emails and from_email:
        try:
            send_mail(
                subject="تنبيه مخالفة الخروج عن الموقع",
                message=message,
                from_email=from_email,
                recipient_list=unique_emails,
                fail_silently=True,
            )
        except Exception as exc:  # pragma: no cover - depends on backend
            logger.warning("Failed to send geofence violation email: %s", exc)

    sms_numbers = []
    if getattr(employee, "phone_number", None):
        sms_numbers.append(employee.phone_number)
    if supervisor and getattr(supervisor, "phone_number", None):
        sms_numbers.append(supervisor.phone_number)
    for number in {num for num in sms_numbers if num}:
        try:
            send_sms_twilio(number, message)
        except Exception as exc:  # pragma: no cover - external service
            logger.warning("Failed to send geofence violation SMS to %s: %s", number, exc)


def record_geofence_violation(
    *,
    employee: Employee,
    location,
    reason: Optional[str],
    distance: Optional[float],
    radius: Optional[float],
    codes: Sequence[str] | None,
    outside_minutes: Optional[float],
    attendance_record: Optional[AttendanceRecord] = None,
    warning_minutes: Optional[int] = None,
    violation_rule: Optional[ViolationRule] = None,
) -> EmployeeViolation:
    summary = reason or "تم رصد خروج عن نطاق الموقع المحدد."
    dist_text = f"{round(distance or 0.0, 2)}م"
    radius_text = f"{int(radius or 0)}م"
    duration_text = None
    if outside_minutes is not None:
        duration_text = f"{int(round(outside_minutes))} دقيقة تقريباً"

    rule_obj = violation_rule
    if rule_obj is None:
        rule_obj, _created = ViolationRule.objects.get_or_create(
            title=GEOFENCE_RULE_TITLE,
            defaults={
                "description": GEOFENCE_RULE_DESCRIPTION,
                "default_action": "deduct" if GEOFENCE_DEDUCTION_PERCENT > 0 else "warn",
                "default_deduction_percent": GEOFENCE_DEDUCTION_PERCENT,
            },
        )
    rule_percent = _decimal_or_zero(getattr(rule_obj, "default_deduction_percent", None))
    deduction_percent = rule_percent if rule_percent > 0 else GEOFENCE_DEDUCTION_PERCENT
    deduction_value = _apply_geofence_salary_deduction(employee, deduction_percent)
    if deduction_value <= 0:
        deduction_percent = Decimal("0")
    else:
        updates = {}
        if rule_obj.default_action != "deduct":
            updates["default_action"] = "deduct"
        if rule_percent <= 0 and deduction_percent > 0:
            updates["default_deduction_percent"] = deduction_percent
        if updates:
            for field, value in updates.items():
                setattr(rule_obj, field, value)
            rule_obj.save(update_fields=list(updates.keys()))

    if attendance_record:
        note_parts = []
        if attendance_record.notes:
            note_parts.append(attendance_record.notes)
        note = f"[GEOFENCE] {summary} (المسافة {dist_text} / النطاق {radius_text})"
        if duration_text:
            note = f"{note} - مدة الابتعاد {duration_text}"
        if deduction_value > 0:
            note = (
                f"{note} - خصم {_format_decimal(deduction_percent)}%"
                f" بقيمة {_format_decimal(deduction_value)}"
            )
        note_parts.append(note)
        attendance_record.notes = "\n".join(part for part in note_parts if part)
        attendance_record.is_violation = True
        attendance_record.save(update_fields=["notes", "is_violation"])

    warning_level = (
        EmployeeViolation.objects.filter(employee=employee, rule=rule_obj).count() + 1
    )

    description = f"{summary} المسافة الحالية {dist_text} (النطاق {radius_text})."
    if duration_text:
        description = f"{description} استمر الابتعاد لمدة {duration_text}."
    if codes:
        description = f"{description} الرموز: {', '.join(codes)}."
    if deduction_value > 0:
        description = (
            f"{description} تم تطبيق خصم بنسبة {_format_decimal(deduction_percent)}%"
            f" بقيمة {_format_decimal(deduction_value)}."
        )

    violation = EmployeeViolation.objects.create(
        employee=employee,
        rule=rule_obj,
        reported_by=getattr(employee, "supervisor", None),
        location=location,
        description=description,
        warning_level=warning_level,
        deduction_value=deduction_value,
    )

    _send_geofence_alert(
        employee=employee,
        location=location,
        reason=summary,
        distance=distance,
        radius=radius,
        outside_minutes=outside_minutes,
        deduction_percent=deduction_percent if deduction_percent > 0 else None,
        deduction_value=deduction_value if deduction_value > 0 else None,
        warning_minutes=warning_minutes,
    )
    return violation


def _purge_location_pings_for_employee(employee: Employee) -> None:
    if not employee:
        return
    LocationPing.objects.filter(employee=employee, violation_triggered=False).delete()


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
            return Response({"detail": "اسم المستخدم/كلمة المرور مطلوبة"}, status=400)

        user = authenticate(request, username=username, password=password)
        if not user:
            return Response({"detail": "بيانات دخول غير صحيحة"}, status=401)
        if not user.is_active:
            return Response({"detail": "الحساب غير مُفعل"}, status=403)

        role_name = getattr(getattr(user, "role", None), "name", None)
        if (role_name or "").strip().casefold() not in {n.casefold() for n in GUARD_ROLE_NAMES}:
            return Response({"detail": "الدخول متاح لحُراس الأمن فقط"}, status=403)

        try:
            employee = Employee.objects.select_related("user", "user__role").get(user=user)
            Salary.objects.get_or_create(employee=employee)
        except Employee.DoesNotExist:
            return Response({"detail": "لا يوجد ملف موظف مرتبط بهذا المستخدم"}, status=404)

        device_id = (request.data.get("device_id") or "").strip()
        device_name = (request.data.get("device_name") or "").strip()
        challenge_id_raw = request.data.get("challenge_id")
        otp_code_raw = request.data.get("otp_code")
        challenge_id = (challenge_id_raw or "").strip()
        otp_code = (otp_code_raw or "").strip()

        if not device_id:
            return Response({"detail": "معرّف الجهاز مفقود. يرجى تحديث التطبيق."}, status=400)

        now = dj_timezone.now()
        device_hash = _device_hash(device_id)
        other_user_entry = (
            TrustedDevice.objects
            .filter(device_hash=device_hash)
            .exclude(user=user)
            .first()
        )
        if other_user_entry:
            return Response({
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
                    return Response({"detail": "طلب التحقق غير صالح"}, status=400)

                if challenge.is_expired:
                    return Response({"detail": "انتهت صلاحية رمز التحقق"}, status=400)
                if challenge.attempts >= 5:
                    return Response({"detail": "تم تجاوز عدد المحاولات المسموح بها"}, status=429)

                if _hash_code(otp_code) != challenge.code_hash:
                    challenge.attempts += 1
                    challenge.save(update_fields=["attempts", "updated_at"])
                    return Response({"detail": "رمز التحقق غير صحيح"}, status=400)

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
                    return Response({
                        "detail": "هذا الجهاز غير موثوق ويستلزم التحقق، لكن لا يوجد بريد إلكتروني لإرسال الرمز. يرجى التواصل مع المسؤول لتحديث بياناتك.",
                        "code": "no_email_available",
                    }, status=400)

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
                except Exception as exc:
                    logger.exception("Failed to dispatch device OTP for user %s", user.pk)
                    if getattr(settings, "DEBUG_SMS_ECHO", False):
                        return Response({
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
                }, status=202)

        if active_trusted_device:
            _enforce_single_trusted_device(
                user=user,
                active_device_hash=active_trusted_device.device_hash,
                now=now,
            )

        emp_data = EmployeeMeSerializer(employee).data
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


class GuardMeView(APIView):
    """يعيد بيانات الموظف الحالي."""
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
# Attendance
# =========================

class AttendanceCheckAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _deny(self, *, action, detail, reason_code,
              start=None, end=None, now=None, extra=None, monitoring=None):
        payload = {
            "ok": False,
            "performed": False,
            "action": action,
            "detail": detail,
            "reason_code": reason_code,
        }
        wnd = {}
        if start is not None: wnd["from"] = start
        if end   is not None: wnd["to"]   = end
        if now   is not None: wnd["now"]  = now
        if wnd: payload["window"] = wnd
        if extra: payload.update(extra)
        if monitoring is not None:
            payload["monitoring"] = monitoring
        return Response(payload, status=status.HTTP_200_OK)

    def post(self, request):
        cleanup_employee = (Employee.objects
                              .select_related("user", "supervisor")
                              .filter(user=request.user)
                              .first())
        if cleanup_employee:
            close_stale_attendance_for_employee(
                cleanup_employee,
                as_of=dj_timezone.now(),
                notify=True,
            )

        ser = AttendanceCheckSerializer(data=request.data, context={"request": request})
        if not ser.is_valid():
            # صياغة رسالة مفصلة بدل "تحقق من الحقول"
            err_text = []
            nice_hint = None
            for field, msgs in ser.errors.items():
                final_msgs = []
                for msg in (msgs if isinstance(msgs, (list, tuple)) else [msgs]):
                    msg_text = str(msg)
                    final_msgs.append(msg_text)
                    final_lower = msg_text.casefold()
                    if "valid uuid" in final_lower or "uuid" in final_lower:
                        nice_hint = (
                            "تعذر تحديد موقع العمل. يرجى التأكد من اختيار الموقع الصحيح"
                            " أو إعادة محاولة تحديد الموقع تلقائيًا ثم إعادة المحاولة."
                        )
                err_text.append(f"{field}: {', '.join(final_msgs)}")

            nice = nice_hint or ("؛ ".join(err_text) if err_text else "الرجاء التحقق من الحقول المدخلة.")
            return Response({
                "ok": False, "performed": False,
                "action": request.data.get("action"),
                "detail": f"تعذر معالجة الطلب. {nice}",
                "errors": ser.errors
            }, status=status.HTTP_200_OK)

        if not ser.validated_data.get('biometric_verified', False):
            return Response({'detail': 'التحقق البيومتري فشل، لا يمكن تسجيل الحضور.'}, status=status.HTTP_403_FORBIDDEN)

        # استخراج القيم
        action   = ser.validated_data.get("action")
        employee = ser.validated_data.get("employee")
        location = ser.validated_data.get("location_obj")
        lat       = ser.validated_data.get("lat")
        lng       = ser.validated_data.get("lng")
        acc       = ser.validated_data.get("accuracy")
        raw_dist  = ser.validated_data.get("distance_m")
        dist      = float(raw_dist) if raw_dist is not None else 0.0
        radius    = ser.validated_data.get("location_radius_m")
        center_lat = ser.validated_data.get("location_center_lat")
        center_lng = ser.validated_data.get("location_center_lng")
        (monitoring_payload,
         monitoring_active,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         monitoring_rule,
         monitoring_config) = _monitoring_details(location)
        violation_flag = bool(ser.validated_data.get("violation", False))
        violation_reason = ser.validated_data.get("violation_reason")
        violation_codes = list(ser.validated_data.get("violation_codes") or [])

        now       = dj_timezone.now()
        now_local = dj_timezone.localtime(now)

        start_dt  = ser.validated_data.get("shift_window_start")
        end_dt    = ser.validated_data.get("shift_window_end")
        blocked   = ser.validated_data.get("blocked")
        reason    = ser.validated_data.get("blocked_reason")

        if blocked:
            return self._deny(
                action=action,
                detail=reason or "⚠️ لا يمكن تنفيذ العملية في الوقت الحالي.",
                reason_code="business_rule_violation",
                start=start_dt, end=end_dt, now=now_local,
                monitoring=monitoring_payload,
                extra={"should_monitor_location": monitoring_active},
            )

        # ===== تنفيذ الإجراءات =====
        violation_escalated = False
        if action == "check_in":
            # منع تسجيل حضور جديد إن وُجد سجل مفتوح
            open_rec = (AttendanceRecord.objects
                        .filter(employee=employee, check_out_time__isnull=True)
                        .order_by("-check_in_time").first())
            if open_rec:
                return self._deny(
                    action=action,
                    detail="⚠️ تم تسجيل حضور مسبقًا، لا يمكن تسجيل حضور آخر قبل الانصراف.",
                    reason_code="already_checked_in",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_active},
                )

            # منع تعدد الحضور في نفس اليوم
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
                    reason_code="already_checked_in_today",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_active},
                )

            # إنشاء السجل
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
                record_geofence_violation(
                    employee=employee,
                    location=location,
                    reason=violation_reason,
                    distance=dist,
                    radius=radius,
                    codes=violation_codes,
                    outside_minutes=None,
                    attendance_record=rec,
                    warning_minutes=monitoring_grace_minutes,
                    violation_rule=monitoring_rule,
                )
                violation_escalated = True
            return Response({
                "ok": True,
                "performed": True,
                "action": action,
                "detail": "✅ تم تسجيل حضورك بنجاح.",
                "note": ("الوردية غير مقيّدة زمنيًا."
                         if start_dt is None and end_dt is None
                         else (f"الفترة المسموحة للحضور: {start_dt.strftime('%H:%M')} → {end_dt.strftime('%H:%M')}"
                               if start_dt and end_dt else "")),
                "record_id": str(rec.id),
                "employee": getattr(employee, "full_name", str(employee.pk)),
                "location_id": str(location.id) if getattr(location, "id", None) else None,
                "location_name": getattr(location, "name", None),
                "distance_m": round(dist, 2) if raw_dist is not None else None,
                "location_center": {
                    "lat": center_lat,
                    "lng": center_lng,
                    "radius_m": radius,
                },
                "violation": violation_flag,
                "violation_reason": violation_reason,
                "violation_codes": violation_codes,
                "violation_warning_minutes": monitoring_grace_minutes,
                "violation_outside_minutes": None,
                "violation_escalated": violation_escalated,
                "monitoring": monitoring_payload,
                "should_monitor_location": monitoring_active,
            }, status=status.HTTP_201_CREATED)

        elif action == "check_out":
            # منع الانصراف العادي إذا كان هناك انصراف مبكر اليوم
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
                    reason_code="early_checkout_done",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_active},
                )

            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(
                    action=action,
                    detail="لا يوجد سجل حضور مفتوح لإقفاله.",
                    reason_code="no_open_record",
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_active},
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
                    record_geofence_violation(
                        employee=employee,
                        location=rec.location or location,
                        reason=violation_reason,
                        distance=dist,
                        radius=radius,
                        codes=violation_codes,
                        outside_minutes=violation_outside_minutes,
                        attendance_record=rec,
                        warning_minutes=monitoring_grace_minutes,
                        violation_rule=monitoring_rule,
                    )
                    violation_escalated = True

            _purge_location_pings_for_employee(employee)

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
                "distance_m": round(dist, 2) if raw_dist is not None else None,
                "location_center": {
                    "lat": center_lat,
                    "lng": center_lng,
                    "radius_m": radius,
                },
                "violation": violation_flag,
                "violation_reason": violation_reason,
                "violation_codes": violation_codes,
                "violation_warning_minutes": monitoring_grace_minutes,
                "violation_outside_minutes": violation_outside_minutes,
                "violation_escalated": violation_escalated,
                "monitoring": monitoring_payload,
                "should_monitor_location": monitoring_active,
            }, status=status.HTTP_200_OK)

        elif action == "early_check_out":
            # يجب وجود سجل حضور مفتوح
            rec = (AttendanceRecord.objects
                   .filter(employee=employee, check_out_time__isnull=True)
                   .order_by("-check_in_time").first())
            if not rec:
                return self._deny(
                    action=action,
                    detail="لا يوجد سجل حضور مفتوح لإقفاله.",
                    reason_code="no_open_record",
                    monitoring=monitoring_payload,
                )

            # مرّة واحدة يوميًا
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
                    reason_code="early_checkout_once_per_day",
                    start=start_dt, end=end_dt, now=now_local,
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_active},
                )

            reason_txt = (request.data.get("early_reason") or "").strip()
            file_obj   = request.FILES.get("early_attachment")
            if not reason_txt:
                return self._deny(
                    action=action,
                    detail="يجب كتابة سبب الانصراف المبكر.",
                    reason_code="early_checkout_reason_required",
                    monitoring=monitoring_payload,
                    extra={"should_monitor_location": monitoring_active},
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
                    record_geofence_violation(
                        employee=employee,
                        location=rec.location or location,
                        reason=violation_reason,
                        distance=dist,
                        radius=radius,
                        codes=violation_codes,
                        outside_minutes=violation_outside_minutes,
                        attendance_record=rec,
                        warning_minutes=monitoring_grace_minutes,
                        violation_rule=monitoring_rule,
                    )
                    violation_escalated = True

            _purge_location_pings_for_employee(employee)

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
                "location_center": {
                    "lat": center_lat,
                    "lng": center_lng,
                    "radius_m": radius,
                },
                "violation": violation_flag,
                "violation_reason": violation_reason,
                "violation_codes": violation_codes,
                "violation_warning_minutes": monitoring_grace_minutes,
                "violation_outside_minutes": violation_outside_minutes,
                "violation_escalated": violation_escalated,
                "monitoring": monitoring_payload,
                "should_monitor_location": monitoring_active,
            }, status=status.HTTP_200_OK)

        return self._deny(
            action=action,
            detail="إجراء غير مدعوم.",
            reason_code="unsupported_action",
            monitoring=monitoring_payload,
            extra={"should_monitor_location": monitoring_active},
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
         monitoring_config) = _monitoring_details(loc)
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
            "should_monitor_location": monitoring_active,
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
         monitoring_active,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         monitoring_rule,
         monitoring_config) = _monitoring_details(loc)

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
        if not within_radius:
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

            if outside_minutes >= monitoring_grace_minutes:
                existing_violation = LocationPing.objects.filter(
                    employee=employee,
                    violation_triggered=True,
                    recorded_at__gte=outside_start,
                ).exists()
                if not existing_violation:
                    record_geofence_violation(
                        employee=employee,
                        location=loc,
                        reason=violation_reason,
                        distance=dist,
                        radius=radius,
                        codes=violation_codes,
                        outside_minutes=outside_minutes,
                        attendance_record=None,
                        warning_minutes=monitoring_grace_minutes,
                        violation_rule=monitoring_rule,
                    )
                    ping.violation_triggered = True
                    ping.save(update_fields=["violation_triggered"])
                    violation_triggered = True

        next_ping_seconds = None
        if monitoring_active:
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
            "violation": not within_radius,
            "violation_reason": violation_reason,
            "violation_codes": violation_codes,
            "violation_triggered": violation_triggered,
            "outside_minutes": outside_minutes,
            "recorded_at": _local_iso(recorded_at),
            "violation_warning_minutes": monitoring_grace_minutes,
            "monitoring": monitoring_payload,
            "should_monitor_location": monitoring_active,
            "next_ping_seconds": next_ping_seconds,
        }
        return Response(data, status=status.HTTP_200_OK)


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


class GuardReportListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReportSerializer

    def get_queryset(self):
        employee = _require_guard_employee(self.request.user)
        return (
            Report.objects
            .filter(employee=employee)
            .select_related("location")
            .prefetch_related("attachments")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        employee = _require_guard_employee(self.request.user)
        with transaction.atomic():
            serializer.save(employee=employee)


class GuardRequestListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = RequestSerializer

    def get_queryset(self):
        employee = _require_guard_employee(self.request.user)
        return (
            Request.objects
            .filter(employee=employee)
            .select_related("approver")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        employee = _require_guard_employee(self.request.user)
        serializer.save(employee=employee)


class GuardAdvanceListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AdvanceSerializer

    def get_queryset(self):
        employee = _require_guard_employee(self.request.user)
        return (
            Advance.objects
            .filter(employee=employee)
            .order_by("-requested_at")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        try:
            context["employee"] = _require_guard_employee(self.request.user)
        except Exception:
            pass
        return context

    def perform_create(self, serializer):
        employee = self.get_serializer_context().get("employee") or _require_guard_employee(self.request.user)
        serializer.save(employee=employee)


class GuardTaskListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TaskMiniSerializer

    def get_queryset(self):
        employee = _require_guard_employee(self.request.user)
        qs = Task.objects.filter(assigned_to=employee).select_related('location').order_by('-due_date', '-created_at')
        status_filter = (self.request.query_params.get('status') or '').strip().lower()
        if status_filter:
            if status_filter == 'active':
                qs = qs.exclude(status='completed')
            elif status_filter in {choice[0] for choice in Task.STATUS_CHOICES}:
                qs = qs.filter(status=status_filter)
        return qs


class GuardTaskUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
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


class GuardUniformItemListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
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



class AttendanceLastForMeView(APIView):
    """
    GET /api/v1/attendance/last/
    يعيد آخر سجل حضور/انصراف للموظف الحالي (حسب التوكن).
    200 مع البيانات | 204 إذا لا يوجد أي سجل
    """
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _determine_action(record: AttendanceRecord) -> str:
        """
        يحاول تحديد آخر إجراء اعتمادًا على الحقول المتاحة لضمان توافق البيانات مع الواجهة.
        """
        if record.check_type:
            return record.check_type
        if record.early_checkout:
            return "early_check_out"
        if record.check_out_time:
            return "check_out"
        return "check_in"

    @staticmethod
    def _shift_window(record: AttendanceRecord) -> tuple[Optional[dt.datetime], Optional[dt.datetime]]:
        """
        يحسب نافذة الوردية (إن وُجدت) باستخدام تاريخ وقت الحضور لضمان تمثيل صحيح بالتوقيت المحلي.
        """
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
        """
        يحدد أفضل طابع زمني محلي لآخر إجراء مرتبط بالسجل.
        """
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
        """
        يثري بيانات السجل الأخير لتتضمن مفاتيح مفهومة لتطبيق الهاتف.
        """
        base = AttendanceMiniSerializer(record).data
        location_obj = getattr(record, "location", None)
        employee_obj = getattr(record, "employee", None)

        (monitoring_payload,
         monitoring_active,
         monitoring_grace_minutes,
         monitoring_ping_seconds,
         monitoring_outside_seconds,
         monitoring_rule,
         monitoring_config) = _monitoring_details(location_obj)

        action = self._determine_action(record)
        recorded_at = (
            record.timestamp
            or record.updated_at
            or record.check_out_time
            or record.check_in_time
        )

        shift_start, shift_end = self._shift_window(record)
        shift_start_local = _local_dt(shift_start) if shift_start else None
        shift_end_local = _local_dt(shift_end) if shift_end else None

        action_labels = {
            "check_in": "الحضور",
            "check_out": "الانصراف",
            "early_check_out": "الانصراف المبكر",
        }
        action_label = action_labels.get(action, action)
        detail_msg = f"آخر تسجيل: {action_label}."

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
        elif shift_start_local or shift_end_local:
            within_shift = True  # تم تحديد أحد حدود الوردية فقط، نعتبره ضمن الوردية
        else:
            within_shift = True  # وردية غير مقيّدة
        should_monitor = (
            monitoring_active
            and is_today
            and within_shift
            and action == "check_in"
            and getattr(record, "check_out_time", None) is None
        )
        next_ping_seconds = None
        if monitoring_active:
            base_next = monitoring_ping_seconds
            outside_next = monitoring_outside_seconds or monitoring_ping_seconds
            candidate = base_next if within_shift else outside_next
            if candidate and candidate > 0:
                next_ping_seconds = candidate

        payload: dict[str, object] = {
            "ok": True,
            "detail": detail_msg,
            "message": detail_msg,
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

        # معلومات إضافية عن الموظف والموقع إن توفرت
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

    def get(self, request):
        # جلب الموظف المرتبط بالمستخدم الحالي
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

        (monitoring_payload_raw,
         _monitoring_active_raw,
         monitoring_grace_minutes_raw,
         monitoring_ping_seconds_raw,
         monitoring_outside_seconds_raw,
         _monitoring_rule_raw,
         _monitoring_config_raw) = _monitoring_details(getattr(rec, "location", None))

        effective_local = self._effective_local_datetime(rec)
        now_local = _local_dt(dj_timezone.now())
        if not effective_local or (now_local and effective_local.date() != now_local.date()):
            return Response(
                {
                    "ok": False,
                    "detail": "لا يوجد سجل حضور لهذا اليوم.",
                    "message": "لا يوجد سجل حضور لهذا اليوم.",
                    "latest_record_id": str(rec.id),
                    "latest_record_action": self._determine_action(rec),
                    "latest_recorded_at": effective_local.isoformat() if effective_local else _local_iso(rec.timestamp),
                    "monitoring": monitoring_payload_raw,
                    "violation_warning_minutes": monitoring_grace_minutes_raw,
                    "next_ping_seconds": monitoring_ping_seconds_raw,
                },
                status=status.HTTP_200_OK,
            )

        data = self._serialize_record(rec, effective_local=effective_local, now_local=now_local)
        return Response(data, status=status.HTTP_200_OK)


class AttendanceExistsView(APIView):
    """
    GET /api/v1/attendance/exists/<uuid:pk>/
    204: موجود
    404: غير موجود (محذوف/غير صحيح)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        exists = AttendanceRecord.objects.filter(id=pk).exists()
        return Response(status=status.HTTP_204_NO_CONTENT if exists else status.HTTP_404_NOT_FOUND)
