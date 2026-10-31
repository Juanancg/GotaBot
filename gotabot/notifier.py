"""
Módulo de notificaciones (Telegram y Email SMTP) usando únicamente la librería estándar.
"""

import json
import smtplib
import urllib.request
from email.message import EmailMessage
from typing import Optional
from .analyzer import AnalysisReport


def format_report_message(
    report: AnalysisReport,
    user_name: str = "",
    address_str: str = "",
    dashboard_url: Optional[str] = None,
    dashboard_pin: Optional[str] = None,
) -> str:
    """Genera un mensaje de resumen claro con el estado del consumo."""
    status_emoji = "🚨 ALERTA DE CONSUMO EXCESIVO" if report.is_latest_excessive else "✅ Consumo dentro de la normalidad"
    lines = [
        f"💧 *GotaBot - Monitor de Agua*",
        f"{status_emoji}",
        f"",
        f"📅 *Última lectura ({report.latest.date}):*",
        f"• Lectura contador: *{report.latest.meter_value_m3:.3f} m³*",
        f"• Consumo del día: *{report.latest.daily_liters:.1f} L* ({report.latest.daily_m3:.3f} m³)",
        f"",
        f"📊 *Estadísticas ({len(report.history)} días):*",
        f"• Media aritmética: {report.mean_liters:.1f} L/día",
        f"• Consumo habitual (mediana): {report.median_liters:.1f} L/día",
        f"• Umbral fijo de alerta: {report.threshold_liters:.1f} L/día",
    ]

    if report.is_latest_excessive:
        lines.append("")
        lines.append("⚠️ *Motivos de la alerta en la última lectura:*")
        for reason in report.latest_alerts:
            lines.append(f"  - {reason}")

    if report.historical_alerts:
        lines.append("")
        lines.append(f"🔎 *Días recientes con consumo excesivo detectado ({len(report.historical_alerts)}):*")
        for alert in report.historical_alerts[-5:]:
            lines.append(f"  • {alert.date}: *{alert.daily_liters:.1f} L* ({alert.daily_m3:.3f} m³)")

    if dashboard_url:
        lines.append("")
        clean_url = dashboard_url.rstrip("/")
        link = f"{clean_url}/?key={dashboard_pin}" if dashboard_pin else clean_url
        lines.append(f"📱 [👉 Ver Gráfica y Dashboard Completo]({link})")

    return "\n".join(lines)


def send_telegram_message(bot_token: str, chat_ids: str, text: str) -> bool:
    """
    Envía un mensaje a través de la API de Telegram Bot a uno o varios destinatarios.
    `chat_ids` puede ser un único ID ("123456789") o varios separados por coma ("123456789,987654321").
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    id_list = [cid.strip() for cid in chat_ids.split(",") if cid.strip()]
    if not id_list:
        return False

    all_ok = True
    for chat_id in id_list:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("ok"):
                    all_ok = False
        except Exception as e:
            print(f"❌ Error enviando Telegram a chat_id={chat_id}: {e}")
            all_ok = False

    return all_ok


def send_email_notification(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    email_to: str,
    subject: str,
    body: str,
) -> bool:
    """Envía una notificación por correo electrónico vía SMTP."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg.set_content(body.replace("*", "").replace("`", ""))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    return True
