from django.contrib.admin import AdminSite

class FunctionalAdminSite(AdminSite):
    required_groups: list[str] = []
    site_header = "سنام — لوحة القسم"
    site_title  = "سنام — لوحة القسم"
    index_title = "مرحبًا بك"

    def has_permission(self, request):
        if not (request.user.is_active and request.user.is_staff):
            return False
        if request.user.is_superuser:
            return True
        return (not self.required_groups) or request.user.groups.filter(name__in=self.required_groups).exists()

hr_admin       = FunctionalAdminSite(name="hr_admin");       hr_admin.site_header="سنام — الموارد البشرية";  hr_admin.index_title="لوحة الموارد البشرية";  hr_admin.required_groups=["HR"]
finance_admin  = FunctionalAdminSite(name="finance_admin");  finance_admin.site_header="سنام — الشؤون المالية"; finance_admin.index_title="لوحة المالية"; finance_admin.required_groups=["Finance"]
ops_admin      = FunctionalAdminSite(name="ops_admin");      ops_admin.site_header="سنام — العمليات والحضور";  ops_admin.index_title="لوحة العمليات";      ops_admin.required_groups=["Operations"]
log_admin      = FunctionalAdminSite(name="logistics_admin");log_admin.site_header="سنام — اللوجستيات";        log_admin.index_title="لوحة اللوجستيات";    log_admin.required_groups=["Logistics"]
