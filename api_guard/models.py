# api_guard/models.py

from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.contrib.auth.models import AbstractUser
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db.models import F
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone

from core.models import BaseModel



# ===================================================================
# ثوابت
# ===================================================================

# أسماء الأدوار كتعداد ثابت داخل جدول Role
ROLE_NAME_CHOICES = [
    ('guard', 'حارس أمن'),
    ('supervisor', 'مشرف'),
    ('ops_manager', 'مدير العمليات'),
    ('hr', 'الموارد البشرية'),
]

# أشهر بنوك السعودية
SAUDI_BANK_CHOICES = [
    ('alrajhi', 'مصرف الراجحي'),
    ('snb', 'الأهلي السعودي (SNB)'),
    ('riyad', 'بنك الرياض'),
    ('sabb', 'ساب'),
    ('bsf', 'البنك السعودي الفرنسي'),
    ('alinma', 'مصرف الإنماء'),
    ('anb', 'البنك العربي الوطني'),
    ('jazira', 'بنك الجزيرة'),
    ('saib', 'البنك السعودي للاستثمار'),
    ('gib', 'بنك الخليج الدولي'),
]

# ===================================================================
# 1) الأدوار والمستخدمون والموظفون
# ===================================================================

class Role(BaseModel):
    # الاسم الآن choices من ROLE_NAME_CHOICES
    name = models.CharField(
        max_length=100,
        unique=True,
        choices=ROLE_NAME_CHOICES,
        verbose_name="اسم الدور",
    )
    description = models.TextField(blank=True, null=True, verbose_name="وصف الدور")

    def __str__(self):
        # أعرض التسمية العربية إن وُجدت
        return dict(ROLE_NAME_CHOICES).get(self.name, self.name)

    class Meta:
        verbose_name = "1. دور"
        verbose_name_plural = "1. الأدوار"


class User(AbstractUser):
    role = models.ForeignKey(
        Role,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='jobs',
        verbose_name="الدور",
    )

    def __str__(self): return self.username

    class Meta:
        verbose_name = "2. مستخدم"
        verbose_name_plural = "2. المستخدمون"


class Employee(BaseModel):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, verbose_name="حساب المستخدم"
    )

    # بيانات عامة
    full_name = models.CharField(max_length=255, verbose_name="الاسم الرباعي")

    # الهوية والاتصال
    national_id = models.CharField(max_length=20, unique=True, verbose_name="رقم الهوية")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الجوال")
    date_of_birth_gregorian = models.DateField(null=True, blank=True, verbose_name="تاريخ الميلاد (ميلادي)")
    id_expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ انتهاء الهوية")
    id_image = models.ImageField(upload_to='id_cards/', null=True, blank=True, verbose_name="صورة الهوية")

    # العمل
    hire_date = models.DateField(null=True, blank=True, verbose_name="تاريخ التعيين")
    supervisor = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='subordinates', verbose_name="المشرف المباشر"
    )

    # البنك والراتب
    bank_name = models.CharField(
        max_length=20, choices=SAUDI_BANK_CHOICES, null=True, blank=True, verbose_name="اسم البنك"
    )
    bank_account = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم الحساب / الآيبان")

    monthly_leave_quota_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        verbose_name="ساعات الإجازة المسموح بها شهرياً",
        help_text="عدد الساعات المتاحة للإجازات في كل شهر"
    )

    # تعليمات
    instructions = models.TextField(blank=True, null=True, verbose_name="تعليمات خاصة بالموظف")

    def __str__(self):  # إصلاح الخطأ السابق
        return self.full_name

    class Meta:
        verbose_name = "3. موظف"
        verbose_name_plural = "3. الموظفون"

# ===================================================================
# 2) المواقع والمهام والورديات
# ===================================================================

class Location(BaseModel):
    name = models.CharField(max_length=200, verbose_name="اسم الموقع")
    client_name = models.CharField(max_length=200, verbose_name="اسم العميل")
    gps_coordinates = models.CharField(max_length=100, blank=True, null=True, verbose_name="إحداثيات الموقع")
    gps_radius = models.PositiveIntegerField(default=50, verbose_name="نطاق GPS المسموح به (متر)")


    use_polygon = models.BooleanField(default=False, verbose_name="استخدام مضلّع بدل الدائرة")
    polygon_coords = models.JSONField(
        blank=True, null=True,
        help_text="قائمة نقاط [[lat,lng],[lat,lng],...]", verbose_name="إحداثيات المضلّع"
    )
    # تعليمات الموقع
    instructions = models.TextField(blank=True, null=True, verbose_name="تعليمات الموقع")

    assigned_employees = models.ManyToManyField(
        Employee, through='EmployeeLocationAssignment', related_name='locations'
    )

    def __str__(self): return self.name

    class Meta:
        verbose_name = "4. موقع"
        verbose_name_plural = "4. المواقع"


