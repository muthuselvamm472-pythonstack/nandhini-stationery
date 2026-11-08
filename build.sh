#!/usr/bin/env bash
# Exit on error
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Automatically ensure superuser admin exists for store owner
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
u, created = User.objects.get_or_create(username='admin', defaults={'email': 'admin@nandhinistationery.com', 'is_staff': True, 'is_superuser': True})
if created or not u.is_staff or not u.is_superuser:
    u.set_password('admin123')
    u.is_staff = True
    u.is_superuser = True
    u.save()
    print('Superuser admin seeded with credentials')
else:
    print('Superuser admin already active')
"

