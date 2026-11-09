#!/usr/bin/env bash
set -e

echo "==> Running database migrations..."
python manage.py migrate --no-input

echo "==> Ensuring admin superuser exists..."
python manage.py shell -c "
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
    print('SUCCESS: Superuser admin verified and password set to admin123')
except Exception as e:
    print('Superuser setup notice:', e)
"

echo "==> Starting Gunicorn application server..."
exec gunicorn nandhini_stationery.wsgi:application --bind 0.0.0.0:${PORT:-8000}

