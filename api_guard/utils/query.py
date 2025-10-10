"""
Queryset optimization utilities: safe select_related/prefetch_related,
and a mixin to apply them to generic list views without breaking behavior.
"""
from typing import Iterable
from django.core.exceptions import FieldError

CANDIDATE_SELECT = (
    "user","guard","shift","location","created_by","updated_by",
    "assigned_by","assigned_to","task","report","request","company","client",
)
CANDIDATE_PREFETCH = (
    "items","attachments","comments","histories","logs","notes","uniform_items",
)

def safe_select_related(qs, fields: Iterable[str] = CANDIDATE_SELECT):
    for f in fields:
        try:
            qs = qs.select_related(f)
        except Exception:
            # Field doesn't exist or not suitable for select_related
            pass
    return qs

def safe_prefetch_related(qs, fields: Iterable[str] = CANDIDATE_PREFETCH):
    for f in fields:
        try:
            qs = qs.prefetch_related(f)
        except Exception:
            pass
    return qs

class OptimizedQuerysetMixin:
    """
    Drop-in mixin for DRF generic views.
    Applies safe select_related/prefetch_related to self.get_queryset().
    """
    select_fields = CANDIDATE_SELECT
    prefetch_fields = CANDIDATE_PREFETCH

    def get_queryset(self):
        qs = super().get_queryset()
        qs = safe_select_related(qs, self.select_fields)
        qs = safe_prefetch_related(qs, self.prefetch_fields)
        return qs
