from __future__ import annotations

from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from api_guard.models import BankAccount, BankChangeRequest, Employee, User


def create_or_replace_pending_request(*, employee: Employee, payload: dict) -> BankChangeRequest:
    with transaction.atomic():
        req = BankChangeRequest.objects.filter(employee=employee, status='pending').first()
        # snapshot current
        acc = getattr(employee, 'bank_account_rec', None)
        snap_bank = getattr(acc, 'bank_name', None) if acc else getattr(employee, 'bank_name', None)
        snap_iban = getattr(acc, 'iban', None) if acc else getattr(employee, 'bank_account', None)
        base = {
            'current_bank_name': snap_bank,
            'current_iban': snap_iban,
            'requested_bank_name': payload.get('requested_bank_name') or payload.get('bank_name'),
            'requested_iban': payload.get('requested_iban') or payload.get('iban'),
            'requested_account_holder': payload.get('requested_account_holder') or payload.get('account_holder'),
            'requested_swift_bic': payload.get('requested_swift_bic') or payload.get('swift_bic'),
            'requested_branch_name': payload.get('requested_branch_name') or payload.get('branch_name'),
            'note_from_employee': payload.get('note_from_employee') or payload.get('note'),
            'status': 'pending',
        }
        if req:
            for k, v in base.items():
                setattr(req, k, v)
            req.full_clean()
            req.save()
            return req
        req = BankChangeRequest(employee=employee, **base)
        req.full_clean()
        req.save()
        return req


def approve_bank_change(*, request_id, reviewer: User, comment: str | None = None) -> BankChangeRequest:
    with transaction.atomic():
        req = BankChangeRequest.objects.select_for_update().get(pk=request_id)
        if req.status != 'pending':
            raise ValidationError({'status': 'الطلب ليس قيد المراجعة'})
        # upsert BankAccount
        acc, _ = BankAccount.objects.get_or_create(employee=req.employee)
        acc.bank_name = req.requested_bank_name
        acc.iban = req.requested_iban
        acc.account_holder = req.requested_account_holder
        acc.swift_bic = req.requested_swift_bic
        acc.branch_name = req.requested_branch_name
        acc.save()

        # تحديث حقول Employee الأساسية للتوافق الخلفي
        try:
            emp = req.employee
            if hasattr(emp, 'bank_name'):
                emp.bank_name = req.requested_bank_name
            if hasattr(emp, 'bank_account'):
                emp.bank_account = req.requested_iban
            emp.save(update_fields=[f for f in ['bank_name', 'bank_account'] if f in [f.name for f in emp._meta.get_fields()]])
        except Exception:
            pass

        req.status = 'approved'
        req.hr_reviewer = reviewer
        req.hr_comment = (comment or '').strip() or req.hr_comment
        req.decided_at = timezone.now()
        req.save(update_fields=['status', 'hr_reviewer', 'hr_comment', 'decided_at'])
        return req


def reject_bank_change(*, request_id, reviewer: User, comment: str | None = None) -> BankChangeRequest:
    with transaction.atomic():
        req = BankChangeRequest.objects.select_for_update().get(pk=request_id)
        if req.status != 'pending':
            raise ValidationError({'status': 'الطلب ليس قيد المراجعة'})
        req.status = 'rejected'
        req.hr_reviewer = reviewer
        req.hr_comment = (comment or '').strip() or req.hr_comment
        req.decided_at = timezone.now()
        req.save(update_fields=['status', 'hr_reviewer', 'hr_comment', 'decided_at'])
        return req
