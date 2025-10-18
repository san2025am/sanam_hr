from django.apps import AppConfig


def _ensure_default_groups(sender=None, **kwargs):
    """Create default functional groups if they don't exist."""
    try:
        from django.contrib.auth.models import Group
        for name in ("HR", "Finance", "Operations", "Logistics"):
            Group.objects.get_or_create(name=name)
    except Exception:
        # Avoid import-time or migration-order issues silently
        pass


def _grant_functional_permissions(sender=None, **kwargs):
    """
    Auto-grant model permissions to functional groups (HR/Finance/Operations/Logistics)
    based on the functional registries. Safe and idempotent.
    """
    try:
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType
        from django.apps import apps
        # Import lazily to avoid circular imports at load time
        from sanam_project.functional_registry import (
            HR_MODELS, FINANCE_MODELS, OPS_MODELS, LOGISTICS_MODELS,
        )

        mapping = {
            'HR': HR_MODELS,
            'Finance': FINANCE_MODELS,
            'Operations': OPS_MODELS,
            'Logistics': LOGISTICS_MODELS,
        }

        for group_name, labels in mapping.items():
            try:
                group, _ = Group.objects.get_or_create(name=group_name)
            except Exception:
                continue
            for label in labels:
                try:
                    app_label, model_name = label.split('.')
                    model = apps.get_model(app_label, model_name)
                    ct = ContentType.objects.get_for_model(model)
                    for op in ("view", "add", "change", "delete"):
                        code = f"{op}_{model._meta.model_name}"
                        try:
                            perm = Permission.objects.get(content_type=ct, codename=code)
                            group.permissions.add(perm)
                        except Permission.DoesNotExist:
                            # Permission may not exist yet for some proxy/abstract models
                            pass
                except Exception:
                    # Skip bad labels or models that aren't loaded
                    continue
    except Exception:
        # Never block migrations due to permission grant helper
        pass

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Ensure default groups are created after migrations
        try:
            from django.db.models.signals import post_migrate
            post_migrate.connect(_ensure_default_groups, dispatch_uid="core.ensure_default_groups")
            post_migrate.connect(_grant_functional_permissions, dispatch_uid="core.grant_functional_permissions")
        except Exception:
            # If signals can't be connected yet, ignore; next process will handle it
            pass
