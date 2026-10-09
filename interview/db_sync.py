"""
MySQL ↔ SQLite sync utilities.

Strategy: serialize all Django app data to JSON (using Django's built-in
serializers), then store/retrieve that blob in a single MySQL table.
This keeps the sync simple and schema-independent.
"""
import json
import logging
from datetime import datetime, timezone

from django.conf import settings
from django.core import serializers
from django.apps import apps

logger = logging.getLogger(__name__)

BACKUP_APPS = ["interview", "auth"]
EXCLUDE_MODELS = {"auth.permission", "contenttypes.contenttype"}

MYSQL_TABLE = "parakeet_backup"
MYSQL_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS `{MYSQL_TABLE}` (
    id INT NOT NULL DEFAULT 1,
    data LONGTEXT NOT NULL,
    records_count INT NOT NULL DEFAULT 0,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"""


def _get_mysql_connection():
    """Return a raw PyMySQL connection using MYSQL_BACKUP_CONFIG from settings."""
    import pymysql
    cfg = settings.MYSQL_BACKUP_CONFIG
    if not cfg.get("host"):
        raise RuntimeError("MYSQL_HOST env var is not set")
    return pymysql.connect(
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        user=cfg["user"],
        password=cfg["password"],
        charset="utf8mb4",
        connect_timeout=10,
    )


def _serialize_all():
    """Dump all relevant Django objects to a JSON string."""
    objects = []
    for app_label in BACKUP_APPS:
        try:
            app_config = apps.get_app_config(app_label)
        except LookupError:
            continue
        for model in app_config.get_models():
            label = f"{app_label}.{model.__name__}".lower()
            if label in EXCLUDE_MODELS:
                continue
            try:
                objects.extend(model.objects.all())
            except Exception as e:
                logger.warning("Skipping %s during serialize: %s", model.__name__, e)

    return serializers.serialize(
        "json",
        objects,
        indent=None,
        use_natural_foreign_keys=True,
        use_natural_primary_keys=True,
    )


def backup_to_mysql(triggered_by="manual"):
    """Dump SQLite → MySQL. Returns (records_count, error_message)."""
    from .models import DbSyncLog

    log = DbSyncLog.objects.create(direction="backup", status="running", triggered_by=triggered_by)
    try:
        data = _serialize_all()
        records = len(json.loads(data))

        conn = _get_mysql_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(MYSQL_CREATE_SQL)
                cur.execute(
                    f"INSERT INTO `{MYSQL_TABLE}` (id, data, records_count, updated_at) VALUES (1, %s, %s, %s) "
                    f"ON DUPLICATE KEY UPDATE data=%s, records_count=%s, updated_at=%s",
                    (data, records, datetime.now(timezone.utc), data, records, datetime.now(timezone.utc)),
                )
            conn.commit()
        finally:
            conn.close()

        log.status = "success"
        log.records_count = records
        log.finished_at = datetime.now(timezone.utc)
        log.save()
        logger.info("MySQL backup done: %d records", records)
        return records, ""

    except Exception as e:
        log.status = "error"
        log.error_message = str(e)
        log.finished_at = datetime.now(timezone.utc)
        log.save()
        logger.error("MySQL backup failed: %s", e)
        return 0, str(e)


def restore_from_mysql(triggered_by="manual"):
    """Fetch MySQL backup → load into SQLite. Returns (records_count, error_message)."""
    from .models import DbSyncLog
    from django.core.management import call_command
    import io

    log = DbSyncLog.objects.create(direction="restore", status="running", triggered_by=triggered_by)
    try:
        conn = _get_mysql_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT data, records_count FROM `{MYSQL_TABLE}` WHERE id=1")
                row = cur.fetchone()
        finally:
            conn.close()

        if not row:
            raise RuntimeError("No backup found in MySQL — nothing to restore")

        data, records = row
        # Load fixtures into SQLite using Django's loaddata mechanism
        # We write to a temp file and call loaddata
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
            tf.write(data)
            tmp_path = tf.name

        try:
            call_command("loaddata", tmp_path, verbosity=0)
        finally:
            os.unlink(tmp_path)

        log.status = "success"
        log.records_count = records
        log.finished_at = datetime.now(timezone.utc)
        log.save()
        logger.info("MySQL restore done: %d records", records)
        return records, ""

    except Exception as e:
        log.status = "error"
        log.error_message = str(e)
        log.finished_at = datetime.now(timezone.utc)
        log.save()
        logger.error("MySQL restore failed: %s", e)
        return 0, str(e)
