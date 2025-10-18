
from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path("apply/", views.job_application_create, name="job_application_create"),
    path("apply/success/", views.job_application_success, name="job_application_success"),
    # Alias: /hr/jobapplication/ → admin HR list of JobApplications
    path("jobapplication/", RedirectView.as_view(url="/admin/hr/hr/jobapplication/", permanent=False), name="job_application_admin_alias"),
    path("employee/<int:employee_id>/education/", views.employee_education_update, name="employee_education_update"),
    path("contracts/new/", views.contract_create, name="contract_create"),
    path("contracts/<int:pk>/sign/", views.contract_sign, name="contract_sign"),
    path("contracts/<int:pk>/sign/submit/", views.contract_sign_submit, name="contract_sign_submit"),
    path("contracts/<int:pk>/sign/<slug:token>/", views.contract_sign_public, name="contract_sign_public"),
    path("contracts/<int:pk>/sign/<slug:token>/submit/", views.contract_sign_public_submit, name="contract_sign_public_submit"),
    # توقيع الإدارة
    path("contracts/<int:pk>/company-sign/", views.contract_company_sign, name="contract_company_sign"),
    path("contracts/<int:pk>/company-sign/submit/", views.contract_company_sign_submit, name="contract_company_sign_submit"),

]