class EmployeeLocationAssignment(BaseModel):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, verbose_name="الموظف")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, verbose_name="الموقع")
    start_date = models.DateField(null=True, blank=True)
    end_date   = models.DateField(null=True, blank=True)

    
    def __str__(self): return f"{self.employee.full_name} @ {self.location.name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "location"],
                condition=models.Q(end_date__isnull=True),   # يمنع أكثر من تعيين نشط
                name="uniq_active_employee_location",
            )
        ]
        unique_together = ('employee', 'location')
        verbose_name = "تعيين موظف لموقع"
        verbose_name_plural = "تعيينات الموظفين للمواقع"


class Task(BaseModel):
    STATUS_CHOICES = [
        ('new', 'جديدة'),
        ('accepted', 'مقبولة'),
        ('in_progress', 'قيد التنفيذ'),
        ('completed', 'مكتملة'),
    ]

    title = models.CharField(max_length=200, verbose_name="عنوان المهمة")
    description = models.TextField(verbose_name="وصف المهمة")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="الحالة")
    status_note = models.TextField(blank=True, null=True, verbose_name="ملاحظة الحالة")
    due_date = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الاستحقاق")

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='tasks', verbose_name="الموقع")
    assigned_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='created_tasks', verbose_name="أُنشئت بواسطة")
    assigned_to = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='assigned_tasks', verbose_name="مُكلف بها")

    def __str__(self): return self.title

    class Meta:
        verbose_name = "5. مهمة"
        verbose_name_plural = "5. المهام"
        ordering = ['-due_date']


class Shift(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الوردية")
    start_time = models.TimeField(verbose_name="وقت البدء")
    end_time = models.TimeField(verbose_name="وقت الانتهاء")

    def __str__(self):
        start = self.start_time.strftime('%I:%M %p'); end = self.end_time.strftime('%I:%M %p')
        return f"{self.name} ({start} - {end})"

    class Meta:
        verbose_name = "6. وردية"
        verbose_name_plural = "6. الورديات"

# models.py

class EmployeeShiftAssignment(BaseModel):
    """
    يربط موظف بوردية معينة (يمكن أن تتكرر يومياً/أسبوعياً).
    """
    employee   = models.ForeignKey(
        Employee, on_delete=models.CASCADE,
        related_name='shift_assignments', verbose_name="الموظف"
    )
    shift      = models.ForeignKey(
        Shift, on_delete=models.PROTECT,
        related_name='employee_assignments', verbose_name="الوردية"
    )
    date       = models.DateField(null=True, blank=True, verbose_name="تاريخ بداية الوردية")
    start_time = models.TimeField(null=True, blank=True, verbose_name="وقت بدء مخصص")
    end_time   = models.TimeField(null=True, blank=True, verbose_name="وقت انتهاء مخصص")
    location   = models.ForeignKey(
        Location, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='shift_assignments', verbose_name="الموقع"
    )

    # === سماحات مخصّصة (اختيارية) ===
    checkin_grace  = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="سماح الحضور (دقائق)",
        help_text="إن تُركت فارغة ⇒ لا سماح للحضور"
    )
    checkout_grace = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="سماح الانصراف (دقائق)",
        help_text="تُستخدم فقط إذا كانت ساعات الانصراف فارغة"
    )
    checkout_grace_hours = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True,
        verbose_name="سماح الانصراف (ساعات)",
        help_text="إن تم تحديدها تتقدّم على الدقائق"
    )

    active     = models.BooleanField(default=True, verbose_name="نشِطة؟")
    notes      = models.TextField(null=True, blank=True, verbose_name="ملاحظات")

    def __str__(self):
        d = self.date.isoformat() if self.date else "دائم"
        return f"{self.employee.full_name} ← {self.shift.name} ({d})"

    class Meta:
        verbose_name = "تعيين وردية لموظف"
        verbose_name_plural = "تعيينات الورديات للموظفين"
        unique_together = ('employee', 'shift', 'date', 'start_time', 'end_time')


