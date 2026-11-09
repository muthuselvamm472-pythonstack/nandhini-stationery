"""
WSGI config for nandhini_stationery project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path for Vercel Serverless module resolution
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nandhini_stationery.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()

# Vercel Serverless Handler
app = application
