import os
from django.apps import AppConfig


class InterviewConfig(AppConfig):
    name = 'interview'

    def ready(self):
        if os.environ.get('MONGODB_URI'):
            # django-mongodb-backend doesn't assign ObjectId PKs after bulk_create,
            # so Django's create_permissions post_migrate signal crashes trying to
            # hash ContentType instances with no PK. Disconnect it — basic auth
            # (login/logout/sessions) doesn't require the Permission table to be
            # populated.
            try:
                from django.contrib.auth.management import create_permissions
                from django.db.models.signals import post_migrate
                post_migrate.disconnect(
                    create_permissions,
                    dispatch_uid="django.contrib.auth.management.create_permissions",
                )
            except Exception:
                pass
