# TikTok IA – videos automáticos con Veo

Mini-novelas para TikTok: historias dramáticas de 24 segundos en 3 escenas (planteamiento, conflicto y giro final), con diálogo en español de México.

Este repositorio hace esto solo, **martes y viernes a las 9:17 a. m.** (hora del centro de México):

1. Toma la siguiente historia de `ideas/cola/` (las escribe Claude cada semana).
2. Genera las 3 escenas verticales 9:16 con **Veo 3.1** (el mismo modelo que usa Flow) en Google Cloud. La escena 2 arranca desde el último cuadro de la 1, y la 3 desde el último de la 2, para que los personajes y el lugar se vean iguales.
3. Une las escenas y pone el texto gancho en pantalla los primeros 3 segundos.
4. Lo manda a tu TikTok como **borrador**: te llega una notificación en la app.
5. Te abre un *issue* en GitHub con el caption listo para copiar (te llega notificación al correo y a la app de GitHub).

Tú solo abres TikTok, pegas el caption, activas la etiqueta de IA y publicas.

---

## Cuánto cuesta

Con la configuración inicial: **3 escenas de 8 s (24 s), Veo 3.1 Lite en 720p ($0.05 USD por segundo), martes y viernes.**

| Configuración | Costo por video | Videos al mes | Costo al mes |
|---|---|---|---|
| **Inicial**: 3 escenas, Lite 720p, martes y viernes | $1.20 | 8 (el tope corta el 9.º) | **$9.60** (lo cubren tus $10 de AI Pro) |
| 3 escenas, Lite 720p, lunes, miércoles y viernes | $1.20 | ~13 | ~$15.60 |
| 3 escenas, Lite 1080p ($0.08/s), martes y viernes | $1.92 | ~9 | ~$16.70 |
| 3 escenas, Fast 1080p ($0.12/s), martes y viernes | $2.88 | ~9 | ~$25.00 |
| 8 escenas (64 s, mínimo para Recompensas), Lite 720p, martes y viernes | $3.20 | ~9 | ~$27.80 |

Precios de referencia de la API de Veo 3.1; Google cobra lo que diga su página de precios. Además hay un **tope de $10 USD al mes** en `config.json` (`presupuesto.tope_mensual_usd`): si el siguiente video lo rebasa, no se genera y te avisa. GitHub Actions es gratis para este uso.

---

## Configuración (una sola vez, ~1 hora)

### Paso 1. Google Cloud: créditos, proyecto y Vertex AI

1. **Activa tus créditos de Gemini Pro.** Entra a <https://developers.google.com/program> con la misma cuenta de Google donde pagas Gemini Pro → *Únete al programa* → en tu perfil, sección **Beneficios**, activa los **créditos de Google Cloud ($10 USD/mes)**. Te pedirá elegir o crear una **cuenta de facturación** (necesita tarjeta; los créditos se gastan primero).
2. **Crea el proyecto.** En <https://console.cloud.google.com> → selector de proyectos (arriba) → **Proyecto nuevo** → nombre `tiktok-ia` → Crear. Anota el **ID del proyecto** (ej. `tiktok-ia-482913`); es el que va en el secreto `GCP_PROJECT`.
3. **Liga la facturación.** Menú ☰ → **Facturación** → *Vincular una cuenta de facturación* → elige la cuenta donde quedaron los créditos.
4. **Activa Vertex AI.** Menú ☰ → **APIs y servicios** → **Biblioteca** → busca **Vertex AI API** → **Habilitar**.
5. **Crea la cuenta de servicio (el "robot" que usará GitHub).** Menú ☰ → **IAM y administración** → **Cuentas de servicio** → **Crear cuenta de servicio**:
   - Nombre: `tiktok-ia-bot` → Crear y continuar.
   - Rol: **Usuario de Vertex AI** (`Vertex AI User`) → Continuar → Listo.
   - Abre la cuenta creada → pestaña **Claves** → **Agregar clave** → **Crear clave nueva** → **JSON** → se descarga un archivo `.json`. **No lo subas al repositorio**: su contenido va en el secreto `GCP_SA_KEY`.
6. **Alerta de gasto (recomendado).** Facturación → **Presupuestos y alertas** → Crear presupuesto → $10 USD → alertas al 50 %, 90 % y 100 %. (La alerta avisa, no corta el servicio; el tope de `config.json` es el que frena.)

### Paso 2. TikTok for Developers: tu app

1. Entra a <https://developers.tiktok.com> e inicia sesión **con la misma cuenta de TikTok donde vas a publicar**.
2. **Manage apps** → **Connect an app** → ponle nombre (ej. `Estudio IA`; no uses la palabra "TikTok" en el nombre).
3. En **Platforms** marca **Desktop**.
4. **Products** → **Add products**:
   - **Login Kit** → en *Desktop*, Redirect URI: `http://localhost:8765/callback/` (exactamente así, con la diagonal final).
   - **Content Posting API** → deja **Direct Post desactivado** (solo usamos borradores).
