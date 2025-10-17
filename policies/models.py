from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class PolicyBundle(BaseModel):
    """
    حزمة سياسة عامة قابلة لإعادة الاستخدام مع تكوين مرن عبر JSON.

    - policy_type: نوع السياسة (holiday, leave, payroll, overtime_rewards, deduction)
    - priority: رقم أولوية (أصغر = أقوى) للفصل عند التعارض داخل نفس النطاق
    - start_date/end_date: فترة سريان السياسة
    - is_active: تمكين/تعطيل سريع للحزمة
    - config: تفاصيل السياسة (JSON) — يحدد شكل الحقل كل سياسة حسب الحاجة
    """

    class PolicyType(models.TextChoices):
        HOLIDAY = "holiday", _("إجازات رسمية")
        LEAVE = "leave", _("إجازات")
        PAYROLL = "payroll", _("الرواتب")
        OVERTIME_REWARDS = "overtime_rewards", _("مكافآت إضافية")
        DEDUCTION = "deduction", _("خصومات")

    policy_type = models.CharField(max_length=50, choices=PolicyType.choices, db_index=True, verbose_name="نوع السياسة")
    name = models.CharField(max_length=200, blank=True, null=True, verbose_name="اسم وصفي")
    description = models.TextField(blank=True, null=True, verbose_name="وصف")

    priority = models.PositiveIntegerField(default=100, help_text="الأصغر أقوى", verbose_name="الأولوية")

    start_date = models.DateField(default=timezone.now, verbose_name="تاريخ البدء")
    end_date = models.DateField(blank=True, null=True, verbose_name="تاريخ الانتهاء")
    is_active = models.BooleanField(default=True, verbose_name="مفعلة؟")

    config = models.JSONField(default=dict, blank=True, verbose_name="تهيئة (JSON)")

    class Meta:
        verbose_name = "حزمة سياسة"
        verbose_name_plural = "حزم السياسات"
        ordering = ["policy_type", "priority", "-start_date"]
        indexes = [
            models.Index(fields=["policy_type", "priority", "start_date", "is_active"]),
        ]

    def __str__(self) -> str:
        label = self.name or dict(self.PolicyType.choices).get(self.policy_type, self.policy_type)
        return f"{label} [prio={self.priority}] ({self.start_date}->{self.end_date or '∞'})"


