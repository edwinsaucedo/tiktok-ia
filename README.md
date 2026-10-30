# TikTok IA – mini-novelas de 1 minuto

Historias dramáticas tipo telenovela de **1 minuto** (8 partes de 8 segundos: planteamiento, conflicto y giro final), con diálogo en español de México, que te llegan **por Telegram** listas para subir a TikTok, con el caption para copiar con un toque.

El sistema tiene dos modos que trabajan juntos:

| | **Modo Flow** (principal) | **Modo automático** (extra) |
|---|---|---|
| Quién genera el video | Tú, en Google Flow, con el guion que te deja Claude | Google Cloud (Veo 3.1) solo |
| Qué haces tú | Pegar 8 prompts en Flow, descargar y subir a Drive (~15–20 min) | Nada |
| Cuántos al mes | ~6 con Veo 3.1 Fast, ~12 con Lite (1,000 créditos de Flow de tu Gemini Pro) | 3 (días 5, 15 y 25) |
| Costo extra | $0 | $0 (lo cubren los $10 USD/mes de créditos de Google Cloud de Gemini Pro) |
| Workflow | `Videos de Flow desde Google Drive` (revisa cada hora) | `Video automático con Veo (3 al mes)` |

Los dos modos terminan igual: texto gancho en pantalla los primeros 3 segundos → **el video y el caption te llegan por Telegram** → *issue* en GitHub con el resumen (te llega al correo y a la app de GitHub).

> **Por qué Telegram y no directo a TikTok:** con la app de TikTok en *sandbox*, los borradores se envían bien (`SEND_TO_USER_INBOX`) pero la notificación no aparece en la app. Mientras TikTok no apruebe la app (ver *Revisión de TikTok*), la subida directa queda apagada (`tiktok.subir: false`) y todo llega por Telegram. Cuando la aprueben, la vuelves a prender y puedes usar las dos.

---

## Modo Flow: cómo se usa

En tu Google Drive (cuenta **edwin8asaucedo@gmail.com**) está la carpeta **TikTok IA**:

```
TikTok IA/
  LÉEME - Cómo usar esta carpeta
  001 - El anillo equivocado/
    Guion para Flow - 001 El anillo equivocado   ← los 8 prompts listos para copiar
  002 - La herencia/
  …
```

1. Abre la carpeta de una historia y su **Guion para Flow**.
2. En Flow: proyecto nuevo, formato **9:16**, **1 resultado por prompt**. Genera la Parte 1 y luego **Extend** con las Partes 2 a 8 (así los personajes se mantienen iguales).
3. **Scenebuilder** → revisa el orden → **Descargar**. Descarga antes de salir del proyecto: el Scenebuilder se borra al salir.
4. Sube el video a **esa misma carpeta** de Drive (en el iPhone: app de Drive → + → Subir).
5. En menos de 1 hora (revisa cada hora de 7 a. m. a 11 p. m.) el sistema le pone el gancho, **te lo manda por Telegram** con el caption, te avisa con un issue y renombra la carpeta con ✅.

Si la carpeta queda con **⚠️** (no se pudo entregar) o **❌** (archivo dañado), el issue te dice por qué; arréglalo y **quítale el símbolo al nombre** para reintentar. Si subes clips sueltos en vez del video completo, nómbralos `1`, `2`, `3`… y el sistema los une en ese orden. No cambies el número del inicio del nombre (001, 002…): así sabe qué historia es.

---

## Cuánto cuesta

- **Modo Flow:** usa los **1,000 créditos mensuales de Flow** que trae tu Gemini Pro. Según las tablas publicadas: Veo 3.1 Fast = 20 créditos por parte (160 por video → ~6 al mes); Veo 3.1 Lite = 10 por parte (80 por video → ~12 al mes). Confírmalo en Flow. El procesamiento en GitHub y la API de TikTok son gratis.
- **Modo automático:** 8 escenas × 8 s × $0.05 USD (Veo 3.1 Lite 720p) = **$3.20 por video**; 3 al mes = **$9.60**, que cubren tus $10 de créditos de Google Cloud. Hay un **tope de $10 al mes** en `config.json`: si el siguiente video lo rebasa, no se genera y te avisa.

---

## Configuración (una sola vez, ~1 hora)

### Paso 1. Google Cloud: créditos, proyecto, Vertex AI y Drive

> **Solo modo Flow (sin facturación):** si tu cuenta de facturación está cerrada o no quieres usar tarjeta, sáltate 1.1, 1.3 y 1.6, en 1.4 habilita **solo Google Drive API** y en 1.5 no le pongas rol a la cuenta de servicio. El modo Flow funciona completo así. El modo automático queda apagado (`modo_automatico.activo: false` en `config.json`) hasta que tengas facturación activa.

