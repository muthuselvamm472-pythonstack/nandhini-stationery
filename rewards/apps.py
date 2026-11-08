from django.apps import AppConfig
from django.db.backends.signals import connection_created


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


class RewardsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rewards'

    def ready(self):
        connection_created.connect(configure_sqlite_wal)
