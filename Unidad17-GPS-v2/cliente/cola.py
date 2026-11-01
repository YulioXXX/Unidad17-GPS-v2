# -*- coding: utf-8 -*-
"""Cola local de reportes para no perder ubicaciones si el servidor no responde."""
from __future__ import annotations

import json
import os
import threading


class Cola:
    def __init__(self, ruta: str, maximo: int = 5000):
        self.ruta = ruta
        self.maximo = max(50, int(maximo))
        self._bloqueo = threading.Lock()
        os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)

    # ------------------------------------------------------------------
    def _leer_lineas(self) -> list[str]:
        if not os.path.exists(self.ruta):
            return []
        try:
            with open(self.ruta, "r", encoding="utf-8") as archivo:
                return [linea for linea in archivo if linea.strip()]
        except OSError:
            return []

    def tamano(self) -> int:
        with self._bloqueo:
            return len(self._leer_lineas())

    # ------------------------------------------------------------------
    def agregar(self, datos: dict) -> bool:
        with self._bloqueo:
            lineas = self._leer_lineas()
            if len(lineas) >= self.maximo:
                return False
            try:
                with open(self.ruta, "a", encoding="utf-8") as archivo:
                    archivo.write(json.dumps(datos, ensure_ascii=False) + "\n")
                return True
            except OSError:
                return False

    def pendientes(self, limite: int = 20) -> list[dict]:
        with self._bloqueo:
            salida = []
            for linea in self._leer_lineas()[:max(1, limite)]:
                try:
                    dato = json.loads(linea)
                except ValueError:
                    continue
                if isinstance(dato, dict):
                    salida.append(dato)
            return salida

    def quitar(self, cantidad: int) -> None:
        if cantidad <= 0:
            return
        with self._bloqueo:
            lineas = self._leer_lineas()
            resto = lineas[cantidad:]
            try:
                temporal = self.ruta + ".tmp"
                with open(temporal, "w", encoding="utf-8") as archivo:
                    archivo.writelines(resto)
                os.replace(temporal, self.ruta)
            except OSError:
                pass
