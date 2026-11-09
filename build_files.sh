#!/usr/bin/env bash
echo "==> Installing dependencies..."
python3 -m pip install -r requirements.txt

echo "==> Running migrations..."
python3 manage.py migrate --no-input

echo "==> Collecting static files..."
python3 manage.py collectstatic --no-input --clear

