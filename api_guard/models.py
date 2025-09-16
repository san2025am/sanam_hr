# api_guard/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

# ===================================================================
# 1. جداول المستخدمين والموظفين (Users & Employees)
# ===================================================================

class Role(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الدور")
    description = models.TextField(blank=True, null=True, verbose_name="وصف الدور")
    def __str__(self): return self.name
    class Meta:
        verbose_name = "1. دور"
        verbose_name_plural = "1. الأدوار"

class User(AbstractUser):
    role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الدور")
    def __str__(self): return self.username
    class Meta:
        verbose_name = "2. مستخدم"
        verbose_name_plural = "2. المستخدمون"

class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, verbose_name="حساب المستخدم")
    full_name = models.CharField(max_length=255, verbose_name="الاسم الرباعي")
    national_id = models.CharField(max_length=20, unique=True, verbose_name="رقم الهوية")
    phone_number = models.CharField(max_length=20, unique=True, verbose_name="رقم الجوال")
    bank_account = models.CharField(max_length=50, blank=True, null=True, verbose_name="رقم الحساب البنكي")
    hire_date = models.DateField(null=True, blank=True, verbose_name="تاريخ التعيين")
    id_image = models.ImageField(upload_to='id_cards/', verbose_name="صورة الهوية", null=True, blank=True)
    date_of_birth_gregorian = models.DateField(null=True, blank=True, verbose_name="تاريخ الميلاد (ميلادي)")
    id_expiry_date = models.DateField(null=True, blank=True, verbose_name="تاريخ انتهاء الهوية")
    supervisor = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subordinates', verbose_name="المشرف المباشر")
    def __str__(self): return self.full_name
    class Meta:
        verbose_name = "3. موظف"
        verbose_name_plural = "3. الموظفين"

# ===================================================================
# 2. جداول المواقع والمهام والورديات
# ===================================================================

class Location(models.Model):
    name = models.CharField(max_length=200, verbose_name="اسم الموقع")
    client_name = models.CharField(max_length=200, verbose_name="اسم العميل")
    gps_coordinates = models.CharField(max_length=100, blank=True, null=True, verbose_name="إحداثيات الموقع")
    gps_radius = models.PositiveIntegerField(default=50, verbose_name="نطاق GPS المسموح به (بالمتر)")
    assigned_employees = models.ManyToManyField(Employee, through='EmployeeLocationAssignment', related_name='locations')
    def __str__(self): return self.name
    class Meta:
        verbose_name = "4. موقع"
        verbose_name_plural = "4. المواقع"

class EmployeeLocationAssignment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, verbose_name="الموظف")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, verbose_name="الموقع")
    def __str__(self): return f"{self.employee.full_name} @ {self.location.name}"
    class Meta:
        unique_together = ('employee', 'location')
        verbose_name = "تعيين موظف لموقع"
        verbose_name_plural = "تعيينات الموظفين للمواقع"

class Task(models.Model):
    STATUS_CHOICES = [('new', 'جديدة'), ('in_progress', 'قيد التنفيذ'), ('completed', 'مكتملة')]
    title = models.CharField(max_length=200, verbose_name="عنوان المهمة")
    description = models.TextField(verbose_name="وصف المهمة")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="الحالة")
    due_date = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الاستحقاق")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='tasks', verbose_name="الموقع")
    assigned_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='created_tasks', verbose_name="أُنشئت بواسطة")
    assigned_to = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='assigned_tasks', verbose_name="مُكلف بها")
    def __str__(self): return self.title
    class Meta:
        verbose_name = "5. مهمة"
        verbose_name_plural = "5. المهام"
        ordering = ['-due_date']