5. Revisa que los **Scopes** sean `user.info.basic` y `video.upload`.

### Paso 3. Sandbox (para no esperar la revisión de TikTok)

1. En la página de tu app, cambia de *Production* a **Sandbox** → **Create Sandbox** → nombre `pruebas`.
2. En la sandbox repite el Paso 2.4 (Login Kit con el mismo Redirect URI + Content Posting API) y da **Apply changes**.
3. **Sandbox settings** → **Target users** → **Add account** → inicia sesión con tu cuenta de TikTok y acepta. (Puede tardar hasta una hora en aparecer.)
4. Si TikTok te pide **verificar una URL** para Content Posting API, verifica `https://emstudiodigital.com/` con la opción de archivo (lo subes a `public_html` en Hostinger) o con registro DNS TXT.
5. Copia el **Client key** y **Client secret** **de la sandbox** (son distintos a los de producción).

> La sandbox sirve para usar la API sin enviar la app a revisión. La primera prueba (Paso 7) te dirá si los borradores de sandbox se pueden publicar normalmente en tu cuenta. Si no, usa el **Plan B** de abajo.

### Paso 4. Conectar tu cuenta de TikTok (en tu computadora)

1. Instala Python 3.12 desde <https://www.python.org/downloads/> (en el instalador marca **Add python.exe to PATH**).
2. Descarga este repositorio: botón verde **Code** → **Download ZIP** → descomprímelo.
3. Abre una terminal en esa carpeta (clic derecho → *Abrir en Terminal*) y corre:
   ```
   py -m pip install requests
   py tools\tiktok_login.py
   ```
4. Pega el Client key y el Client secret de la sandbox. Se abre el navegador → autoriza con tu cuenta de TikTok.
5. La terminal te muestra el **refresh token**. Cópialo: va en el secreto `TIKTOK_REFRESH_TOKEN`. Dura 365 días y el sistema lo renueva solo.

### Paso 5. Token de GitHub para renovar el acceso de TikTok

TikTok a veces cambia el refresh token al renovarlo; el workflow necesita permiso para guardar el nuevo.

1. <https://github.com/settings/personal-access-tokens> → **Generate new token** (fine-grained).
2. Nombre `tiktok-ia`, expiración **1 año**, *Repository access* → **Only select repositories** → `tiktok-ia`.
3. *Permissions* → *Repository permissions* → **Secrets: Read and write**.
4. Genera y copia el token: va en el secreto `GH_PAT`. Pon un recordatorio para renovarlo en un año.

### Paso 6. Guardar los secretos en GitHub

En el repositorio → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**, uno por uno:

| Secreto | Qué poner |
|---|---|
| `GCP_PROJECT` | ID del proyecto de Google Cloud (Paso 1.2) |
| `GCP_SA_KEY` | Todo el contenido del archivo `.json` de la cuenta de servicio (Paso 1.5) |
| `TIKTOK_CLIENT_KEY` | Client key de la sandbox (Paso 3.5) |
| `TIKTOK_CLIENT_SECRET` | Client secret de la sandbox (Paso 3.5) |
| `TIKTOK_REFRESH_TOKEN` | El refresh token (Paso 4.5) |
| `GH_PAT` | El token de GitHub (Paso 5) |

Después, en `config.json`, cambia `"tema_cuenta"` por el tema de tu cuenta (Claude lo usa para las ideas).

### Paso 7. Pruebas

1. **Prueba gratis de TikTok:** pestaña **Actions** → **Video diario para TikTok** → **Run workflow** → marca **Simular** y deja marcado **Mandar a TikTok** → Run. En 2–3 minutos te llega a TikTok un borrador con barras de colores (bórralo) y un issue en GitHub.
2. **Primer video real:** Run workflow **sin** marcar Simular. Tarda 5–15 minutos y gasta ~$1.20 USD.
3. Listo: desde aquí corre solo martes y viernes.

---

## Uso diario

1. Te llega un issue **"🎬 Borrador listo en TikTok: …"** (correo / app de GitHub).
2. En TikTok, abre la notificación de la **Bandeja de entrada** para terminar el borrador.
3. Copia el caption del issue y pégalo.
4. **Más opciones** → activa **Contenido generado por IA** (obligatorio en TikTok para video realista hecho con IA).
5. Publica y cierra el issue.

TikTok permite **máximo 5 borradores pendientes**: si se juntan más, la subida falla hasta que publiques o borres alguno (el issue te lo dice y deja el video descargable).

## Las ideas

