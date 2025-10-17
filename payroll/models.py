from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from typing import Optional

from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import BaseModel


class PayrollConfig(BaseModel):
    """
    الضبط العام للرواتب اليومية.

    - daily_rate_policy: 'fixed'‎ = قيمة ثابتة، 'from_base'‎ = مشتقة من الراتب الأساسي ÷ عدد الأيام القياسية.
    - fixed_daily_rate: قيمة اليومية عند سياسة 'fixed'.
    - default_working_days: عدد الأيام القياسية في الشهر (يُستخدم لحساب payable_days والد اليومية عند from_base).
    - hours_per_day: عدد الساعات المعيارية لليوم (للرجوع إليها لاحقًا في الوقت الإضافي).
    - max_deduction_rate: نسبة أقصى خصم من الراتب الأساسي في الشهر (٪).

    ملاحظة: أبقيناها ضبطًا عامًا واحدًا مبسطًا. يمكن توسيعها لاحقًا بالربط مع PolicyBundle إن لزم.
    """

    class DailyRatePolicy(models.TextChoices):
        FIXED = "fixed", _("ثابت")
        FROM_BASE = "from_base", _("من الراتب الأساسي")

    daily_rate_policy = models.CharField(max_length=20, choices=DailyRatePolicy.choices, default=DailyRatePolicy.FROM_BASE, verbose_name="سياسة اليومية")
    fixed_daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="اليومية الثابتة")
    default_working_days = models.DecimalField(max_digits=6, decimal_places=2, default=30, verbose_name="الأيام القياسية")
    hours_per_day = models.DecimalField(max_digits=5, decimal_places=2, default=8, verbose_name="ساعات العمل في اليوم")
    max_deduction_rate = models.DecimalField(max_digits=5, decimal_places=2, default=30, verbose_name="الحد الأقصى للخصم (%)")

    is_active = models.BooleanField(default=True, verbose_name="مفعّل؟")

    class Meta:
        verbose_name = "إعداد الرواتب"
        verbose_name_plural = "إعدادات الرواتب"

    def __str__(self):
        return f"PayrollConfig(policy={self.daily_rate_policy})"


class PayrollCycle(BaseModel):
    """دورة راتب شهرية (سنة/شهر)."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("مسودّة")
        CLOSED = "closed", _("مقفلة")

    year = models.PositiveIntegerField(verbose_name="السنة")
    month = models.PositiveIntegerField(verbose_name="الشهر")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, verbose_name="الحالة")
    config = models.ForeignKey(PayrollConfig, on_delete=models.PROTECT, related_name="cycles", verbose_name="الإعداد المستخدم")

    class Meta:
        unique_together = ("year", "month")
        verbose_name = "دورة راتب"
        verbose_name_plural = "دورات الرواتب"
        ordering = ["-year", "-month"]

    def __str__(self):
        return f"PayrollCycle({self.year}-{self.month:02d}, {self.get_status_display()})"

    def clean(self):
        """
        تحقّق مسبق لعدم تكرار (year, month) بدلاً من سقوط بخطأ UNIQUE من قاعدة البيانات.
        يتجاهل السجل الحالي ويسمح بوجود نسخة محذوفة منطقيًا فقط.
        """
        y = getattr(self, 'year', None)
        m = getattr(self, 'month', None)
        if y and m:
            all_qs = getattr(type(self), 'all_objects', type(self).objects)
            dup = (all_qs
                   .filter(year=y, month=m)
                   .exclude(pk=self.pk)
                   .first())
            if dup and getattr(dup, 'deleted_at', None) is None:
                raise ValidationError({
                    'month': 'توجد دورة راتب لهذا الشهر بالفعل — افتحها للتعديل بدلاً من إنشاء دورة جديدة.'
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PayrollItem(BaseModel):
    """
    بند راتب لموظف واحد داخل دورة.

    - لا يُسجّل الإجازة غير المدفوعة كبند خصم؛ تؤثر فقط على payable_days.
    - خصومات الشهر تُحدّ بالسقف max_deduction_rate×base_salary، والفائض يُرحّل للشهر التالي.
    """

    cycle = models.ForeignKey(PayrollCycle, on_delete=models.CASCADE, related_name="items", verbose_name="الدورة")
    employee = models.ForeignKey("api_guard.Employee", on_delete=models.CASCADE, related_name="payroll_items", verbose_name="الموظف")

    # لقطات/قيم حسابية
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="الراتب الأساسي")
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="اليومية")
    default_working_days = models.DecimalField(max_digits=6, decimal_places=2, default=30, verbose_name="الأيام القياسية")
    unpaid_leave_days = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="أيام الإجازة غير المدفوعة")
    payable_days = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="أيام مستحقة الدفع")

    days_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="قيمة الأيام")
    allowances_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="إجمالي البدلات")
    overtime_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="إجمالي الإضافي")
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الإجمالي قبل الخصم")

    deductions_requested = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الخصومات المطلوبة")
    carry_in_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="خصومات مرحلة من الشهر السابق")
    deductions_applied = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الخصومات المطبقة")
    deductions_excess_carried = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="خصومات فائضة مرحّلة")
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="الصافي المستحق")

    detail = models.JSONField(blank=True, null=True, verbose_name="تفاصيل")

    class Meta:
        verbose_name = "بند راتب"
        verbose_name_plural = "بنود الرواتب"
        indexes = [
            models.Index(fields=["employee", "cycle"]),
        ]

    def __str__(self):
        return f"Item({self.employee_id} {self.cycle.year}-{self.cycle.month:02d})"


class Reward(BaseModel):
    """مكافأة مباشرة للموظف (مبلغ ثابت)، تخضع للموافقة وتدخل في البدلات."""
    employee = models.ForeignKey("api_guard.Employee", on_delete=models.CASCADE, related_name="rewards", verbose_name="الموظف")
    date = models.DateField(verbose_name="التاريخ")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ")
    reason = models.CharField(max_length=255, blank=True, null=True, verbose_name="السبب")
    approved = models.BooleanField(default=False, verbose_name="معتمد؟")

    class Meta:
        verbose_name = "مكافأة"
        verbose_name_plural = "مكافآت"
        indexes = [
            models.Index(fields=["employee", "date"]),
        ]

    def __str__(self):
        return f"Reward({self.employee_id} {self.date} {self.amount})"


class Overtime(BaseModel):
    """ساعات عمل إضافية مع تصنيف ونسبة من السياسة، تخضع للموافقة."""
    class Classification(models.TextChoices):
        NORMAL = "normal", _("عادي")
        NIGHT = "night", _("ليلي")
        OFFDAY = "offday", _("يوم راحة")
        PUBLIC_HOLIDAY = "public_holiday", _("عطلة رسمية")

    employee = models.ForeignKey("api_guard.Employee", on_delete=models.CASCADE, related_name="overtimes", verbose_name="الموظف")
    date = models.DateField(verbose_name="التاريخ")
    hours = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="الساعات")
    classification = models.CharField(max_length=20, choices=Classification.choices, default=Classification.NORMAL, verbose_name="التصنيف")
    approved = models.BooleanField(default=False, verbose_name="معتمد؟")
    note = models.CharField(max_length=255, blank=True, null=True, verbose_name="ملاحظة")

    class Meta:
        verbose_name = "عمل إضافي"
        verbose_name_plural = "أعمال إضافية"
        indexes = [
            models.Index(fields=["employee", "date"]),
        ]

    def __str__(self):
        return f"Overtime({self.employee_id} {self.date} {self.hours}h {self.classification})"
