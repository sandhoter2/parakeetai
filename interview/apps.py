from django.apps import AppConfig


class InterviewConfig(AppConfig):
    name = "interview"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.conf import settings
        if not getattr(settings, "MYSQL_BACKUP_ENABLED", False):
            return
        # Run MySQL→SQLite restore on startup in a background thread
        # so it doesn't block the server from starting
        import threading
        def _startup_restore():
            import time
            time.sleep(2)  # wait for DB migrations to settle
            try:
                from interview.db_sync import restore_from_mysql
                count, err = restore_from_mysql(triggered_by="startup")
                if err:
                    import logging
                    logging.getLogger(__name__).warning("Startup MySQL restore failed: %s", err)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error("Startup MySQL restore error: %s", e)

        t = threading.Thread(target=_startup_restore, daemon=True)
        t.start()
