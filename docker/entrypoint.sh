#!/bin/sh
set -eu

mkdir -p /app/staticfiles

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
