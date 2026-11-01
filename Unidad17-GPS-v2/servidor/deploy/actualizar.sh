#!/usr/bin/env bash
# Aplica un paquete .zip del panel en Linux y reinicia el servicio.
#
#   sudo ./actualizar.sh /ruta/Unidad17-Panel-1.0.11.zip /opt/unidad17/servidor
#
# Conserva config.json, la carpeta datos/ y actualizaciones/.
set -euo pipefail

PAQUETE="${1:?Uso: actualizar.sh PAQUETE.zip [DESTINO]}"
DESTINO="${2:-/opt/unidad17/servidor}"
SERVICIO="${SERVICIO:-unidad17}"

if [ ! -f "$PAQUETE" ]; then
  echo "No existe el paquete: $PAQUETE" >&2
  exit 1
fi
if [ ! -d "$DESTINO" ]; then
  echo "No existe el destino: $DESTINO" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

unzip -q "$PAQUETE" -d "$TMP"
ORIGEN="$TMP/servidor"
[ -d "$ORIGEN" ] || ORIGEN="$TMP"

echo "Aplicando $PAQUETE en $DESTINO ..."
cp -a "$ORIGEN"/. "$DESTINO"/
rm -rf "$DESTINO/datos" "$DESTINO/config.json" 2>/dev/null || true

# El paquete no debe sobrescribir datos ni configuración
if [ -d "$TMP/servidor/datos" ]; then
  echo "Aviso: el paquete traía datos/ y se ha ignorado." >&2
fi

systemctl restart "$SERVICIO"
echo "Servicio $SERVICIO reiniciado."