class Shift(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم الوردية")
    start_time = models.TimeField(verbose_name="وقت البدء")
    end_time = models.TimeField(verbose_name="وقت الانتهاء")
    def __str__(self):
        start = self.start_time.strftime('%I:%M %p'); end = self.end_time.strftime('%I:%M %p')
        return f"{self.name} ({start} - {end})"
    class Meta:
        verbose_name = "6. وردية"
        verbose_name_plural = "6. الورديات"

# ===================================================================
# 3. جداول الحضور والرواتب
# ===================================================================

class AttendanceRecord(models.Model):
    WORK_TYPE_CHOICES = [('official', 'دوام رسمي'), ('coverage', 'تغطية'), ('overtime', 'إضافي')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records', verbose_name="الموظف")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموقع")
    check_in_time = models.DateTimeField(verbose_name="وقت الحضور")
    check_out_time = models.DateTimeField(null=True, blank=True, verbose_name="وقت الانصراف")
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الوردية")
    work_type = models.CharField(max_length=20, choices=WORK_TYPE_CHOICES, default='official', verbose_name="نوع الدوام")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    def __str__(self): return f"{self.employee.full_name} - {self.check_in_time.strftime('%Y-%m-%d')}"
    class Meta:
        verbose_name = "7. سجل حضور"
        verbose_name_plural = "7. سجلات الحضور"
        ordering = ['-check_in_time']

# في ملف api_guard/models.py

class Salary(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, primary_key=True, verbose_name="الموظف")
    
    # --- التعديل هنا: إضافة default=0 ---
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="الراتب الأساسي")
    bonuses = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المكافآت")
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="الخصومات")
    overtime = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="قيمة العمل الإضافي")
    
    pay_date = models.DateField(verbose_name="تاريخ صرف الراتب", null=True, blank=True) # من الأفضل جعل التاريخ اختياريًا أيضًا

    def __str__(self):
        return f"راتب {self.employee.full_name}"

    @property
    def total_salary(self):
        # هذه الدالة الآن آمنة لأن الحقول لن تكون None أبدًا
        return self.base_salary + self.bonuses + self.overtime - self.deductions

    class Meta:
        verbose_name = "8. راتب"
        verbose_name_plural = "8. الرواتب"
        ordering = ['-pay_date']
        
# ===================================================================
# 4. جداول التقارير والطلبات
# ===================================================================

class Report(models.Model):
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

class ReportAttachment(models.Model):
    FILE_TYPE_CHOICES = [('image', 'صورة'), ('video', 'فيديو')]
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name='attachments', verbose_name="التقرير")
    file = models.FileField(upload_to='report_attachments/', verbose_name="الملف")
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES, verbose_name="نوع الملف")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الرفع")
    def __str__(self): return f"مرفق لتقرير رقم {self.report.id}"
    class Meta:
        verbose_name = "مرفق تقرير"
        verbose_name_plural = "مرفقات التقارير"

class Request(models.Model):
    REQUEST_TYPE_CHOICES = [('coverage', 'تغطية'), ('transfer', 'نقل'), ('materials', 'طلب مواد')]
    STATUS_CHOICES = [('pending', 'قيد المراجعة'), ('approved', 'تمت الموافقة'), ('rejected', 'مرفوض')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='requests', verbose_name="صاحب الطلب")
    request_type = models.CharField(max_length=20, choices=REQUEST_TYPE_CHOICES, verbose_name="نوع الطلب")
    description = models.TextField(verbose_name="تفاصيل الطلب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    approver = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_requests', verbose_name="الموافق/الرافض")
    approval_notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات على القرار")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت الإنشاء")
    def __str__(self): return f"طلب {self.get_request_type_display()} من {self.employee.full_name}"
    class Meta:
        verbose_name = "10. طلب"
        verbose_name_plural = "10. الطلبات"
        ordering = ['-created_at']

# ===================================================================
# 5. جداول المخالفات والعقود
# ===================================================================