# ===================================================================
# 3) الحضور والرواتب
# ===================================================================

class AttendanceRecord(BaseModel):
    WORK_TYPE_CHOICES = [('official', 'دوام رسمي'), ('coverage', 'تغطية'), ('overtime', 'إضافي')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records', verbose_name="الموظف")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموقع")
    check_in_time = models.DateTimeField(verbose_name="وقت الحضور")
    check_out_time = models.DateTimeField(null=True, blank=True, verbose_name="وقت الانصراف")
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الوردية")
    work_type = models.CharField(max_length=20, choices=WORK_TYPE_CHOICES, default='official', verbose_name="نوع الدوام")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    early_checkout  = models.BooleanField(default=False)
    early_reason    = models.TextField(null=True, blank=True)
    early_attachment = models.FileField(upload_to="early_checkout/", null=True, blank=True)
    biometric_verified = models.BooleanField(default=False)
    biometric_method = models.CharField(max_length=50, blank=True, null=True)
    biometric_attempts = models.IntegerField(default=0)
    check_type = models.CharField(max_length=20, choices=[
        ('check_in', 'Check In'),
        ('check_out', 'Check Out'),
        ('early_check_out', 'Early Check Out')
    ], default='check_in')
    timestamp = models.DateTimeField(auto_now_add=True)
    is_violation = models.BooleanField(default=False)
    def __str__(self): return f"{self.employee.full_name} - {self.check_in_time.strftime('%Y-%m-%d')}"

    class Meta:
        verbose_name = "7. سجل حضور"
        verbose_name_plural = "7. سجلات الحضور"
        ordering = ['-check_in_time']


class LocationPing(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="location_pings",
        verbose_name="الموظف",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="location_pings",
        verbose_name="الموقع",
    )
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy = models.FloatField(null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    within_radius = models.BooleanField(default=True)
    violation_triggered = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(default=timezone.now, verbose_name="وقت التسجيل")

    class Meta:
        verbose_name = "7.1 تتبع موقع"
        verbose_name_plural = "7.1 تتبع المواقع"
        ordering = ['-recorded_at']

    def __str__(self):
        status = "داخل النطاق" if self.within_radius else "خارج النطاق"
        return f"{self.employee.full_name} @ {self.recorded_at:%Y-%m-%d %H:%M} ({status})"


class Salary(BaseModel):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE,verbose_name="الموظف")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="الراتب الأساسي")
    bonuses = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المكافآت")
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="الخصومات")
    overtime = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="قيمة العمل الإضافي")
    pay_date = models.DateField(null=True, blank=True, verbose_name="تاريخ صرف الراتب")

    def __str__(self): return f"راتب {self.employee.full_name}"

    @property
    def total_salary(self):
        return self.base_salary + self.bonuses + self.overtime - self.deductions

    class Meta:
        verbose_name = "8. راتب"
        verbose_name_plural = "8. الرواتب"
        ordering = ['-pay_date']


class EmployeeLeaveBalance(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='leave_balances',
        verbose_name="الموظف",
    )
    year = models.PositiveSmallIntegerField(verbose_name="السنة", validators=[MinValueValidator(2000)])
    month = models.PositiveSmallIntegerField(
        verbose_name="الشهر",
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    quota_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        verbose_name="ساعات الإجازة المسموحة",
    )
    used_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        verbose_name="ساعات الإجازة المستخدمة",
    )

    class Meta:
        verbose_name = "رصيد إجازة شهري"
        verbose_name_plural = "أرصدة الإجازات الشهرية"
        unique_together = ('employee', 'year', 'month')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"رصيد {self.employee.full_name} لشهر {self.month}/{self.year}"

    @property
    def remaining_hours(self):
        remaining = (self.quota_hours or Decimal('0')) - (self.used_hours or Decimal('0'))
        return max(Decimal('0'), remaining)

# ===================================================================
# 4) التقارير والطلبات
# ===================================================================

class Report(BaseModel):
    REPORT_TYPE_CHOICES = [('daily', 'يومي'), ('monthly', 'شهري'), ('security', 'حالة أمنية'), ('complaint', 'شكوى')]
    STATUS_CHOICES = [('new', 'جديد'), ('resolved', 'تم حله'), ('escalated', 'تم تصعيده')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='reports', verbose_name="الموظف")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموقع")
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES, verbose_name="نوع التقرير")
    description = models.TextField(verbose_name="الوصف")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="الحالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الإنشاء")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="وقت الإغلاق")

    def __str__(self): return f"تقرير {self.get_report_type_display()} من {self.employee.full_name}"

    class Meta:
        verbose_name = "9. تقرير"
        verbose_name_plural = "9. التقارير"
        ordering = ['-created_at']


