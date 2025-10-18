from __future__ import annotations

import uuid
from typing import Dict, List, Tuple

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection, models, transaction


class Command(BaseCommand):
    help = "Scan all models with UUID PKs and fix rows having invalid/non-UUID primary keys; also updates referencing FKs and M2M through tables."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Only report, do not modify the database.",
        )

    def handle(self, *args, **options):
        dry = options.get("dry_run", False)
        total_updates: List[Tuple[str, int]] = []

        # Build model list with UUID PK
        models_with_uuid_pk = [
            m for m in apps.get_models() if isinstance(m._meta.pk, models.UUIDField)
        ]

        # Pre-compute reverse FK & M2M relationships
        reverse_fk: Dict[models.Model, List[Tuple[models.Model, models.ForeignKey]]] = {}
        reverse_m2m: Dict[models.Model, List[Tuple[models.Model, models.Model]]] = {}

        all_models = list(apps.get_models())
        for src in all_models:
            # FKs that point to target model
            for f in src._meta.get_fields():
                if isinstance(f, models.ForeignKey):
                    tgt = f.remote_field.model
                    reverse_fk.setdefault(tgt, []).append((src, f))
                # M2M through tables
                if isinstance(f, models.ManyToManyField):
                    through = f.remote_field.through
                    # Identify the target model on the M2M side
                    tgt = f.remote_field.model
                    reverse_m2m.setdefault(tgt, []).append((through, src))

        with connection.cursor() as cursor:
            # Disable FK checks for SQLite to allow staged updates
            vendor = connection.vendor
            fk_disabled = False
            try:
                if vendor == "sqlite":
                    cursor.execute("PRAGMA foreign_keys")
                    row = cursor.fetchone()
                    if row and row[0] == 1:
                        fk_disabled = True
                        cursor.execute("PRAGMA foreign_keys=OFF")
            except Exception:
                pass

        for model in models_with_uuid_pk:
            table = model._meta.db_table
            pk_col = model._meta.pk.column
            updates: Dict[str, str] = {}

            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {pk_col} FROM {table}")
                rows = cursor.fetchall()
                for (old_id,) in rows:
                    if old_id is None:
                        continue
                    try:
                        uuid.UUID(str(old_id))
                    except Exception:
                        new_id = str(uuid.uuid4())
                        updates[str(old_id)] = new_id

            if not updates:
                continue

            self.stdout.write(self.style.WARNING(f"{table}: {len(updates)} invalid UUID(s) detected"))

            if dry:
                total_updates.append((table, len(updates)))
                continue

            # Apply updates inside a transaction to keep consistency
            with transaction.atomic():
                with connection.cursor() as cursor:
                    # Update referencing FKs first to avoid dangling refs
                    for (src_model, fk_field) in reverse_fk.get(model, []):
                        src_table = src_model._meta.db_table
                        col = fk_field.column
                        for old, new in updates.items():
                            try:
                                cursor.execute(
                                    f"UPDATE {src_table} SET {col}=%s WHERE {col}=%s",
                                    [new, old],
                                )
                            except Exception:
                                # Best-effort; continue
                                pass

                    # Update M2M through tables
                    for (through_model, src_model) in reverse_m2m.get(model, []):
                        t_table = through_model._meta.db_table
                        # Find the FK column on the through table that points to our target model
                        tgt_fk_cols = []
                        for f in through_model._meta.get_fields():
                            if isinstance(f, models.ForeignKey) and f.remote_field.model == model:
                                tgt_fk_cols.append(f.column)
                        for col in tgt_fk_cols:
                            for old, new in updates.items():
                                try:
                                    cursor.execute(
                                        f"UPDATE {t_table} SET {col}=%s WHERE {col}=%s",
                                        [new, old],
                                    )
                                except Exception:
                                    pass

                    # Finally, update the PK values in the base table
                    for old, new in updates.items():
                        cursor.execute(
                            f"UPDATE {table} SET {pk_col}=%s WHERE {pk_col}=%s",
                            [new, old],
                        )

            total_updates.append((table, len(updates)))

        # Re-enable SQLite FK checks if we disabled them
        with connection.cursor() as cursor:
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            except Exception:
                pass

        if not total_updates:
            self.stdout.write(self.style.SUCCESS("No invalid UUIDs found."))
        else:
            for table, cnt in total_updates:
                self.stdout.write(self.style.SUCCESS(f"Fixed {cnt} rows in {table}"))

