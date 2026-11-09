"""
WSGI config for nandhini_stationery project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nandhini_stationery.settings')

application = get_wsgi_application()

# Auto-initialize database schema and store admin on runtime container startup
try:
    from django.core.management import call_command
    call_command('migrate', interactive=False)

    from django.contrib.auth import get_user_model
    User = get_user_model()
    admin_user, _ = User.objects.get_or_create(
        username='admin',
        defaults={'email': 'admin@nandhinistationery.com', 'is_staff': True, 'is_superuser': True}
    )
    admin_user.is_staff = True
    admin_user.is_superuser = True
    admin_user.is_active = True
    admin_user.set_password('admin123')
    admin_user.save()
    print("✓ WSGI STARTUP: SQLite database migrated and admin superuser verified (admin/admin123)")
except Exception as _startup_exc:
    print(f"WSGI STARTUP NOTICE: {_startup_exc}")