class Violation(models.Model):
    VIOLATION_TYPE_CHOICES = [('flag1', 'إنذار'), ('flag2', 'خصم'), ('flag3', 'فصل')]
    STATUS_CHOICES = [('pending', 'معلقة'), ('objected', 'تم الاعتراض'), ('action_taken', 'تم اتخاذ إجراء')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='violations', verbose_name="الموظف المخالف")
    reported_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, related_name='reported_violations', verbose_name="المشرف المُبلغ")
    violation_type = models.CharField(max_length=10, choices=VIOLATION_TYPE_CHOICES, verbose_name="نوع المخالفة")
    description = models.TextField(verbose_name="وصف المخالفة")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    action_taken = models.TextField(blank=True, null=True, verbose_name="الإجراء المتخذ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="وقت التسجيل")
    def __str__(self): return f"مخالفة ({self.get_violation_type_display()}) على {self.employee.full_name}"
    class Meta:
        verbose_name = "11. مخالفة"
        verbose_name_plural = "11. المخالفات"
        ordering = ['-created_at']

class Contract(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='contracts', verbose_name="الموظف")
    contract_file = models.FileField(upload_to='contracts/', verbose_name="ملف العقد")
    start_date = models.DateField(verbose_name="تاريخ بدء العقد")
    end_date = models.DateField(null=True, blank=True, verbose_name="تاريخ انتهاء العقد")
    is_signed = models.BooleanField(default=False, verbose_name="هل تم توقيعه؟")
    signed_at = models.DateTimeField(null=True, blank=True, verbose_name="وقت التوقيع")
    def __str__(self): return f"عقد الموظف {self.employee.full_name}"
    class Meta:
        verbose_name = "12. عقد"
        verbose_name_plural = "12. العقود"

# ===================================================================
# 6. جداول المالية واللوجستيات
# ===================================================================

class Advance(models.Model):
    STATUS_CHOICES = [('pending', 'قيد المراجعة'), ('approved', 'موافق عليها'), ('rejected', 'مرفوضة'), ('repaying', 'يتم السداد'), ('paid', 'مدفوعة بالكامل')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='advances', verbose_name="الموظف")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ")
    reason = models.TextField(blank=True, null=True, verbose_name="السبب")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    requested_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الطلب")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="تاريخ الموافقة")
    def __str__(self): return f"سلفة بقيمة {self.amount} للموظف {self.employee.full_name}"
    class Meta:
        verbose_name = "13. سلفة"
        verbose_name_plural = "13. السلف"
        ordering = ['-requested_at']

class Custody(models.Model):
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
        verbose_name = "14. عهدة"
        verbose_name_plural = "14. العهد"

class LogisticRequest(models.Model):
    STATUS_CHOICES = [('new', 'جديد'), ('in_progress', 'قيد التنفيذ'), ('completed', 'تم التنفيذ')]
    supervisor = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='logistic_requests', verbose_name="المشرف الطالب")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='logistic_requests', verbose_name="الموقع")
    description = models.TextField(verbose_name="وصف الطلب اللوجستي")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', verbose_name="الحالة")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ الطلب")
    def __str__(self): return f"طلب لوجستي لموقع {self.location.name}"
    class Meta:
        verbose_name = "15. طلب لوجستي"
        verbose_name_plural = "15. الطلبات اللوجستية"
        ordering = ['-created_at']

# ===================================================================
# 7. نماذج استلام الزي الرسمي
# ===================================================================

class UniformItem(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="اسم القطعة")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="السعر الافتراضي")
    def __str__(self): return self.name
    class Meta:
        verbose_name = "16. قطعة زي"
        verbose_name_plural = "16. قطع الزي"

class UniformDelivery(models.Model):
    PAYMENT_METHOD_CHOICES = [('direct', 'دفع مباشر للمصنع'), ('deduction', 'خصم من الراتب')]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='uniform_deliveries', verbose_name="الموظف المستلم")
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الموقع")
    delivery_date = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ ووقت الاستلام")
    total_value = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="القيمة الإجمالية")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, verbose_name="طريقة الدفع")
    operations_manager_signature = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_uniforms_manager', verbose_name="توقيع رئيس العمليات")
    operations_assistant_signature = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_uniforms_assistant', verbose_name="توقيع مساعد المدير")
    is_finalized = models.BooleanField(default=False, verbose_name="هل تم إغلاق النموذج؟")
    def __str__(self): return f"استلام زي للموظف {self.employee.full_name} بتاريخ {self.delivery_date.strftime('%Y-%m-%d')}"
    def update_total_value(self):
        total = sum(item.value for item in self.items.all())
        if self.total_value != total:
            self.total_value = total
            self.save(update_fields=['total_value'])
    class Meta:
        verbose_name = "17. نموذج استلام زي"
        verbose_name_plural = "17. نماذج استلام الزي"
        ordering = ['-delivery_date']

class UniformDeliveryItem(models.Model):
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

# ===================================================================
# 8. الإشارات (Signals)
# ===================================================================

@receiver(post_save, sender=UniformDeliveryItem)
def update_delivery_total_value(sender, instance, **kwargs):
    """Signal to update the total value of the delivery when an item is saved."""
    instance.delivery.update_total_value()

@receiver(post_save, sender=UniformDelivery)
def apply_salary_deduction_for_uniform(sender, instance, created, **kwargs):
    """
    Signal to automatically apply a deduction to the employee's salary
    if the uniform payment method is 'deduction' and the delivery is finalized.
    """
    if instance.payment_method == 'deduction' and instance.is_finalized:
        # نبحث عن سجل الراتب الخاص بالموظف أو ننشئه إذا لم يكن موجودًا
        salary, created = Salary.objects.get_or_create(employee=instance.employee)
        
        # نضيف قيمة الزي إلى الخصومات
        # نستخدم F() expression لتجنب race conditions
        from django.db.models import F
        salary.deductions = F('deductions') + instance.total_value
        salary.save()
        
        # يمكنك إضافة منطق إضافي هنا، مثل إرسال إشعار
        print(f"تمت إضافة خصم بقيمة {instance.total_value} إلى راتب الموظف {instance.employee.full_name}")
