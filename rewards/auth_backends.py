import logging
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.core.management import call_command

logger = logging.getLogger(__name__)


class AdminFallbackAuthBackend(ModelBackend):
    """
    Guarantees the store owner can ALWAYS log in with admin/admin123
    even if the ephemeral cloud database (e.g. Render SQLite) was wiped,
    reset, or never seeded with a superuser.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username == 'admin' and password == 'admin123':
            User = get_user_model()
            try:
                user = self._ensure_admin_user(User)
                if user:
                    return user
            except Exception as e:
                logger.warning(f"Initial admin lookup failed, attempting migration: {e}")
                try:
                    call_command('migrate', interactive=False)
                    user = self._ensure_admin_user(User)
                    if user:
                        return user
                except Exception as inner_e:
                    logger.error(f"Fallback migration during admin auth failed: {inner_e}")
                    return None

        # Fall back to standard Django username/password check
        return super().authenticate(request, username=username, password=password, **kwargs)

    def _ensure_admin_user(self, User):
        user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@nandhinistationery.com',
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            }
        )
        needs_save = False
        if not user.is_staff or not user.is_superuser or not user.is_active:
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            needs_save = True

        if not user.check_password('admin123'):
            user.set_password('admin123')
            needs_save = True

        if needs_save:
            user.save()

        return user
