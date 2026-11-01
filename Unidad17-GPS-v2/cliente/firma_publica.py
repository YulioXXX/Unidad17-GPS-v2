# -*- coding: utf-8 -*-
"""Clave pública con la que el agente verifica las actualizaciones.

Pega aquí (antes de compilar el .exe) el contenido de ``firma_publica.txt``,
generado con ``herramientas/firmar_paquete.py claves``. Son 64 caracteres
hexadecimales y NO son secretos.

Si la dejas vacía, el agente la busca en ``config.json`` (``clave_publica_firma``).
Sin clave en ningún sitio el agente NO se actualiza solo, salvo que pongas
``"permitir_sin_firma": true`` en config.json (no recomendado).
"""

CLAVE_PUBLICA_HEX = ""