class ReportAttachment(BaseModel):
    FILE_TYPE_CHOICES = [('image', 'صورة'), ('video', 'فيديو')]

    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='attachments', verbose_name="التقرير")
    file = models.FileField(upload_to='report_attachments/', verbose_name="الملف")
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES, verbose_name="نوع الملف")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الرفع")

    def __str__(self): return f"مرفق لتقرير رقم {self.report.id}"

    class Meta:
        verbose_name = "مرفق تقرير"
        verbose_name_plural = "مرفقات التقارير"


class Request(BaseModel):
    REQUEST_TYPE_CHOICES = [
        ('coverage', 'تغطية'),
        ('leave', 'إجازة'),
        ('transfer', 'نقل'),
        ('materials', 'طلب مواد'),
        ('uniform', 'طلب زي'),
    ]
    STATUS_CHOICES = [('pending', 'قيد المراجعة'), ('approved', 'تمت الموافقة'), ('rejected', 'مرفوض')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='requests', verbose_name="صاحب الطلب")
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, verbose_name="نوع الطلب")
    description = models.TextField(verbose_name="تفاصيل الطلب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    approver = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='approved_requests', verbose_name="الموافق/الرافض")
    approval_notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات على القرار")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الإنشاء")

    leave_start = models.DateTimeField(null=True, blank=True, verbose_name="وقت بداية الإجازة")
    leave_end = models.DateTimeField(null=True, blank=True, verbose_name="وقت نهاية الإجازة")
    leave_hours = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="عدد ساعات الإجازة",
    )
    leave_deducted = models.BooleanField(
        default=False,
        verbose_name="تم خصم الرصيد",
        help_text="لمنع الخصم المكرر عند تغيير حالة الطلب",
    )
    uniform_delivery = models.ForeignKey(
        'UniformDelivery',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requests',
        verbose_name="نموذج الزي المرتبط",
    )

    def __str__(self): return f"طلب {self.get_request_type_display()} من {self.employee.full_name}"

    class Meta:
        verbose_name = "10. طلب"
        verbose_name_plural = "10. الطلبات"
        ordering = ['-created_at']

# ===================================================================
# 5) المخالفات (تعريف القاعدة ثم إسنادها للموظف)
# ===================================================================

class ViolationRule(BaseModel):
    """تعريف/لائحة المخالفة (نوع المخالفة ووصفها والإجراء الافتراضي)."""
    ACTION_CHOICES = [('warn', 'إنذار'), ('deduct', 'خصم'), ('terminate', 'فصل')]

    title = models.CharField(max_length=200, unique=True, verbose_name="عنوان المخالفة")
    description = models.TextField(blank=True, null=True, verbose_name="الوصف")
    default_action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='warn', verbose_name="الإجراء الافتراضي")
    default_deduction_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name="نسبة الخصم الافتراضية (%)", help_text="اتركها 0 إن لم ينطبق"
    )
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    def __str__(self): return self.title

    class Meta:
        verbose_name = "11. لائحة مخالفة"
        verbose_name_plural = "11. لوائح المخالفات"


class EmployeeViolation(BaseModel):
    """إسناد مخالفة محددة لموظف."""
    STATUS_CHOICES = [('pending', 'معلقة'), ('objected', 'تم الاعتراض'), ('action_taken', 'تم اتخاذ إجراء')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='violations', verbose_name="الموظف")
    rule = models.ForeignKey(ViolationRule, on_delete=models.PROTECT, related_name='assignments', verbose_name="المخالفة")
    reported_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True,
                                    related_name='reported_violations', verbose_name="المشرف المُبلغ")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموقع")
    description = models.TextField(blank=True, null=True, verbose_name="وصف الواقعة")
    occurred_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التسجيل")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    action_taken = models.TextField(blank=True, null=True, verbose_name="الإجراء المتخذ")
    warning_level = models.PositiveSmallIntegerField(default=1, verbose_name="تكرار/المرة رقم")
    deduction_value = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="قيمة الخصم (إن وجِد)")

    def __str__(self): return f"{self.rule.title} -> {self.employee.full_name}"

    class Meta:
        verbose_name = "12. مخالفة موظف"
        verbose_name_plural = "12. مخالفات الموظفين"
        ordering = ['-occurred_at']

