
from django import forms  # type: ignore
from .models import JobApplication
from api_guard.models import Employee, Contract
from django.forms.widgets import ClearableFileInput

class MultiFileInput(ClearableFileInput):
    # هذا يجعل الودجت يدعم multiple
    allow_multiple_selected = True

from django import forms
from django.forms.widgets import ClearableFileInput, TextInput, Textarea, EmailInput, Select, FileInput
from api_guard.models import Employee, Contract
from .models import JobApplication 
class MultiFileInput(ClearableFileInput):
    allow_multiple_selected = True

class JobApplicationForm(forms.ModelForm):
    other_qualifications = forms.FileField(
        label="مؤهلات/شهادات إضافية (يمكن عدة ملفات)",
        required=False,
        widget=MultiFileInput(attrs={
            "multiple": True,
            "accept": "application/pdf,image/*",
            "class": "form-control"
        })
    )

    class Meta:
        model = JobApplication
        fields = [
            "full_name", "national_id", "phone", "email", "position",
            "resume", "qualification_document", "cover_letter"
        ]
        widgets = {
            "full_name": TextInput(attrs={
                "class": "form-control", "placeholder": "أدخل الاسم الرباعي", "required": True
            }),
            "national_id": TextInput(attrs={
                "class": "form-control", "placeholder": "10 أرقام", "pattern": r"^\d{10}$",
                "inputmode": "numeric", "required": True
            }),
            "phone": TextInput(attrs={
                "class": "form-control", "placeholder": "05xxxxxxxx", "pattern": r"^05\d{8}$",
                "inputmode": "tel", "dir": "ltr", "required": True
            }),
            "email": EmailInput(attrs={
                "class": "form-control", "placeholder": "example@domain.com", "dir": "ltr"
            }),
            "position": Select(attrs={
                "class": "form-select", "required": True
            }),
            "resume": ClearableFileInput(attrs={
                "class": "form-control", "accept": "application/pdf,image/*"
            }),
            "qualification_document": ClearableFileInput(attrs={
                "class": "form-control", "accept": "application/pdf,image/*"
            }),
            "cover_letter": Textarea(attrs={
                "class": "form-control", "rows": 4, "placeholder": "اكتب رسالة توضيحية (اختياري)"
            }),
        }

    def clean_national_id(self):
        nid = (self.cleaned_data.get("national_id") or "").strip()
        if not nid.isdigit() or len(nid) != 10:
            raise forms.ValidationError("رقم الهوية يجب أن يكون 10 أرقام.")
        return nid

    def clean_phone(self):
        p = (self.cleaned_data.get("phone") or "").strip()
        if not p.startswith("05") or len(p) != 10 or not p.isdigit():
            raise forms.ValidationError("رقم الجوال يجب أن يبدأ بـ 05 ويتكون من 10 أرقام.")
        return p


class EmployeeEducationForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["education_level", "major", "qualification_document"]


class ContractForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = ["employee", "title", "contract_type", "start_date", "end_date", "salary", "file", "body",
                  "signed_by_employee", "signed_by_company"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


