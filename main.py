#!/usr/bin/env python3
"""
GotaBot - Monitor de consumo diario de agua para EMI Telegestión.
Obtiene las lecturas directamente de la API OAuth2 de EMI Telegestión sin necesidad
de usar navegadores pesados (Selenium/Playwright), guarda una caché local, evalúa
umbrales de consumo excesivo y envía alertas opcionales por Telegram o Email.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

from gotabot.client import EmiClient
from gotabot.analyzer import analyze_consumptions
from gotabot.notifier import (
    format_report_message,
    send_email_notification,
    send_telegram_message,
)

# Asegurar salida UTF-8 en consolas de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_env_file(env_path: Path) -> None:
    """Carga variables de un archivo .env sin requerir python-dotenv."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key not in os.environ:
            os.environ[key] = val


def load_cache(cache_file: Path) -> Dict[str, dict]:
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache_file: Path, data: Dict[str, dict]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def format_address(building: dict) -> str:
    addr = building.get("addresses", {})
    gen = addr.get("general", {})
    det = addr.get("detailed", {})
    town = gen.get("town", {}).get("name", "")
    street = f"{gen.get('type', '')} {gen.get('street', '')} {gen.get('number', '')}".strip()
    block = det.get("block") or ""
    parts = [p for p in [street, f"Bloque {block}" if block else "", town] if p]
    return ", ".join(parts)