class PolicyTarget(BaseModel):
    """
    يحدد نطاق تطبيق الحزمة:
    - GLOBAL: عام لكل النظام (لا مراجع)
    - ROLE: مرتبط بدور معين
    - LOCATION: مرتبط بموقع معين
    - SHIFT: مرتبط بورديّة معينة

    ملاحظات:
    - يجب أن يتوافق الحقل scope مع المرجع المعبأ فقط (تحقق بقيود)
    - يمكن ربط عدة أهداف بنفس الحزمة لأنواع مختلفة من النطاقات
    """

    class Scope(models.TextChoices):
        GLOBAL = "global", _("عام")
        ROLE = "role", _("دور")
        LOCATION = "location", _("موقع")
        SHIFT = "shift", _("وردية")

    bundle = models.ForeignKey(PolicyBundle, on_delete=models.CASCADE, related_name="targets", verbose_name="الحزمة")
    scope = models.CharField(max_length=20, choices=Scope.choices, db_index=True, verbose_name="النطاق")

    # مراجع بحسب النطاق
    role = models.ForeignKey("api_guard.Role", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الدور")
    location = models.ForeignKey("api_guard.Location", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموقع")
    shift = models.ForeignKey("api_guard.Shift", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الوردية")

    class Meta:
        verbose_name = "هدف سياسة"
        verbose_name_plural = "أهداف السياسات"
        indexes = [
            models.Index(fields=["scope", "role"]),
            models.Index(fields=["scope", "location"]),
            models.Index(fields=["scope", "shift"]),
        ]
        constraints = [
            # GLOBAL: جميع المراجع يجب أن تكون NULL
            models.CheckConstraint(
                name="pol_target_global_null_refs",
                check=(
                    models.Q(scope="global", role__isnull=True, location__isnull=True, shift__isnull=True)
                    | ~models.Q(scope="global")
                ),
            ),
            # ROLE: role موجود والباقي NULL
            models.CheckConstraint(
                name="pol_target_role_only",
                check=(
                    models.Q(scope="role", role__isnull=False, location__isnull=True, shift__isnull=True)
                    | ~models.Q(scope="role")
                ),
            ),
            # LOCATION: location موجود والباقي NULL
            models.CheckConstraint(
                name="pol_target_location_only",
                check=(
                    models.Q(scope="location", role__isnull=True, location__isnull=False, shift__isnull=True)
                    | ~models.Q(scope="location")
                ),
            ),
            # SHIFT: shift موجود والباقي NULL
            models.CheckConstraint(
                name="pol_target_shift_only",
                check=(
                    models.Q(scope="shift", role__isnull=True, location__isnull=True, shift__isnull=False)
                    | ~models.Q(scope="shift")
                ),
            ),
        ]

    def __str__(self) -> str:
        if self.scope == self.Scope.GLOBAL:
            return f"{self.bundle} @ GLOBAL"
        if self.scope == self.Scope.ROLE and self.role:
            return f"{self.bundle} @ ROLE:{self.role}"
        if self.scope == self.Scope.LOCATION and self.location:
            return f"{self.bundle} @ LOCATION:{self.location}"
        if self.scope == self.Scope.SHIFT and self.shift:
            return f"{self.bundle} @ SHIFT:{self.shift}"
        return f"{self.bundle} @ {self.scope}"

    def clean(self):
        """
        تطبيع/التحقق قبل الحفظ لتفادي خرق القيود:
        - GLOBAL: جميع المراجع يجب أن تكون NULL.
        - ROLE: يجب تحديد role فقط، وغير ذلك NULL.
        - LOCATION: يجب تحديد location فقط.
        - SHIFT: يجب تحديد shift فقط.
        """
        # طبيع الحقول حسب النطاق
        scope = (self.scope or '').strip()
        if scope == self.Scope.GLOBAL:
            self.role = None
            self.location = None
            self.shift = None
        elif scope == self.Scope.ROLE:
            if not self.role_id:
                raise ValidationError({"role": "يجب اختيار دور عند نطاق الدور."})
            self.location = None
            self.shift = None
        elif scope == self.Scope.LOCATION:
            if not self.location_id:
                raise ValidationError({"location": "يجب اختيار موقع عند نطاق الموقع."})
            self.role = None
            self.shift = None
        elif scope == self.Scope.SHIFT:
            if not self.shift_id:
                raise ValidationError({"shift": "يجب اختيار وردية عند نطاق الورديّة."})
            self.role = None
            self.location = None

    def save(self, *args, **kwargs):
        # ضمنيًا يشغّل clean() ويوقف الحفظ لو وُجدت أخطاء
        self.full_clean()
        return super().save(*args, **kwargs)


class WeeklyOff(BaseModel):
    """
    تعريف أيام الراحة الأسبوعية حسب النطاق.

    - day_of_week: 0=Mon .. 6=Sun
    - scope: GLOBAL/ROLE/LOCATION/SHIFT
    - priority: الأصغر أقوى عند التعارض داخل نفس النطاق
    - start_date/end_date + is_active للتحكم الزمني
    """

    class Scope(models.TextChoices):
        GLOBAL = "global", _("عام")
        ROLE = "role", _("دور")
        LOCATION = "location", _("موقع")
        SHIFT = "shift", _("وردية")

    DOW_CHOICES = (
        (0, _("الاثنين")),
        (1, _("الثلاثاء")),
        (2, _("الأربعاء")),
        (3, _("الخميس")),
        (4, _("الجمعة")),
        (5, _("السبت")),
        (6, _("الأحد")),
    )

    scope = models.CharField(max_length=20, choices=Scope.choices, db_index=True, verbose_name="النطاق")
    role = models.ForeignKey("api_guard.Role", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الدور")
    location = models.ForeignKey("api_guard.Location", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموقع")
    shift = models.ForeignKey("api_guard.Shift", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الوردية")

    day_of_week = models.IntegerField(choices=DOW_CHOICES, db_index=True, verbose_name="اليوم الأسبوعي")
    priority = models.PositiveIntegerField(default=100, help_text="الأصغر أقوى", verbose_name="الأولوية")
    start_date = models.DateField(default=timezone.now, verbose_name="تاريخ البدء")
    end_date = models.DateField(blank=True, null=True, verbose_name="تاريخ الانتهاء")
    is_active = models.BooleanField(default=True, verbose_name="مفعلة؟")

    class Meta:
        verbose_name = "راحة أسبوعية"
        verbose_name_plural = "أيام الراحة الأسبوعية"
        indexes = [
            models.Index(fields=["scope", "day_of_week", "priority", "start_date", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="weeklyoff_global_only",
                check=(models.Q(scope="global", role__isnull=True, location__isnull=True, shift__isnull=True) | ~models.Q(scope="global")),
            ),
            models.CheckConstraint(
                name="weeklyoff_role_only",
                check=(models.Q(scope="role", role__isnull=False, location__isnull=True, shift__isnull=True) | ~models.Q(scope="role")),
            ),
            models.CheckConstraint(
                name="weeklyoff_location_only",
                check=(models.Q(scope="location", role__isnull=True, location__isnull=False, shift__isnull=True) | ~models.Q(scope="location")),
            ),
            models.CheckConstraint(
                name="weeklyoff_shift_only",
                check=(models.Q(scope="shift", role__isnull=True, location__isnull=True, shift__isnull=False) | ~models.Q(scope="shift")),
            ),
        ]

    def __str__(self) -> str:
        return f"WeeklyOff({self.get_day_of_week_display()} @ {self.scope})"


class PublicHoliday(BaseModel):
    """
    العطل الرسمية. يمكن تقييدها بنطاق اختياريًا.
    - إذا كان repeats_annually=True يتم المطابقة حسب (شهر/يوم) فقط.
    - يمكن تفعيل/تعطيل وإعطاء فترة صلاحية.
    """

    class Scope(models.TextChoices):
        GLOBAL = "global", _("عام")
        ROLE = "role", _("دور")
        LOCATION = "location", _("موقع")
        SHIFT = "shift", _("وردية")

    name = models.CharField(max_length=200, verbose_name="اسم العطلة")
    date = models.DateField(verbose_name="التاريخ")
    repeats_annually = models.BooleanField(default=True, verbose_name="تكرار سنوي؟")
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.GLOBAL, db_index=True, verbose_name="النطاق")
    role = models.ForeignKey("api_guard.Role", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الدور")
    location = models.ForeignKey("api_guard.Location", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموقع")
    shift = models.ForeignKey("api_guard.Shift", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الوردية")
    is_active = models.BooleanField(default=True, verbose_name="مفعلة؟")

    class Meta:
        verbose_name = "عطلة رسمية"
        verbose_name_plural = "عطل رسمية"
        indexes = [
            models.Index(fields=["scope", "date", "repeats_annually", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="holiday_scope_global_only",
                check=(models.Q(scope="global", role__isnull=True, location__isnull=True, shift__isnull=True) | ~models.Q(scope="global")),
            ),
            models.CheckConstraint(
                name="holiday_scope_role_only",
                check=(models.Q(scope="role", role__isnull=False, location__isnull=True, shift__isnull=True) | ~models.Q(scope="role")),
            ),
            models.CheckConstraint(
                name="holiday_scope_location_only",
                check=(models.Q(scope="location", role__isnull=True, location__isnull=False, shift__isnull=True) | ~models.Q(scope="location")),
            ),
            models.CheckConstraint(
                name="holiday_scope_shift_only",
                check=(models.Q(scope="shift", role__isnull=True, location__isnull=True, shift__isnull=False) | ~models.Q(scope="shift")),
            ),
        ]

    def __str__(self) -> str:
        return f"PublicHoliday({self.name} on {self.date})"


class LocalException(BaseModel):
    """
    استثناءات محلية تجعل اليوم عملًا أو عطلة لموظف أو موقع.

    - effect: make_off → اجعل اليوم عطلة | make_working → اجعل اليوم عمل
    - applies to: employee OR location (واحد فقط)
    - notes: وصف اختياري
    """

    class Effect(models.TextChoices):
        MAKE_OFF = "make_off", _("اجعل عطلة")
        MAKE_WORKING = "make_working", _("اجعل عمل")

    date = models.DateField(verbose_name="التاريخ")
    effect = models.CharField(max_length=20, choices=Effect.choices, verbose_name="التأثير")
    employee = models.ForeignKey("api_guard.Employee", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموظف")
    location = models.ForeignKey("api_guard.Location", on_delete=models.CASCADE, null=True, blank=True, verbose_name="الموقع")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظة")

    class Meta:
        verbose_name = "استثناء محلي"
        verbose_name_plural = "استثناءات محلية"
        indexes = [
            models.Index(fields=["date", "employee", "location"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="local_exception_one_target",
                check=(
                    (models.Q(employee__isnull=False, location__isnull=True) |
                     models.Q(employee__isnull=True, location__isnull=False))
                ),
            ),
        ]

    def __str__(self) -> str:
        target = self.employee or self.location or "global"
        return f"LocalException({self.effect} on {self.date} for {target})"


class LeavePolicy(BaseModel):
    """
    سياسة الإجازات (بالأيام) مع ربط اختياري بحزمة سياسة (PolicyBundle) من النوع "leave".

    الحقول:
    - monthly_accrual_days: الأيام المكتسبة شهريًا (قد تكون عشرية).
    - yearly_cap_days: الحد الأقصى السنوي للأيام المكتسبة.
    - carry_over_max: الحد الأعلى للترحيل إلى السنة التالية.

    ملاحظة:
    - يمكن ربط عدة أهداف عبر PolicyTarget على مستوى الحزمة لتطبيق أولوية النطاق: SHIFT → LOCATION → ROLE → GLOBAL.
    - يوصى بإنشاء PolicyBundle(policy_type='leave') وربطه عبر هذا الحقل.
    """

    bundle = models.ForeignKey(
        PolicyBundle,
        on_delete=models.CASCADE,
        related_name="leave_policies",
        verbose_name="حزمة السياسة (leave)",
        null=True,
        blank=True,
    )
    monthly_accrual_days = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="الاستحقاق الشهري (أيام)")
    yearly_cap_days = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="الحد السنوي (أيام)")
    carry_over_max = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="حد الترحيل السنوي (أيام)")

    class Meta:
        verbose_name = "سياسة إجازات (أيام)"
        verbose_name_plural = "سياسات إجازات (أيام)"
        indexes = [
            models.Index(fields=["bundle"]),
        ]

    def __str__(self) -> str:
        return f"LeavePolicy(monthly={self.monthly_accrual_days}, cap={self.yearly_cap_days}, carry={self.carry_over_max})"


class OvertimeRewardsPolicy(BaseModel):
    """
    سياسة العمل الإضافي والمكافآت بالنِسَب.

    - normal_rate: معامل الإضافي للحالات العادية (مثل 1.5)
    - night_rate: معامل الإضافي لفترة الليل (مثل 1.75)
    - offday_rate: معامل الإضافي في يوم الراحة الأسبوعية (مثل 2.0)
    - public_holiday_rate: معامل الإضافي في العطل الرسمية (مثل 2.5)
    - night_window_start/end: نافذة الليل (افتراضي 22:00 → 06:00)
    - monthly_hours_cap: سقف ساعات الإضافي القابلة للدفع شهريًا (اختياري)
    - bundle: ربط اختياري بـ PolicyBundle(policy_type='overtime_rewards') لتطبيق حسب النطاق.
    """

    bundle = models.ForeignKey(
        PolicyBundle,
        on_delete=models.CASCADE,
        related_name="overtime_policies",
        verbose_name="حزمة السياسة (overtime_rewards)",
        null=True,
        blank=True,
    )
    normal_rate = models.DecimalField(max_digits=5, decimal_places=2, default=1.50, verbose_name="معامل العادي")
    night_rate = models.DecimalField(max_digits=5, decimal_places=2, default=1.75, verbose_name="معامل الليلي")
    offday_rate = models.DecimalField(max_digits=5, decimal_places=2, default=2.00, verbose_name="معامل يوم الراحة")
    public_holiday_rate = models.DecimalField(max_digits=5, decimal_places=2, default=2.50, verbose_name="معامل العطلة الرسمية")

    night_window_start = models.TimeField(default=timezone.datetime(2000,1,1,22,0).time(), verbose_name="بداية الليلي")
    night_window_end = models.TimeField(default=timezone.datetime(2000,1,1,6,0).time(), verbose_name="نهاية الليلي")
    monthly_hours_cap = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, verbose_name="سقف ساعات شهري")

    class Meta:
        verbose_name = "سياسة إضافي ومكافآت"
        verbose_name_plural = "سياسات إضافي ومكافآت"
        indexes = [
            models.Index(fields=["bundle"]),
        ]

    def __str__(self) -> str:
        return f"OTPolicy(norm={self.normal_rate}, night={self.night_rate}, off={self.offday_rate}, hol={self.public_holiday_rate})"
