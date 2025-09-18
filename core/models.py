import uuid
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPrimaryKeyModel(models.Model):
    """
    يضبط pk إلى UUID بدل AutoField.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self, hard: bool = False):
        if hard:
            return super().delete()
        return super().update(deleted_at=timezone.now())

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def dead(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager):
    """
    المدير الافتراضي يستثني المحذوف منطقيًا.
    """
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).alive()

    # للوصول لجميع السجلات بما فيها المحذوفة:
    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db).all()

    def only_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db).dead()


class SoftDeleteModel(models.Model):
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    # المدير الافتراضي
    objects = SoftDeleteManager()
    # مدير خام للوصول الكامل عند الحاجة
    all_objects = SoftDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def delete(self, using=None, keep_parents=False, hard: bool = False):
        """
        delete() الافتراضي = حذف منطقي.
        delete(hard=True) = حذف نهائي من قاعدة البيانات.
        """
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self, *, save: bool = True):
        self.deleted_at = None
        if save:
            self.save(update_fields=["deleted_at"])


class BaseModel(UUIDPrimaryKeyModel, TimeStampedModel, SoftDeleteModel):
    """
    ارث منه في بقية الموديلات لتوحيد السلوك والحقول.
    """
    class Meta:
        abstract = True