def main() -> int:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / ".env")

    parser = argparse.ArgumentParser(
        description="GotaBot: Scraper/Cliente API y monitor de consumo diario de agua (EMI Telegestión)"
    )
    parser.add_argument(
        "--username",
        default=os.environ.get("EMI_USERNAME"),
        help="Usuario (email) de EMI Telegestión (por defecto: EMI_USERNAME en .env)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("EMI_PASSWORD"),
        help="Contraseña de EMI Telegestión (por defecto: EMI_PASSWORD en .env)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Número de días de histórico diario a consultar (por defecto: 30)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("ALERT_THRESHOLD_LITERS", "1000")),
        help="Umbral fijo de consumo excesivo en Litros/día (por defecto: 1000 L)",
    )
    parser.add_argument(
        "--multiplier",
        type=float,
        default=float(os.environ.get("ALERT_MULTIPLIER_MEAN", "2.0")),
        help="Multiplicador sobre la media/mediana histórica para alertar (por defecto: 2.0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprimir la salida en formato JSON estructurado",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Enviar notificación por Telegram/Email si están configurados en .env",
    )
    parser.add_argument(
        "--notify-always",
        action="store_true",
        help="Enviar notificación siempre (incluso si no hay exceso de consumo en el último día)",
    )
    parser.add_argument(
        "--force-notify",
        action="store_true",
        help="Forzar el envío de notificación ignorando la protección de envío único diario",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignorar la caché local y volver a pedir todos los días a la API",
    )
    parser.add_argument(
        "--export-web",
        action="store_true",
        help="Generar el archivo docs/data.json para el Dashboard Web",
    )
    parser.add_argument(
        "--pin",
        default=os.environ.get("DASHBOARD_PIN", "1234"),
        help="PIN de 4 dígitos para proteger el Dashboard Web (por defecto: 1234)",
    )

    args = parser.parse_args()

    if not args.username or not args.password:
        print(
            "❌ Error: Debes indicar las credenciales mediante el archivo .env (EMI_USERNAME / EMI_PASSWORD) "
            "o por parámetros (--username / --password).",
            file=sys.stderr,
        )
        return 1

    client = EmiClient(username=args.username, password=args.password)

    if not args.json:
        print("🔐 Autenticando en la API de EMI Telegestión...")
    client.login()

    user_info = client.get_current_user()
    user_name = user_info.get("name", args.username)

    buildings = client.get_buildings()
    if not buildings:
        print("❌ No se encontraron viviendas asociadas a esta cuenta.", file=sys.stderr)
        return 1

    building = buildings[0]
    building_id = int(building["id"])
    address_str = format_address(building)

    # Buscar servicio de Agua (por defecto id=8)
    service_id = 8
    for srv in building.get("services", []):
        if "agua" in srv.get("name", "").lower():
            service_id = int(srv["id"])
            break

    cache_file = base_dir / "data" / f"readings_{building_id}_{service_id}.json"
    cached_readings = {} if args.no_cache else load_cache(cache_file)

    if not args.json:
        print(f"🏠 Vivienda: {address_str} (ID: {building_id})")
        print(f"📡 Obteniendo consumos diarios de los últimos {args.days} días...")

    readings = client.get_daily_readings(
        building_id=building_id,
        days=args.days,
        service_id=service_id,
        cached_readings=cached_readings,
    )
    save_cache(cache_file, cached_readings)

    report = analyze_consumptions(
        readings=readings,
        threshold_liters=args.threshold,
        multiplier_mean=args.multiplier,
    )

    # Exportar datos para la web estática si se solicita o por defecto en docs/
    web_dir = base_dir / "docs"
    dashboard_pin = args.pin.strip()
    web_export_data = {
        "security": {
            "pin": dashboard_pin,
        },
        "user": {"name": user_name},
        "building": {
            "id": building_id,
            "address": address_str,
            "meter_serial": report.latest.serial_number,
        },
        "summary": {
            "latest_date": report.latest.date,
            "latest_meter_m3": report.latest.meter_value_m3,
            "latest_daily_m3": report.latest.daily_m3,
            "latest_daily_liters": report.latest.daily_liters,
            "mean_daily_liters": report.mean_liters,
            "median_daily_liters": report.median_liters,
            "threshold_liters": report.threshold_liters,
            "multiplier_mean": report.multiplier_mean,
            "is_latest_excessive": report.is_latest_excessive,
            "latest_alerts": report.latest_alerts,
        },
        "daily_readings": [
            {
                "date": r.date,
                "meter_value_m3": r.meter_value_m3,
                "daily_m3": r.daily_m3,
                "daily_liters": r.daily_liters,
                "days_elapsed": getattr(r, "days_elapsed", 1),
            }
            for r in readings
        ],
        "historical_alerts": [
            {
                "date": a.date,
                "daily_liters": a.daily_liters,
                "daily_m3": a.daily_m3,
                "reasons": a.reasons,
            }
            for a in report.historical_alerts
        ],
    }

    if args.export_web or web_dir.exists():
        web_dir.mkdir(parents=True, exist_ok=True)
        (web_dir / "data.json").write_text(
            json.dumps(web_export_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if args.json:
        output = {
            "user": user_info,
            "building": {
                "id": building_id,
                "address": address_str,
                "meter_serial": report.latest.serial_number,
            },
            "summary": {
                "latest_date": report.latest.date,
                "latest_meter_m3": report.latest.meter_value_m3,
                "latest_daily_m3": report.latest.daily_m3,
                "latest_daily_liters": report.latest.daily_liters,
                "mean_daily_liters": report.mean_liters,
                "median_daily_liters": report.median_liters,
                "threshold_liters": report.threshold_liters,
                "multiplier_mean": report.multiplier_mean,
                "is_latest_excessive": report.is_latest_excessive,
                "latest_alerts": report.latest_alerts,
            },
            "daily_readings": [
                {
                    "date": r.date,
                    "meter_value_m3": r.meter_value_m3,
                    "daily_m3": r.daily_m3,
                    "daily_liters": r.daily_liters,
                }
                for r in readings
            ],
            "historical_alerts": [
                {
                    "date": a.date,
                    "daily_liters": a.daily_liters,
                    "daily_m3": a.daily_m3,
                    "reasons": a.reasons,
                }
                for a in report.historical_alerts
            ],
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0

    # Mostrar tabla detallada en consola
    print("\n" + "=" * 75)
    print(f"👤 Titular:  {user_name} ({user_info.get('email', '')})")
    print(f"📍 Dirección: {address_str}")
    print(f"🔧 Contador:  {report.latest.serial_number} ({report.latest.room})")
    print("=" * 75)
    print(f"{'FECHA':<12} | {'LECTURA (m³)':>14} | {'CONSUMO (m³)':>14} | {'CONSUMO (L)':>13} | {'ESTADO'}")
    print("-" * 75)

    alert_dates = {a.date for a in report.historical_alerts}
    for r in readings:
        status = "🚨 EXCESIVO" if r.date in alert_dates else "✅ Normal"
        days_note = f" ({r.days_elapsed}d)" if getattr(r, "days_elapsed", 1) > 1 else ""
        date_col = f"{r.date}{days_note}"
        print(
            f"{date_col:<12} | {r.meter_value_m3:>14.3f} | {r.daily_m3:>14.3f} | {r.daily_liters:>11.1f} L | {status}"
        )

    print("-" * 75)
    print(f"📊 Media aritmética ({len(readings)} días):   {report.mean_liters:>8.1f} L/día ({report.mean_liters/1000:.3f} m³/día)")
    print(f"📊 Mediana habitual ({len(readings)} días):   {report.median_liters:>8.1f} L/día ({report.median_liters/1000:.3f} m³/día)")
    print(f"🎯 Umbral fijo configurado:       {report.threshold_liters:>8.1f} L/día")
    print("=" * 75)

    dashboard_url = os.environ.get("DASHBOARD_URL", "").strip()
    msg_text = format_report_message(
        report,
        user_name,
        address_str,
        dashboard_url=dashboard_url,
        dashboard_pin=dashboard_pin,
    )
    print("\n📋 Resumen de estado:")
    print(msg_text.replace("*", "").replace("`", ""))

    should_send = args.notify_always or (args.notify and report.is_latest_excessive)
    if should_send:
        # Control de duplicados: evitar enviar más de una notificación al día o repetir la misma lectura
        state_file = base_dir / "data" / "last_notification.json"
        already_sent = False
        last_state = {}

        try:
            import zoneinfo
            today_str = datetime.now(zoneinfo.ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")
        except Exception:
            today_str = datetime.now().strftime("%Y-%m-%d")

        if state_file.exists():
            try:
                last_state = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:
                last_state = {}

        last_sent_date = last_state.get("last_sent_date")
        last_reading_date = last_state.get("last_reading_date")

        if not args.force_notify and (last_sent_date == today_str or last_reading_date == report.latest.date):
            already_sent = True
            reason = (
                f"ya se envió notificación hoy ({last_sent_date})"
                if last_sent_date == today_str
                else f"la lectura del {report.latest.date} ya fue notificada previamente"
            )
            print(f"\nℹ️ Notificación omitida (skip): {reason}. Usa --force-notify si deseas forzar el reenvío.")

        if not already_sent:
            tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
            tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
            sent_any = False

            if tg_token and tg_chat:
                print("\n📲 Enviando notificación a Telegram...")
                ok = send_telegram_message(tg_token, tg_chat, msg_text)
                if ok:
                    print("✅ Telegram enviado correctamente.")
                    sent_any = True
                else:
                    print("❌ Falló el envío a Telegram.")

            smtp_user = os.environ.get("SMTP_USER", "").strip()
            smtp_pass = os.environ.get("SMTP_PASSWORD", "").strip()
            email_to = os.environ.get("EMAIL_TO", "").strip()
            if smtp_user and smtp_pass and email_to:
                print("\n📧 Enviando notificación por Email...")
                subject = (
                    f"🚨 ALERTA GotaBot: Consumo excesivo ({report.latest.daily_liters:.1f} L)"
                    if report.is_latest_excessive
                    else f"💧 GotaBot: Resumen de consumo ({report.latest.daily_liters:.1f} L)"
                )
                email_ok = send_email_notification(
                    smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
                    smtp_port=int(os.environ.get("SMTP_PORT", "587")),
                    smtp_user=smtp_user,
                    smtp_password=smtp_pass,
                    email_to=email_to,
                    subject=subject,
                    body=msg_text,
                )
                if email_ok:
                    print("✅ Email enviado correctamente.")
                    sent_any = True

            if sent_any:
                new_state = {
                    "last_sent_date": today_str,
                    "last_reading_date": report.latest.date,
                    "latest_meter_m3": report.latest.meter_value_m3,
                    "sent_at": datetime.now().isoformat(),
                }
                state_file.parent.mkdir(parents=True, exist_ok=True)
                state_file.write_text(
                    json.dumps(new_state, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