1. **Activa tus créditos de Gemini Pro.** Entra a <https://developers.google.com/program> con la cuenta de Google donde pagas Gemini Pro → *Únete al programa* → en tu perfil, sección **Beneficios**, activa los **créditos de Google Cloud ($10 USD/mes)**. Te pedirá una **cuenta de facturación** (con tarjeta; los créditos se gastan primero).
2. **Crea el proyecto.** <https://console.cloud.google.com> → selector de proyectos → **Proyecto nuevo** → nombre `tiktok-ia` → Crear. Anota el **ID del proyecto** (ej. `tiktok-ia-482913`).
3. **Liga la facturación.** Menú ☰ → **Facturación** → vincula la cuenta donde quedaron los créditos.
4. **Activa dos APIs.** Menú ☰ → **APIs y servicios** → **Biblioteca** → busca y **habilita** las dos: **Vertex AI API** y **Google Drive API**.
5. **Crea la cuenta de servicio (el "robot" que usará GitHub).** Menú ☰ → **IAM y administración** → **Cuentas de servicio** → **Crear cuenta de servicio**:
   - Nombre: `tiktok-ia-bot` → Crear y continuar.
   - Rol: **Usuario de Vertex AI** (`Vertex AI User`) → Continuar → Listo.
   - **Copia su correo** (algo como `tiktok-ia-bot@tiktok-ia-482913.iam.gserviceaccount.com`): lo usas en el Paso 8.
   - Abre la cuenta → pestaña **Claves** → **Agregar clave** → **Crear clave nueva** → **JSON** → se descarga un `.json`. **No lo subas al repositorio**: su contenido va en el secreto `GCP_SA_KEY`.
6. **Alerta de gasto (recomendado).** Facturación → **Presupuestos y alertas** → $10 USD → alertas al 50 %, 90 % y 100 %.

### Paso 2. TikTok for Developers: tu app

1. Entra a <https://developers.tiktok.com> **con la cuenta de TikTok donde vas a publicar**.
2. **Manage apps** → **Connect an app** → nombre (ej. `Estudio IA`; sin la palabra "TikTok").
3. En **Platforms** marca **Desktop**.
4. **Products** → **Add products**:
   - **Login Kit** → en *Desktop*, Redirect URI: `http://localhost:8765/callback/` (exactamente así).
   - **Content Posting API** → deja **Direct Post desactivado** (solo usamos borradores).
5. Revisa que los **Scopes** sean `user.info.basic` y `video.upload`.

### Paso 3. Sandbox (para no esperar la revisión de TikTok)

1. En tu app, cambia a **Sandbox** → **Create Sandbox** → nombre `pruebas`.
2. En la sandbox repite el Paso 2.4 y da **Apply changes**.
3. **Sandbox settings** → **Target users** → **Add account** → inicia sesión con tu TikTok y acepta (puede tardar hasta una hora en aparecer).
4. Si TikTok pide **verificar una URL** para Content Posting API, verifica `https://emstudiodigital.com/` (archivo en `public_html` de Hostinger o registro DNS TXT).
5. Copia el **Client key** y **Client secret de la sandbox**.

> En sandbox TikTok acepta los borradores (`SEND_TO_USER_INBOX`) pero la notificación puede no aparecer en tu app. Por eso, por ahora, los videos te llegan por **Telegram** (Paso 5b) y la subida directa queda apagada hasta pasar la *Revisión de TikTok*.

### Paso 4. Token de GitHub (lo usan "Conectar TikTok", la renovación del acceso y Telegram)

1. <https://github.com/settings/personal-access-tokens> → **Generate new token** (fine-grained).
2. Nombre `tiktok-ia`, expiración **1 año**, *Only select repositories* → `tiktok-ia`.
3. *Repository permissions* → **Secrets: Read and write**.
4. Copia el token: va en el secreto `GH_PAT`.

### Paso 5. Guardar los secretos en GitHub

Repositorio → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secreto | Qué poner |
|---|---|
| `GCP_PROJECT` | ID del proyecto de Google Cloud (Paso 1.2) |
| `GCP_SA_KEY` | Todo el contenido del `.json` de la cuenta de servicio (Paso 1.5) |
| `TIKTOK_CLIENT_KEY` | Client key de la sandbox (Paso 3.5) |
| `TIKTOK_CLIENT_SECRET` | Client secret de la sandbox (Paso 3.5) |
| `GH_PAT` | Token de GitHub (Paso 4) |
| `TELEGRAM_BOT_TOKEN` | Token de tu bot de Telegram (Paso 5b) |

`TIKTOK_REFRESH_TOKEN` y `TELEGRAM_CHAT_ID` no los creas tú: se guardan solos (Paso 6 y la primera entrega por Telegram).

