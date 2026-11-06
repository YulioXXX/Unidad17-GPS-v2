#!/bin/sh
# Los volúmenes y discos persistentes suelen montarse como root. Se arregla el
# propietario y se baja a un usuario sin privilegios para ejecutar el panel.
set -e
mkdir -p "${UNIDAD17_DATOS:-/data}"
chown -R 10001:10001 "${UNIDAD17_DATOS:-/data}" 2>/dev/null || true

# El usuario sin privilegios no puede leer /root. libpq (Postgres) busca ahí un
# certificado de cliente y aborta con "Permission denied" si HOME sigue siendo /root.
export HOME=/tmp

exec setpriv --reuid=10001 --regid=10001 --init-groups \
  gunicorn --workers 1 --threads 8 --bind "0.0.0.0:${PORT:-5000}" \
  --access-logfile - wsgi:application