# ===================================================================
# 6) العقود والمالية واللوجستيات
# ===================================================================

class Contract(BaseModel):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='contracts', verbose_name="الموظف")
    contract_file = models.FileField(upload_to='contracts/', verbose_name="ملف العقد")
    start_date = models.DateField(verbose_name="تاريخ بدء العقد")
    end_date = models.DateField(null=True, blank=True, verbose_name="تاريخ انتهاء العقد")
    is_signed = models.BooleanField(default=False, verbose_name="هل تم توقيعه؟")
    signed_at = models.DateTimeField(null=True, blank=True, verbose_name="وقت التوقيع")

    def __str__(self): return f"عقد الموظف {self.employee.full_name}"

    class Meta:
        verbose_name = "13. عقد"
        verbose_name_plural = "13. العقود"


class Advance(BaseModel):
    STATUS_CHOICES = [
        ('pending', 'قيد المراجعة'),
        ('approved', 'موافق عليها'),
        ('rejected', 'مرفوضة'),
        ('repaying', 'يتم السداد'),
        ('paid', 'مدفوعة بالكامل'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='advances', verbose_name="الموظف")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ")
    reason = models.TextField(blank=True, null=True, verbose_name="السبب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    requested_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الطلب")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الموافقة")
    deduction_applied = models.BooleanField(
        default=False,
        verbose_name="تم خصم السلفة من الراتب",
        help_text="علم إذا تم تحديث خصومات الراتب بهذه السلفة",
    )

    def __str__(self): return f"سلفة بقيمة {self.amount} للموظف {self.employee.full_name}"

    class Meta:
        verbose_name = "14. سلفة"
        verbose_name_plural = "14. السلف"
        ordering = ['-requested_at']


class Custody(BaseModel):
    STATUS_CHOICES = [('active', 'في العهدة'), ('returned', 'تم تسليمها')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='custodies', verbose_name="الموظف المسؤول")
    item_description = models.CharField(max_length=255, verbose_name="وصف العهدة")
    serial_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="الرقم التسلسلي (إن وجد)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="الحالة")
    received_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الاستلام")
    returned_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ التسليم")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")

    def __str__(self): return f"عهدة ({self.item_description}) لدى {self.employee.full_name}"

    class Meta:
        verbose_name = "15. عهدة"
        verbose_name_plural = "15. العهد"


class LogisticRequest(BaseModel):
    STATUS_CHOICES = [('new', 'جديد'), ('in_progress', 'قيد التنفيذ'), ('completed', 'تم التنفيذ')]

    supervisor = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='logistic_requests', verbose_name="المشرف الطالب")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='logistic_requests', verbose_name="الموقع")
    description = models.TextField(verbose_name="وصف الطلب اللوجستي")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="الحالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الطلب")

    def __str__(self): return f"طلب لوجستي لموقع {self.location.name}"

    class Meta:
        verbose_name = "16. طلب لوجستي"
        verbose_name_plural = "16. الطلبات اللوجستية"
        ordering = ['-created_at']

# ===================================================================
# 7) الزي الرسمي
# ===================================================================

class UniformItem(BaseModel):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القطعة")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="السعر الافتراضي")

    def __str__(self): return self.name

    class Meta:
        verbose_name = "17. قطعة زي"
        verbose_name_plural = "17. قطع الزي"


class UniformDelivery(BaseModel):
    PAYMENT_METHOD_CHOICES = [('direct', 'دفع مباشر للمصنع'), ('deduction', 'خصم من الراتب')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='uniform_deliveries', verbose_name="الموظف المستلم")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموقع")
    delivery_date = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الاستلام")
    total_value = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="القيمة الإجمالية")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, verbose_name="طريقة الدفع")
    operations_manager_signature = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_uniforms_manager', verbose_name="توقيع رئيس العمليات"
    )
    operations_assistant_signature = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_uniforms_assistant', verbose_name="توقيع مساعد المدير"
    )
    is_finalized = models.BooleanField(default=False, verbose_name="هل تم إغلاق النموذج؟")

    def __str__(self): return f"استلام زي للموظف {self.employee.full_name} بتاريخ {self.delivery_date.strftime('%Y-%m-%d')}"

    def update_total_value(self):
        total = sum(item.value for item in self.items.all())
        if self.total_value != total:
            self.total_value = total
            self.save(update_fields=['total_value'])

    class Meta:
        verbose_name = "18. نموذج استلام زي"
        verbose_name_plural = "18. نماذج استلام الزي"
        ordering = ['-delivery_date']