### Paso 5b. Tu bot de Telegram (aquí te llegan los videos)

1. En Telegram busca **@BotFather** (con la palomita azul) → **Iniciar** → escribe `/newbot`.
2. Nombre: el que quieras (ej. `Canaca Reels`). Usuario: debe terminar en `bot` (ej. `canacareels_bot`).
3. BotFather te contesta con un **token** (algo como `7123456789:AAH…`). Guárdalo en GitHub como secreto **`TELEGRAM_BOT_TOKEN`**. No se lo pases a nadie.
4. Toca el link de tu bot nuevo (`t.me/…_bot`) → **Iniciar** (manda `/start`).
5. Listo. La primera vez que se entregue un video, el sistema encuentra tu chat y lo guarda como `TELEGRAM_CHAT_ID`. Si pasan más de 24 h entre el `/start` y la primera prueba, vuelve a mandarle `/start` antes.

### Paso 6. Conectar tu cuenta de TikTok (sin instalar nada)

1. **Actions** → **Conectar TikTok** → **Run workflow** → deja el campo **vacío** → Run.
2. Abre la ejecución cuando termine (≈30 s): en el resumen aparece una **dirección de TikTok**. Ábrela, inicia sesión con tu cuenta del canal (la de *Target users*) y **autoriza**.
3. El navegador te manda a `http://localhost:8765/callback/?code=…` y dice que **no puede conectar**: es normal. **Copia esa dirección completa** de la barra.
4. En menos de 5 minutos: **Run workflow** otra vez → **pega la dirección** en el campo → Run.
5. Debe terminar en verde con "Cuenta de TikTok conectada ✅". El token quedó en el secreto `TIKTOK_REFRESH_TOKEN` (dura 365 días y se renueva solo).

> Alternativa en tu computadora: con Python instalado, `py -m pip install requests` y `py tools\tiktok_login.py` te da el refresh token para guardarlo a mano.

### Paso 7. (Ya está hecho) Carpeta de Drive

La carpeta **TikTok IA** ya existe en tu Drive y su ID ya está en `config.json` (`flow.carpeta_drive_id`).

### Paso 8. Compartir la carpeta de Drive con el robot

En Google Drive → clic derecho en **TikTok IA** → **Compartir** → pega el **correo de la cuenta de servicio** (Paso 1.5) → rol **Editor** → desmarca "Notificar" → **Compartir**. Sin esto el sistema no puede ver tus videos ni renombrar las carpetas.

### Paso 9. Pruebas

1. **Prueba gratis de entrega:** **Actions** → **Video automático con Veo (3 al mes)** → **Run workflow** → marca **Simular** → Run. En 2–3 min te llega por Telegram un video de barras de colores con su caption, y un issue.
2. **Prueba del modo Flow:** sube cualquier video corto vertical (uno de tu galería sirve) a la carpeta **`000 - Prueba`** de Drive, espera 10 minutos y corre **Actions** → **Videos de Flow desde Google Drive** → **Run workflow**. Debe llegarte el video por Telegram, un issue avisando que la historia 000 no existe (es normal en la prueba) y la carpeta debe quedar como `✅ 000 - Prueba`.
3. **Primer video automático real:** Run workflow del modo automático **sin** Simular (5–20 min, ~$3.20).

---

## Al publicar en TikTok

**Desde Telegram (lo normal):**

1. Te llega a tu bot el video y un mensaje con el caption.
2. Mantén presionado el video → **Guardar** (en Fotos o Galería).
3. En TikTok toca **+** → elige el video.
4. Toca el caption en Telegram (se copia solo) y pégalo como descripción.
5. **Más opciones** → activa **Contenido generado por IA** (obligatorio en TikTok para video realista hecho con IA) → Publica. Cierra el issue.

**Desde borrador de TikTok (cuando `tiktok.subir` esté en `true`):** abre la notificación de la **Bandeja de entrada** de TikTok, pega el caption del issue, activa *Contenido generado por IA* y publica. TikTok permite **máximo 5 borradores pendientes**; si se juntan más, la subida falla hasta que publiques o borres alguno.

## Las historias

- `ideas/flow/` → historias para el **modo Flow** (cada una tiene su carpeta y guion en Drive).
- `ideas/cola/` → historias para el **modo automático**.
- Al usarse pasan a `ideas/hechas/` con el resultado. `ideas/flow_procesadas.json` registra qué carpetas de Drive ya se subieron.
- Para más historias pídele a Claude: *"agrega 5 historias para Flow en tiktok-ia"* (crea los archivos, las carpetas y los guiones en Drive).
- Si la cola automática se vacía, Gemini crea una idea de respaldo (`ideas.respaldo_gemini`).

Formato de una historia:

