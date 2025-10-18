import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings
from .utils.current import get_current_user

UserModel = settings.AUTH_USER_MODEL


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    class Meta: abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self, hard: bool = False):
        if hard:
            return super().delete()
        now = timezone.now()
        return super().update(is_deleted=True, deleted_at=now)

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db).all()

    def only_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db).dead()


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(UserModel, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="deleted_%(class)ss", verbose_name="تم الحذف بواسطة")

    objects = SoftDeleteManager()
    all_objects = SoftDeleteQuerySet.as_manager()

    def soft_delete(self, when=None, by=None, save=True):
        if not self.is_deleted:
            self.is_deleted = True
            self.deleted_at = when or timezone.now()
            by_user = by if by is not None else get_current_user()
            if by_user is not None and getattr(by_user, "is_authenticated", False):
                self.deleted_by = by_user
            if save:
                self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    # Backward-compatible delete override
    def delete(self, using=None, keep_parents=False, hard: bool = False):
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.soft_delete(save=True)

    def restore(self, save=True):
        if self.is_deleted:
            self.is_deleted = False
            self.deleted_at = None
            self.deleted_by = None
            if save:
                self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    class Meta: abstract = True


class BlameableModel(models.Model):
    created_by = models.ForeignKey(UserModel, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="created_%(class)ss", verbose_name="أُنشئ بواسطة")
    updated_by = models.ForeignKey(UserModel, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="updated_%(class)ss", verbose_name="عُدّل بواسطة")
    class Meta: abstract = True
    def _auto_set_blame_fields(self, is_new: bool):
        u = get_current_user()
        if u is not None and getattr(u, "is_authenticated", False):
            if is_new and getattr(self, 'created_by_id', None) is None:
                self.created_by = u
            self.updated_by = u
    def save(self, *a, **k):
        self._auto_set_blame_fields(self._state.adding)
        super().save(*a, **k)


class UUIDPrimaryKeyModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class Meta: abstract = True


class BaseModel(UUIDPrimaryKeyModel, TimeStampedModel, SoftDeleteModel, BlameableModel):
    class Meta: abstract = True
