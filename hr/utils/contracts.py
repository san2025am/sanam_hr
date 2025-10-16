from datetime import date, timedelta
from django.conf import settings
from django.urls import reverse
from django.core.mail import send_mail

CONTRACT_BODY_TEMPLATE = """
عقد عمل لمدة سنة – حارس أمن

الطرف الأول (الشركة): شركة سنام للأمن.
الطرف الثاني (الموظف): {{ employee_name }}، رقم الهوية: {{ national_id }}، رقم الجوال: {{ phone }}.

1) موضوع العقد والوظيفة
يوظَّف الطرف الثاني بوظيفة حارس أمن ...

2) مدة العقد وبدايته
تبدأ من: {{ start_date }} وتنتهي في: {{ end_date }} (سنة كاملة). يتجدد تلقائيًا ما لم يُخطر أحد الطرفين قبل 30 يومًا.

... (أكمل نص العقد الكامل الذي زوّدتك به سابقًا) ...
"""

def one_year_period(start=None):
    start = start or date.today()
    # نهاية سنة ناقص يوم (مثلاً من 2025-01-01 إلى 2025-12-31)
    end = start.replace(year=start.year + 1) - timedelta(days=1)
    return start, end

def render_contract_body(employee):
    body = CONTRACT_BODY_TEMPLATE
    body = body.replace("{{ employee_name }}", employee.full_name)
    body = body.replace("{{ national_id }}", employee.national_id or "")
    body = body.replace("{{ phone }}", employee.phone or "")
    s, e = one_year_period()
    body = body.replace("{{ start_date }}", s.isoformat())
    body = body.replace("{{ end_date }}", e.isoformat())
    return body

def build_public_sign_url(contract):
    path = reverse("contract_sign_public", args=[contract.pk, contract.sign_token])
    base = getattr(settings, "SITE_URL", "")
    return f"{base}{path}"

def send_contract_email(to_email, employee_name, link):
    subj = "عقد عملك لدى سنام الأمن — رابط التوقيع"
    txt = f"""مرحبًا {employee_name},

تم إنشاء عقد عملك. الرجاء قراءة العقد وتوقيعه عبر الرابط التالي:
{link}

ملاحظة: الرابط موقّت وقد ينتهي بعد 72 ساعة، أو بعد التوقيع مباشرة.
"""
    send_mail(subject=subj, message=txt, from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
              recipient_list=[to_email], fail_silently=False)
