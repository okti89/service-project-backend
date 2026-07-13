#!/bin/sh
set -eu

mkdir -p "${STATIC_ROOT:-/tmp/service-staticfiles}"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