class UniformDeliveryItem(BaseModel):
    delivery = models.ForeignKey(UniformDelivery, on_delete=models.CASCADE, related_name='items', verbose_name="نموذج الاستلام")
    item = models.ForeignKey(UniformItem, on_delete=models.CASCADE, verbose_name="القطعة")
    quantity = models.PositiveIntegerField(default=1, verbose_name="الكمية")
    value = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="القيمة")
    notes = models.CharField(max_length=255, blank=True, null=True, verbose_name="ملاحظات")

    def __str__(self): return f"{self.quantity} x {self.item.name}"

    def save(self, *args, **kwargs):
        self.value = self.item.price * self.quantity
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "بند في نموذج استلام"
        verbose_name_plural = "بنود نماذج الاستلام"




class TrustedDevice(BaseModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="trusted_devices",
        verbose_name="المستخدم",
    )
    device_hash = models.CharField(max_length=128, verbose_name="بصمة الجهاز")
    device_name = models.CharField(max_length=200, blank=True, verbose_name="اسم الجهاز")
    first_seen_at = models.DateTimeField(auto_now_add=True, verbose_name="أول ظهور")
    last_seen_at = models.DateTimeField(auto_now=True, verbose_name="آخر ظهور")

    class Meta:
        verbose_name = "جهاز موثوق"
        verbose_name_plural = "الأجهزة الموثوقة"
        unique_together = ("user", "device_hash")

    def __str__(self):
        name = self.device_name or "(بدون اسم)"
        return f"{self.user.username} - {name}"


