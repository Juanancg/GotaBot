"""
Cliente para la API REST oculta de EMI Telegestión (https://apioficinavirtual.emitelegestion.es).

Aunque la web https://oficinavirtual.emitelegestion.es/dashboard parece requerir scraping con navegador,
por debajo es una SPA en Angular que se comunica con un backend Laravel OAuth2 en:
https://apioficinavirtual.emitelegestion.es
"""

import json
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


@dataclass
class MeterReading:
    date: str               # YYYY-MM-DD
    timestamp: int          # Unix timestamp (UTC midnight)
    meter_value_m3: float   # Lectura acumulada del contador en m³
    daily_m3: float         # Consumo desde la lectura anterior en m³
    daily_liters: float     # Consumo desde la lectura anterior en Litros
    days_elapsed: int       # Días transcurridos desde la lectura anterior (normalmente 1)
    serial_number: str      # Número de serie del contador
    room: str               # Ubicación (ej. "Vivienda")


class EmiClient:
    BASE_URL = "https://apioficinavirtual.emitelegestion.es"
    # Credenciales OAuth2 públicas del cliente Angular extraídas del bundle main.js
    CLIENT_ID = "992c10fc-e3d6-4e85-b55b-3410e1f261b3"
    CLIENT_SECRET = "4MrqtaTgCXZ3btu5e0BOdB9lhwHme9xwughO3lGQ"

    def __init__(self, username: str, password: str, timeout: int = 20):
        self.username = username
        self.password = password
        self.timeout = timeout
        self.access_token: Optional[str] = None

    def _post(self, url: str, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GotaBot/1.0",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        if not self.access_token:
            self.login()

        url = f"{self.BASE_URL}/api/v1{path}"
        if params:
            query = urllib.parse.urlencode(params)
            url += ("&" if "?" in url else "?") + query

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GotaBot/1.0",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def login(self) -> str:
        """Obtiene el Bearer Token mediante OAuth2 Password Grant."""
        payload = {
            "grant_type": "password",
            "client_id": self.CLIENT_ID,
            "client_secret": self.CLIENT_SECRET,
            "scope": "*",
            "username": self.username,
            "password": self.password,
        }
        resp = self._post(f"{self.BASE_URL}/oauth/token", payload)
        self.access_token = resp["access_token"]
        return self.access_token

    def get_current_user(self) -> dict:
        """Devuelve la información del titular de la cuenta (/api/v1/me)."""
        return self._get("/me").get("data", {})

    def get_buildings(self) -> List[dict]:
        """Devuelve la lista de viviendas/inmuebles asociados (/api/v1/buildings)."""
        return self._get("/buildings").get("data", [])

    def get_latest_reading(self, building_id: int, service_id: int = 8) -> Optional[dict]:
        """Devuelve la última lectura disponible del contador."""
        resp = self._get(
            f"/building/{building_id}/readings/latest",
            params={"page": 1, "service": service_id},
        )
        data = resp.get("data", [])
        return data[0] if data else None

    def get_intervals(self, building_id: int, service_id: int = 8) -> Tuple[int, int]:
        """Devuelve (first_reading_ts, last_reading_ts) en segundos Unix."""
        resp = self._get(
            f"/building/{building_id}/consumptions/intervals",
            params={"service": service_id},
        )
        data = resp.get("data", {})
        return int(data["first_reading"]), int(data["last_reading"])

    def get_readings_page(
        self, building_id: int, page: int = 1, service_id: int = 8
    ) -> dict:
        """
        Consulta el endpoint oculto /api/v1/building/{id}/readings que devuelve
        las lecturas brutas registradas por la pasarela de telelectura (10 por página).
        """
        return self._get(
            f"/building/{building_id}/readings",
            params={"page": page, "service": service_id},
        )

    def get_daily_readings(
        self,
        building_id: int,
        days: int = 14,
        service_id: int = 8,
        cached_readings: Optional[Dict[str, dict]] = None,
    ) -> List[MeterReading]:
        """
        Obtiene el histórico de lecturas diarias de los últimos `days` días usando
        el endpoint directo `/building/{id}/readings` (que trae 10 lecturas por petición
        desde las últimas páginas), evitando hacer una petición por cada día.
        """
        if cached_readings is None:
            cached_readings = {}

        # Primero consultamos la última página para saber cuántas páginas existen y traer lo más nuevo
        first_resp = self.get_readings_page(building_id, page=1, service_id=service_id)
        meta = first_resp.get("meta", {})
        last_page = int(meta.get("last_page", 1))
        per_page = int(meta.get("per_page", 10))

        # Guardamos también lo que vino en la página 1 por si acaso
        for item in first_resp.get("data", []):
            ts = int(item["date"])
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            cached_readings[date_str] = {
                "timestamp": ts,
                "meter_value_m3": float(item["value"]),
                "serial_number": item.get("meter", {}).get("serial_number", ""),
                "room": item.get("meter", {}).get("room", "Vivienda"),
            }

        # Calculamos cuántas páginas desde el final necesitamos para cubrir `days + 1` lecturas
        pages_needed = (days // per_page) + 2
        start_page = max(1, last_page - pages_needed + 1)

        for p in range(last_page, start_page - 1, -1):
            if p == 1:
                continue  # Ya consultada
            resp = self.get_readings_page(building_id, page=p, service_id=service_id)
            for item in resp.get("data", []):
                ts = int(item["date"])
                date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                cached_readings[date_str] = {
                    "timestamp": ts,
                    "meter_value_m3": float(item["value"]),
                    "serial_number": item.get("meter", {}).get("serial_number", ""),
                    "room": item.get("meter", {}).get("room", "Vivienda"),
                }

        # Ordenar todas las lecturas disponibles por timestamp
        sorted_points = sorted(
            cached_readings.items(), key=lambda kv: kv[1]["timestamp"]
        )

        # Nos quedamos con las últimas `days + 1` lecturas para generar `days` consumos
        recent_points = sorted_points[-(days + 1) :] if len(sorted_points) > days else sorted_points

        readings: List[MeterReading] = []
        for idx in range(1, len(recent_points)):
            curr_date_str, curr = recent_points[idx]
            prev_date_str, prev = recent_points[idx - 1]
            daily_m3 = round(curr["meter_value_m3"] - prev["meter_value_m3"], 3)
            daily_liters = round(daily_m3 * 1000.0, 1)
            days_elapsed = max(1, round((curr["timestamp"] - prev["timestamp"]) / 86400))
            # La lectura acumulada 'curr' se toma a las 00:00:00 al finalizar el día 'prev_date_str'.
            # Por tanto, el consumo corresponde exactamente al día 'prev_date_str'.
            readings.append(
                MeterReading(
                    date=prev_date_str,
                    timestamp=prev["timestamp"],
                    meter_value_m3=round(curr["meter_value_m3"], 3),
                    daily_m3=daily_m3,
                    daily_liters=daily_liters,
                    days_elapsed=days_elapsed,
                    serial_number=curr["serial_number"],
                    room=curr["room"],
                )
            )

        return readings