```json
{
  "id": "009-la-vecina",
  "titulo": "Título",
  "gancho": "Texto en pantalla (máx. ~45 caracteres)",
  "estilo": "Visual style shared by all scenes, in English",
  "escenas": ["Parte 1 en inglés con personajes completos; diálogo entre comillas en español", "…8 partes…"],
  "caption": "Descripción para TikTok #novela #drama",
  "continuidad": true,
  "resumen_partes": ["Qué pasa en la parte 1", "…"]
}
```

Consejos: cada parte repite la descripción de los personajes (edad, ropa, cabello); todas pasan en el mismo lugar y continúan donde terminó la anterior; diálogos de máximo ~15 palabras por parte.

## Ajustes (`config.json`)

| Ajuste | Para qué |
|---|---|
| `flow.carpeta_drive_id` | Carpeta de Drive que revisa el modo Flow |
| `flow.minutos_espera` | Minutos sin cambios antes de tomar un video (para no agarrarlo a medio subir) |
| `flow.resolucion` / `flow.texto_gancho` | Resolución de salida y texto gancho en los videos de Flow |
| `video.modelos` | Modelos de Veo del modo automático; si el primero no está disponible, usa el siguiente |
| `video.resolucion` | `720p` (Lite $0.05/s) o `1080p` (Lite $0.08/s) |
| `video.max_clips_por_video` | Escenas de 8 s (8 = 64 s) |
| `video.continuidad` | Cada escena arranca del último cuadro de la anterior |
| `presupuesto.tope_mensual_usd` | Tope de gasto estimado del modo automático |
| `tiktok.subir` | `true` para mandar también el borrador a TikTok (apagado hasta que aprueben la app) |
| `telegram.activo` | `true` para que te llegue el video y el caption por Telegram |

Horarios: línea `cron` de cada workflow en `.github/workflows/` (en UTC: hora de CDMX + 6).

## Revisión de TikTok (para que lleguen los borradores directo)

1. Las páginas ya están publicadas: https://emstudiodigital.com/tiktok-ia/terminos.html y https://emstudiodigital.com/tiktok-ia/privacidad.html (archivos en `web/`).
2. En la app (Production): ícono, descripción, categoría y esas dos URLs.
3. Graba un video corto de pantalla del flujo (guion en `docs/revision-tiktok.md`).
4. **Submit for review** (de varios días a 2 semanas). Al aprobarse, cambia `TIKTOK_CLIENT_KEY` y `TIKTOK_CLIENT_SECRET` por los **de producción**, corre otra vez **Conectar TikTok** y pon `tiktok.subir: true` en `config.json`.

## Problemas comunes

| Mensaje | Solución |
|---|---|
| `Drive no encuentra la carpeta` / `no dejó renombrar` | Falta el Paso 8 (compartir **TikTok IA** como Editor con la cuenta de servicio) o el Paso 1.4 (Google Drive API) |
| Subí el video y no pasa nada | Espera: toma videos con 10 min sin cambios y revisa cada hora de 7 a. m. a 11 p. m. O corre el workflow a mano |
| `No se pudo renovar el acceso a TikTok (invalid_grant…)` | Corre otra vez el workflow **Conectar TikTok** (Paso 6) |
| `spam_risk_too_many_pending_share` | Tienes 5 borradores sin publicar en TikTok |
| `Telegram rechazó … Unauthorized` | El secreto `TELEGRAM_BOT_TOKEN` está mal: cópialo otra vez de @BotFather |
| `No encontré tu chat` / `chat not found` | Abre tu bot en Telegram, mándale `/start` y corre el workflow otra vez |
| `Encontré tu chat … no hay secreto GH_PAT` | Falta el Paso 4 (`GH_PAT`): sin él tu chat no se guarda y después de 24 h ya no lo encuentra |
| `El video venía horizontal` | En Flow elige formato 9:16 antes de generar |
| `PERMISSION_DENIED` de Vertex AI | Rol *Usuario de Vertex AI* en la cuenta de servicio y Vertex AI API habilitada |
| No te deja crear la clave JSON | Tu cuenta bloquea claves; pídele a Claude cambiar a *Workload Identity Federation* |
| `bloqueado por filtros de seguridad` | Veo rechazó el prompt; se reintenta una vez y la idea sale de la cola |
| Falla siempre en la escena 2 (modo automático) | Tu proyecto no permite imagen→video con personas: `"continuidad": false` en `config.json` |
| `Tope de gasto del mes alcanzado` | Sube `presupuesto.tope_mensual_usd` o espera al día 1 |
| Los workflows dejaron de correr solos | GitHub pausa los cron tras 60 días sin actividad; reactívalos en Actions |

## Pruebas del código

```
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Sin internet: simulan Veo con ffmpeg, TikTok y Telegram con servidores locales y Google Drive con un cliente falso.
