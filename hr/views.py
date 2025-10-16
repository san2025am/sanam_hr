
import base64, os
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML, CSS
from django.core.files import File

from .forms import JobApplicationForm, EmployeeEducationForm, ContractForm
from .models import JobApplication
from api_guard.models import  Employee, AdditionalQualification, Contract
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt  # سنستخدمه لنداء fetch العام



@require_http_methods(["GET", "POST"])
def job_application_create(request):
    if request.method == "POST":
        form = JobApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            app = form.save()
            from django.contrib import messages
            messages.success(request, "تم استلام طلبك بنجاح. سنقوم بالتواصل معك قريبًا.")
            return redirect("job_application_success")
        else:
            from django.contrib import messages
            messages.error(request, "تعذّر إرسال الطلب. فضلاً راجع البيانات المظللة.")
    else:
        form = JobApplicationForm()
    return render(request, "hr/job_application_form.html", {"form": form})


def job_application_success(request):
    return render(request, "hr/job_application_success.html")


@login_required
@require_http_methods(["GET", "POST"])
def employee_education_update(request, employee_id):
    employee = get_object_or_404(Employee, pk=employee_id)
    if request.method == "POST":
        form = EmployeeEducationForm(request.POST, request.FILES, instance=employee)
        extra_files = request.FILES.getlist("extra_files")
        titles = request.POST.getlist("extra_titles")
        dates = request.POST.getlist("extra_dates")
        if form.is_valid():
            form.save()
            for idx, f in enumerate(extra_files):
                title = (titles[idx] if idx < len(titles) else "مؤهل إضافي") or "مؤهل إضافي"
                date = (dates[idx] if idx < len(dates) else None) or None
                aq = AdditionalQualification(employee=employee, title=title, file=f)
                if date:
                    try:
                        aq.issued_at = date
                    except Exception:
                        pass
                aq.save()
            messages.success(request, "تم تحديث بيانات المؤهل والمرفقات بنجاح.")
            return redirect("employee_education_update", employee_id=employee.id)
    else:
        form = EmployeeEducationForm(instance=employee)
    extras = employee.extra_quals.all()
    return render(request, "hr/employee_education_form.html", {"form": form, "employee": employee, "extras": extras})


@login_required
@require_http_methods(["GET", "POST"])
def contract_create(request):
    if request.method == "POST":
        form = ContractForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء/رفع العقد بنجاح.")
            return redirect("contract_create")
    else:
        form = ContractForm()
    return render(request, "hr/contract_form.html", {"form": form})


@login_required
@require_http_methods(["GET"])
def contract_sign(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    return render(request, "hr/contract_sign.html", {"contract": contract})


@login_required
@require_http_methods(["POST"])
def contract_sign_submit(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    data_url = request.POST.get("signature_data")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return JsonResponse({"ok": False, "detail": "صيغة التوقيع غير صالحة."}, status=400)

    b64 = data_url.split(',', 1)[1]
    raw = base64.b64decode(b64)
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    sig_name = f"signature_{contract.pk}_{ts}.png"
    sig_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signatures")
    os.makedirs(sig_dir, exist_ok=True)
    sig_path = os.path.join(sig_dir, sig_name)
    with open(sig_path, "wb") as f:
        f.write(raw)

    with open(sig_path, "rb") as f:
        contract.signature_image.save(sig_name, File(f), save=False)

    contract.mark_signed()

    html_str = render_to_string("hr/contract_pdf_template.html", {
        "contract": contract,
        "signed_at": contract.signed_at,
        "signature_url": contract.signature_image.url,
        "company_name": "شركة سنام للأمن",
    })

    pdf_name = f"contract_{contract.pk}_signed_{ts}.pdf"
    pdf_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signed")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_name)

    HTML(string=html_str, base_url=request.build_absolute_uri('/')).write_pdf(pdf_path, stylesheets=[
        CSS(string='@page { size: A4; margin: 20mm; } body { font-family: "Tajawal", Arial, sans-serif; }')
    ])

    with open(pdf_path, "rb") as f:
        contract.signed_pdf.save(pdf_name, File(f), save=False)
    contract.save(update_fields=["signature_image", "signed_pdf"])

    messages.success(request, "تم توقيع العقد وتوليد نسخة PDF بنجاح.")
    return JsonResponse({"ok": True, "pdf_url": contract.signed_pdf.url})



def _validate_token_or_403(contract: Contract, token: str):
    if not contract.sign_token or not token or token != contract.sign_token:
        return False
    if contract.sign_token_expires_at and timezone.now() > contract.sign_token_expires_at:
        return False
    if contract.signed_by_employee:
        # تم التوقيع مسبقًا – امنع إعادة الاستخدام
        return False
    return True

@require_http_methods(["GET"])
def contract_sign_public(request, pk, token):
    contract = get_object_or_404(Contract, pk=pk)
    if not _validate_token_or_403(contract, token):
        return HttpResponseForbidden("الرابط غير صالح أو منتهي الصلاحية.")
    # نفس القالب المستخدم مع تسجيل الدخول:
    return render(request, "hr/contract_sign.html", {"contract": contract, "public_token": token, "is_public": True})

@csrf_exempt   # لأننا لا نعتمد جلسة/CSRF هنا، سنعتمد على التوكن والمهلة
@require_http_methods(["POST"])
def contract_sign_public_submit(request, pk, token):
    contract = get_object_or_404(Contract, pk=pk)
    if not _validate_token_or_403(contract, token):
        return JsonResponse({"ok": False, "detail": "الرابط غير صالح أو منتهي."}, status=403)

    data_url = request.POST.get("signature_data")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return JsonResponse({"ok": False, "detail": "صيغة التوقيع غير صالحة."}, status=400)

    # حفظ صورة التوقيع
    b64 = data_url.split(",", 1)[1]
    raw = base64.b64decode(b64)
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    sig_name = f"signature_{contract.pk}_{ts}.png"
    sig_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signatures")
    os.makedirs(sig_dir, exist_ok=True)
    sig_path = os.path.join(sig_dir, sig_name)
    with open(sig_path, "wb") as f:
        f.write(raw)
    with open(sig_path, "rb") as f:
        contract.signature_image.save(sig_name, File(f), save=False)

    # علّم العقد موقّع + أبطل الرابط العام حتى لا يُستخدم مجددًا
    contract.mark_signed()
    contract.sign_token = None
    contract.sign_token_expires_at = None

    # توليد PDF
    html_str = render_to_string("hr/contract_pdf_template.html", {
        "contract": contract,
        "signed_at": contract.signed_at,
        "signature_url": contract.signature_image.url,
        "company_name": "شركة سنام للأمن",
    })
    pdf_name = f"contract_{contract.pk}_signed_{ts}.pdf"
    pdf_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signed")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_name)
    HTML(string=html_str, base_url=request.build_absolute_uri('/')).write_pdf(
        pdf_path,
        stylesheets=[CSS(string='@page { size: A4; margin: 20mm; } body { font-family: "Tajawal", Arial, sans-serif; }')]
    )
    with open(pdf_path, "rb") as f:
        contract.signed_pdf.save(pdf_name, File(f), save=False)
    contract.save(update_fields=["signature_image", "signed_pdf", "sign_token", "sign_token_expires_at"])

    return JsonResponse({"ok": True, "pdf_url": contract.signed_pdf.url})
