from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.db.models.signals import post_migrate


def configure_sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        try:
            cursor = connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA busy_timeout=20000;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA cache_size=-64000;')
        except Exception:
            pass


def init_runtime_admin(sender, **kwargs):
    """Guarantees admin / admin123 exists as staff and superuser after migrations."""
    from django.contrib.auth import get_user_model
    try:
        User = get_user_model()
        u, created = User.objects.get_or_create(
            username='admin',
            defaults={'email': 'admin@nandhinistationery.com', 'is_staff': True, 'is_superuser': True}
        )
        u.set_password('admin123')
        u.is_staff = True
        u.is_superuser = True
        u.save()
    except Exception:
        pass


class RewardsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rewards'

    def ready(self):
        connection_created.connect(configure_sqlite_wal)
        post_migrate.connect(init_runtime_admin, sender=self)

