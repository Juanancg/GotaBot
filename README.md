# GotaBot 💧

Bot y monitor diario de consumo de agua para contadores de **EMI Telegestión**. Lee las lecturas directamente de la API, calcula consumos diarios, detecta anomalías o posibles fugas y envía alertas por Telegram. Además, genera un dashboard web sencillo protegido por PIN para consultarlo desde el móvil.

---

## Características

- **Sin navegadores pesados**: interactúa directamente con la API REST de EMI Telegestión mediante OAuth2 (cero dependencias externas, solo Python estándar).
- **Control de fugas / exceso**: compara el gasto diario frente a un umbral fijo configurable (ej: 1000 L) y frente a la mediana histórica habitual.
- **Alertas por Telegram**: soporte para enviar notificaciones a uno o varios destinatarios (`CHAT_ID`).
- **Dashboard web móvil**: web estática en `docs/` con gráficos interactivos diarios (7, 15 y 30 días) protegida con PIN de acceso o enlace directo desde Telegram.
- **Automatización 24/7**: workflow de GitHub Actions incluido para ejecutarse gratis cada mañana y desplegar la web a GitHub Pages.

---

## Configuración rápida

1. Clona el repositorio y crea tu archivo `.env`:
   ```bash
   cp .env.example .env
   ```

2. Configura tus credenciales y parámetros en `.env`:
   ```ini
   EMI_USERNAME=tu_email@ejemplo.com
   EMI_PASSWORD=tu_contraseña

   # Umbrales
   ALERT_THRESHOLD_LITERS=1000
   ALERT_MULTIPLIER_MEAN=2.0

   # Telegram
   TELEGRAM_BOT_TOKEN=tu_bot_token
   TELEGRAM_CHAT_ID=tu_chat_id

   # Web
   DASHBOARD_PIN=1234
   DASHBOARD_URL=https://tu-usuario.github.io/GotaBot/
   ```

3. Ejecuta el script:
   ```bash
   # Consulta los últimos 15 días en consola
   python main.py --days 15

   # Enviar notificación a Telegram solo si hay consumo excesivo
   python main.py --days 15 --notify

   # Enviar siempre el parte diario a Telegram y actualizar el dashboard web
   python main.py --days 15 --notify-always --export-web
   ```

---

## Automatización en GitHub Actions (Gratis)

El workflow en `.github/workflows/daily_check.yml` se ejecuta automáticamente todos los días a las 08:00 UTC:

1. Ve a tu repositorio en GitHub > **Settings** > **Secrets and variables** > **Actions**.
2. Añade los siguientes secretos:
   - `EMI_USERNAME`
   - `EMI_PASSWORD`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - *(Opcional)* `ALERT_THRESHOLD_LITERS`, `DASHBOARD_PIN`, `DASHBOARD_URL`
3. Si quieres habilitar el dashboard web en GitHub Pages:
   - Ve a **Settings** > **Pages**.
   - En **Build and deployment** > **Source**, selecciona **GitHub Actions**.

---

## Estructura del proyecto

- `main.py`: CLI principal y generador de datos.
- `gotabot/client.py`: Cliente HTTP para autenticación y extracción de lecturas en EMI Telegestión.
- `gotabot/analyzer.py`: Lógica de análisis de consumo y detección de excesos.
- `gotabot/notifier.py`: Formateo de informes y envíos a la API de Telegram y SMTP.
- `docs/`: WebApp responsive para móvil con Chart.js y Tailwind CSS.
- `.github/workflows/`: Automatización diaria y despliegue continuo.
