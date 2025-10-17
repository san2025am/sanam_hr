# في ملف api_guard/urls.py

from django.urls import path,include
# سنقوم بإنشاء هذه الـ views في الخطوة التالية
from rest_framework.routers import DefaultRouter
# 1. إنشاء Router
router = DefaultRouter()
from api_guard.views import (
    AttendanceCheckAPIView,
    AttendanceExistsView,
    AttendanceLastForMeView,
    GuardLoginAndProfileView,
    GuardMeView,
    GuardReportListCreateView,
    GuardRequestListCreateView,
    GuardAdvanceListCreateView,
    GuardTaskListView,
    GuardTaskUpdateView,
    GuardUniformItemListView,
    GuardProfilePhotoUploadView,
    PasswordForgotUsernameView,
    PasswordResetUsernameView,
    ResolveLocationAPIView,
    LocationPingAPIView,
    GeofenceViolationPauseAPIView,
)
from api_guard.api_flutter import (
    TodayHolidayView,
    LeaveBalanceView,
    LeaveApplyView,
    PayslipView,
    RewardsListView,
    OvertimeListView,
    MarkItemPaidView,
)


# 2. تسجيل الـ ViewSet مع الـ Router
# 'roles' هو المسار الذي سيتم استخدامه في الـ URL (e.g., /api/v1/roles/)

urlpatterns = [
    
    # مثال: نقطة نهاية محمية لعرض بيانات المستخدم الحالي
    path("auth/guard/login/", GuardLoginAndProfileView.as_view(), name="guard-login"),
    path("auth/guard/me/", GuardMeView.as_view(), name="guard-me"),
    path("auth/password/forgot/username/", PasswordForgotUsernameView.as_view(), name="password-forgot-Username"),
    path("auth/password/reset/username/",  PasswordResetUsernameView.as_view(),  name="password-reset-Username"),
    
    path("attendance/check/", AttendanceCheckAPIView.as_view(), name="attendance-check"),

    path("attendance/resolve-location/", ResolveLocationAPIView.as_view(), name="resolve-location"),
    path("attendance/location-ping/", LocationPingAPIView.as_view(), name="attendance-location-ping"),
    path("attendance/violation-pause/", GeofenceViolationPauseAPIView.as_view(), name="attendance-violation-pause"),
    path("guards/reports/", GuardReportListCreateView.as_view(), name="guard-reports"),
    path("guards/requests/", GuardRequestListCreateView.as_view(), name="guard-requests"),
    path("guards/advances/", GuardAdvanceListCreateView.as_view(), name="guard-advances"),
    path("guards/tasks/", GuardTaskListView.as_view(), name="guard-tasks"),
    path("guards/tasks/<uuid:pk>/", GuardTaskUpdateView.as_view(), name="guard-task-update"),
    path("guards/uniform-items/", GuardUniformItemListView.as_view(), name="guard-uniform-items"),
    path("guards/profile/photo/", GuardProfilePhotoUploadView.as_view(), name="guard-profile-photo"),
    path("attendance/last/", AttendanceLastForMeView.as_view(), name="attendance_last"),
    path("attendance/exists/<uuid:pk>/", AttendanceExistsView.as_view(), name="attendance_exists"),
    # Flutter API endpoints
    path("holidays/today/", TodayHolidayView.as_view(), name="holidays-today"),
    path("leaves/balance/", LeaveBalanceView.as_view(), name="leaves-balance"),
    path("leaves/apply/", LeaveApplyView.as_view(), name="leaves-apply"),
    path("payroll/cycle/<int:y>-<int:m>/payslip/", PayslipView.as_view(), name="payroll-payslip"),
    path("payroll/rewards/", RewardsListView.as_view(), name="payroll-rewards"),
    path("payroll/overtime/", OvertimeListView.as_view(), name="payroll-overtime"),
    path("payroll/items/<uuid:pk>/mark-paid/", MarkItemPaidView.as_view(), name="payroll-item-mark-paid"),
]