- Cada idea es un archivo en `ideas/cola/` (se procesan en orden alfabético). Al usarse pasan a `ideas/hechas/` con el resultado.
- Claude agrega ideas nuevas cada semana. También puedes pedirle en cualquier momento: *"agrega 5 ideas a la cola de tiktok-ia"*.
- Si la cola se vacía, Gemini crea una idea de respaldo para no fallar (`ideas.respaldo_gemini` en `config.json`).

Formato de una idea:

```json
{
  "id": "2026-11-03-a",
  "titulo": "Título interno",
  "gancho": "Texto en pantalla (máx. ~45 caracteres)",
  "estilo": "Visual style shared by all scenes, in English",
  "escenas": [
    "Escena 1 en inglés: personajes descritos completos, acción, cámara; diálogo entre comillas en español",
    "Escena 2: continúa justo donde terminó la 1",
    "Escena 3: el giro final"
  ],
  "caption": "Descripción para TikTok #hashtag1 #hashtag2",
  "continuidad": true
}
```

Consejos para que las historias salgan bien con Veo:
- Cada escena repite la descripción de los personajes (edad, ropa, cabello) aunque ya salieran antes.
- Con `"continuidad": true`, cada escena empieza en el último cuadro de la anterior: escribe la escena como continuación del mismo lugar y momento. Si la historia necesita un salto de lugar o tiempo, pon `"continuidad": false` en esa idea.
- Diálogos cortos: máximo ~15 palabras por escena para que quepan en 8 segundos.

## Ajustes (`config.json`)

| Ajuste | Para qué |
|---|---|
| `tema_cuenta` | Tema de tu cuenta (lo usan las ideas) |
| `video.modelos` | Orden de modelos de Veo; si el primero no está disponible, usa el siguiente |
| `video.resolucion` | `1080p` o `720p` (720p cuesta menos con Lite: $0.05/s) |
| `video.max_clips_por_video` | Escenas de 8 s por video (3 = 24 s; 8 = 64 s, lo mínimo para el programa de Recompensas) |
| `video.continuidad` | Cada escena arranca del último cuadro de la anterior (personajes consistentes) |
| `video.texto_gancho` | `true`/`false` para el texto en pantalla |
| `presupuesto.tope_mensual_usd` | Tope de gasto estimado al mes |
| `tiktok.subir` | `false` para solo generar el video sin mandarlo a TikTok |

Para cambiar días u hora, edita la línea `cron` de `.github/workflows/video-diario.yml` (la hora está en UTC: hora de CDMX + 6).

## Plan B: si la sandbox no deja publicar los borradores

Hay que mandar la app a revisión de TikTok (tarda de varios días a 2 semanas):

1. Sube `web/privacidad.html` y `web/terminos.html` a Hostinger, por ejemplo en `public_html/tiktok-ia/` → quedan en `https://emstudiodigital.com/tiktok-ia/privacidad.html` y `.../terminos.html`. Antes cambia `{{CORREO_DE_CONTACTO}}` por tu correo.
2. En la app (Production): llena ícono, descripción, categoría y esas dos URLs.
3. Graba un video corto de pantalla mostrando el flujo: correr `tiktok_login.py`, autorizar, y el borrador llegando a TikTok.
4. **Submit for review**. Cuando la aprueben, corre otra vez `tiktok_login.py` con el Client key/secret **de producción** y actualiza los secretos `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` y `TIKTOK_REFRESH_TOKEN`.

## Problemas comunes

| Mensaje en el issue | Solución |
|---|---|
| `No se pudo renovar el acceso a TikTok (invalid_grant…)` | Corre otra vez `tools/tiktok_login.py` y actualiza `TIKTOK_REFRESH_TOKEN` |
| `spam_risk_too_many_pending_share` | Tienes 5 borradores sin publicar; publica o borra en TikTok |
| `Falta la variable/secreto …` | Falta ese secreto en Settings → Secrets → Actions |
| `PERMISSION_DENIED` de Google | Revisa que la cuenta de servicio tenga el rol *Usuario de Vertex AI* y que Vertex AI API esté habilitada |
| No te deja crear la clave JSON | Tu cuenta tiene una política que bloquea claves; avísale a Claude para cambiar a *Workload Identity Federation* |
| `bloqueado por filtros de seguridad` | Veo rechazó el prompt; la idea se reintenta una vez y luego sale de la cola |
| Falla siempre en la escena 2 (con imagen inicial) | Tu región o proyecto no permite imagen→video con personas: pon `"continuidad": false` en `config.json` |
| `Tope de gasto del mes alcanzado` | Sube `presupuesto.tope_mensual_usd` o espera al día 1 |
| El workflow dejó de correr solo | GitHub pausa los cron tras 60 días sin actividad en el repo; entra a Actions y reactívalo |

## Pruebas del código

```
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Las pruebas no usan internet: simulan Veo con ffmpeg y TikTok con un servidor local.