class DeviceLoginChallenge(BaseModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="device_login_challenges",
        verbose_name="المستخدم",
    )
    device_hash = models.CharField(max_length=128, verbose_name="بصمة الجهاز")
    device_name = models.CharField(max_length=200, blank=True, verbose_name="اسم الجهاز")
    code_hash = models.CharField(max_length=128, verbose_name="هاش رمز التحقق")
    expires_at = models.DateTimeField(verbose_name="ينتهي في")
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name="عدد المحاولات")
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name="وقت التوثيق")

    class Meta:
        verbose_name = "طلب توثيق جهاز"
        verbose_name_plural = "طلبات توثيق الأجهزة"
        indexes = [
            models.Index(fields=["user", "device_hash"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.device_name or self.device_hash[:8]}"

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at < timezone.now()


class PasswordResetSMS(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_resets_sms")
    phone = models.CharField(max_length=32, db_index=True)
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.phone} @ {self.created_at:%Y-%m-%d %H:%M}"


# ===================================================================
# 8) Signals
# ===================================================================

@receiver(post_save, sender=UniformDeliveryItem)
def update_delivery_total_value(sender, instance, **kwargs):
    instance.delivery.update_total_value()


@receiver(post_save, sender=UniformDelivery)
def apply_salary_deduction_for_uniform(sender, instance, created, **kwargs):
    """
    خصم تلقائي من راتب الموظف عند إغلاق نموذج الزي والدفع بالخصم.
    """
    if instance.payment_method == 'deduction' and instance.is_finalized:
        salary, _ = Salary.objects.get_or_create(employee=instance.employee)
        salary.deductions = F('deductions') + instance.total_value
        salary.save()
        print(f"تمت إضافة خصم بقيمة {instance.total_value} إلى راتب الموظف {instance.employee.full_name}")


TWO_DECIMAL_PLACES = Decimal('0.01')


def _quantize_hours(value: Decimal | float | int | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


def _get_leave_balance(employee: Employee, dt) -> tuple[EmployeeLeaveBalance, bool]:
    if dt is None:
        raise ValidationError("تاريخ الإجازة غير معروف")
    quota = _quantize_hours(employee.monthly_leave_quota_hours or Decimal('0'))
    defaults = {
        'quota_hours': quota or Decimal('0'),
        'used_hours': Decimal('0'),
    }
    balance, created = EmployeeLeaveBalance.objects.get_or_create(
        employee=employee,
        year=dt.year,
        month=dt.month,
        defaults=defaults,
    )
    if quota is not None and balance.quota_hours != quota:
        balance.quota_hours = quota
        balance.save(update_fields=['quota_hours'])
    return balance, created


def _month_floor(dt: datetime | date) -> date:
    if isinstance(dt, datetime):
        return date(dt.year, dt.month, 1)
    return date(dt.year, dt.month, 1)


def _iter_months(start: date, end: date):
    current = date(start.year, start.month, 1)
    end_point = date(end.year, end.month, 1)
    while current <= end_point:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def _ensure_leave_balances(employee: Employee, upto_dt: datetime | date) -> list[EmployeeLeaveBalance]:
    hire_date = employee.hire_date
    if not hire_date:
        raise ValidationError("يجب تحديد تاريخ التعيين للموظف قبل احتساب الإجازات")

    target = _month_floor(upto_dt)
    start = date(hire_date.year, hire_date.month, 1)
    if start > target:
        start = target

    balances: list[EmployeeLeaveBalance] = []
    for month_date in _iter_months(start, target):
        balance, _ = _get_leave_balance(employee, month_date)
        balances.append(balance)
    return balances


@receiver(pre_save, sender=Request)
def prepare_leave_request(sender, instance: Request, **kwargs):
    instance._old_status = None
    instance._old_leave_hours = Decimal('0')
    instance._old_leave_start = None

    if instance.pk:
        try:
            previous = Request.objects.get(pk=instance.pk)
        except Request.DoesNotExist:
            previous = None
        if previous:
            instance._old_status = previous.status
            instance._old_leave_hours = previous.leave_hours or Decimal('0')
            instance._old_leave_start = previous.leave_start

    if instance.request_type != 'leave':
        instance.leave_start = None
        instance.leave_end = None
        instance.leave_hours = None
        instance.leave_deducted = False
        return

    if instance.leave_start and instance.leave_end:
        duration = instance.leave_end - instance.leave_start
        total_seconds = duration.total_seconds()
        if total_seconds <= 0:
            raise ValidationError("وقت نهاية الإجازة يجب أن يكون بعد وقت البداية")
        hours = _quantize_hours(Decimal(str(total_seconds)) / Decimal('3600'))
        instance.leave_hours = hours
    else:
        instance.leave_hours = None

    if instance.status == 'approved':
        if not instance.leave_start or not instance.leave_end:
            raise ValidationError("يجب تحديد وقت البداية والنهاية للإجازة قبل الموافقة")
        if not instance.leave_hours or instance.leave_hours <= 0:
            raise ValidationError("مدة الإجازة غير صالحة")

        balance, _ = _get_leave_balance(instance.employee, instance.leave_start)

        used_without_current = balance.used_hours or Decimal('0')
        if instance._old_status == 'approved':
            used_without_current -= instance._old_leave_hours or Decimal('0')
            if used_without_current < 0:
                used_without_current = Decimal('0')

        projected = used_without_current + (instance.leave_hours or Decimal('0'))
        quota = balance.quota_hours or Decimal('0')
        if quota <= 0:
            raise ValidationError("لا يوجد رصيد إجازات شهري محدد لهذا الموظف")
        if projected - quota > Decimal('0.0001'):
            remaining = _quantize_hours(quota - used_without_current) or Decimal('0')
            raise ValidationError(
                f"رصيد الإجازة المتبقي ({remaining} ساعة) لا يكفي لتغطية هذه الإجازة"
            )

        cumulative_balances = _ensure_leave_balances(instance.employee, instance.leave_start)
        total_quota = sum((b.quota_hours or Decimal('0')) for b in cumulative_balances)
        total_used = sum((b.used_hours or Decimal('0')) for b in cumulative_balances)
        if instance._old_status == 'approved':
            total_used -= instance._old_leave_hours or Decimal('0')
            if total_used < 0:
                total_used = Decimal('0')

        projected_total = total_used + (instance.leave_hours or Decimal('0'))
        if projected_total - total_quota > Decimal('0.0001'):
            remaining_total = _quantize_hours(total_quota - total_used) or Decimal('0')
            raise ValidationError(
                f"إجمالي رصيد الإجازات المتاح ({remaining_total} ساعة) لا يكفي لتغطية هذه الإجازة"
            )


@receiver(post_save, sender=Request)
def sync_leave_balance(sender, instance: Request, created, **kwargs):
    if instance.request_type != 'leave':
        if instance.leave_deducted:
            type(instance).objects.filter(pk=instance.pk).update(leave_deducted=False)
        return

    new_hours = instance.leave_hours or Decimal('0')
    old_status = getattr(instance, '_old_status', None)
    old_hours = getattr(instance, '_old_leave_hours', Decimal('0'))
    old_start = getattr(instance, '_old_leave_start', None)

    if instance.status == 'approved' and instance.leave_start:
        with transaction.atomic():
            balance, _ = _get_leave_balance(instance.employee, instance.leave_start)
            used = balance.used_hours or Decimal('0')
            if instance.leave_deducted and old_status == 'approved':
                delta = new_hours - old_hours
            elif instance.leave_deducted and old_status != 'approved':
                delta = new_hours
            elif old_status == 'approved':
                delta = new_hours - old_hours
            else:
                delta = new_hours

            if delta:
                balance.used_hours = _quantize_hours(used + delta) or Decimal('0')
                if balance.used_hours < 0:
                    balance.used_hours = Decimal('0')
                balance.save(update_fields=['used_hours'])

        if not instance.leave_deducted:
            type(instance).objects.filter(pk=instance.pk).update(leave_deducted=True)

    elif instance.leave_deducted:
        target_start = old_start or instance.leave_start
        if target_start:
            with transaction.atomic():
                balance, _ = _get_leave_balance(instance.employee, target_start)
                used = balance.used_hours or Decimal('0')
                refund = old_hours or new_hours
                if refund:
                    balance.used_hours = _quantize_hours(used - refund) or Decimal('0')
                    if balance.used_hours < 0:
                        balance.used_hours = Decimal('0')
                    balance.save(update_fields=['used_hours'])

        type(instance).objects.filter(pk=instance.pk).update(leave_deducted=False)


def _quantize_currency(value: Decimal | float | int | None) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


@receiver(pre_save, sender=Advance)
def validate_advance(sender, instance: Advance, **kwargs):
    instance._old_status = None
    instance._old_amount = Decimal('0')

    if instance.pk:
        try:
            previous = Advance.objects.get(pk=instance.pk)
        except Advance.DoesNotExist:
            previous = None
        if previous:
            instance._old_status = previous.status
            instance._old_amount = previous.amount or Decimal('0')

    amount = _quantize_currency(instance.amount)
    if not amount or amount <= 0:
        raise ValidationError("قيمة السلفة يجب أن تكون أكبر من صفر")
    instance.amount = amount

    salary, _ = Salary.objects.get_or_create(employee=instance.employee)
    base_salary = _quantize_currency(salary.base_salary)
    if not base_salary or base_salary <= 0:
        raise ValidationError("لا يمكن طلب السلفة قبل تحديد الراتب الأساسي")

    max_allowed = _quantize_currency(base_salary * Decimal('0.20'))
    if max_allowed is None or amount - max_allowed > Decimal('0.0001'):
        raise ValidationError(
            f"قيمة السلفة تتجاوز الحد المسموح (20% من الراتب: {max_allowed} ريال)"
        )

    if instance.status == 'approved':
        hire_date = instance.employee.hire_date
        if not hire_date:
            raise ValidationError("يجب تحديد تاريخ التعيين للموظف قبل الموافقة على السلفة")
        days_worked = (timezone.now().date() - hire_date).days
        if days_worked < 30:
            raise ValidationError("لا يمكن الموافقة على السلفة قبل إكمال شهر عمل كامل")
        if not instance.approved_at:
            instance.approved_at = timezone.now()
    else:
        instance.approved_at = instance.approved_at if instance.pk else None


@receiver(post_save, sender=Advance)
def sync_advance_deduction(sender, instance: Advance, created, **kwargs):
    old_status = getattr(instance, '_old_status', None)
    old_amount = getattr(instance, '_old_amount', Decimal('0'))

    new_effective = instance.amount if instance.status == 'approved' else Decimal('0')
    old_effective = old_amount if old_status == 'approved' else Decimal('0')
    delta = _quantize_currency(new_effective - old_effective) or Decimal('0')

    if delta:
        with transaction.atomic():
            salary, _ = Salary.objects.select_for_update().get_or_create(employee=instance.employee)
            current = _quantize_currency(salary.deductions) or Decimal('0')
            updated = current + delta
            if updated < 0:
                updated = Decimal('0')
            salary.deductions = _quantize_currency(updated)
            salary.save(update_fields=['deductions'])

    should_flag = instance.status == 'approved'
    if instance.deduction_applied != should_flag:
        type(instance).objects.filter(pk=instance.pk).update(deduction_applied=should_flag)
