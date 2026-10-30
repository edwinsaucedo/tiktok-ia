# Revisión de TikTok (App review)

Sirve para que la app salga de *sandbox* y los borradores lleguen directo a tu bandeja de TikTok. Mientras tanto, los videos te llegan por **Telegram** y eso no depende de la revisión.

## Antes de mandarla: el obstáculo principal

Las reglas de revisión de TikTok dicen: **"Apps must not be for private or personal use."** Las apps de uso personal se rechazan.

Hoy la app es exactamente eso. Tu propio aviso de privacidad (`web/privacidad.html`) la describe como *"herramienta privada… uso interno"* y *"private, single-user tool"*. Si la mandas así, lo más probable es que la rechacen.

Tienes dos caminos:

| | **A. Quedarte con Telegram** (recomendado si es solo para tu cuenta) | **B. Ofrecerlo como servicio de EMStudioDigital** |
|---|---|---|
| Qué cambia | Nada. Ya funciona | Que otros creadores o clientes de tu estudio conecten **su** TikTok y reciban sus videos |
| Trabajo | Ninguno | Claude adapta el sistema a varias cuentas, reescribe las páginas legales y publica una página de la herramienta en emstudiodigital.com |
| Diferencia para ti | Guardas el video de Telegram y lo subes (≈30 s más por video) | El borrador aparece solo en TikTok |

Elige **B** solo si de verdad vas a ofrecerlo a otras personas: la revisión tiene que describir la app tal como es. Si eliges B, dile a Claude *"prepara el modo para clientes"* y luego sigue esta guía.

---

## Guía para el camino B

### 1. Datos de la app (Production → App details)

- **App name:** el mismo que se vea en tu web y en las páginas legales. Hoy no coinciden (la app es *CanacaReels* y las páginas dicen *Estudio IA*); hay que dejar uno solo.
- **Icon:** `icono-canacareels-1024.png` (o uno nuevo si cambias el nombre).
- **Category:** Entertainment (o *Productivity* si lo presentas como herramienta para creadores).
- **Description** (en inglés, cópiala tal cual):

```
EM Studio Digital helps creators turn short AI-assisted drama stories into vertical videos and sends each finished video to the creator's TikTok inbox as a draft, so they can review it, edit the caption and post it themselves.
```

- **Terms of Service URL / Privacy Policy URL:** las de `emstudiodigital.com/tiktok-ia/` ya actualizadas para el servicio a clientes. Ya están verificadas.
- **Platforms:** Desktop (o Web, si se publica la página de la herramienta).

### 2. Explicación de productos y permisos (App review → explanation)

En inglés, cópiala tal cual:

```
Login Kit (user.info.basic): The creator connects their TikTok account once through TikTok's authorization page. We call the user info endpoint only to show the connected account's display name and avatar, so the creator can confirm the right account is linked.

Content Posting API – Upload (video.upload): When a creator's video is ready (they generate the clips with Google Flow and drop them into their Google Drive folder), our system adds an on-screen title, joins the clips into one 9:16 video and sends it to the creator's TikTok inbox using the Upload flow. TikTok notifies the creator, who opens the draft, edits the caption, turns on the AI-generated content label and decides whether to post. We never post directly, never change privacy settings, and nothing is published without the creator's action in the TikTok app. Videos are deleted from our systems after 7 days.
```

### 3. Video demo (máx. 5 videos de 50 MB; MP4)

TikTok pide que se vea **todo el flujo**, **cada producto y permiso**, la interfaz y los clics. Graba la pantalla de la computadora (en Windows: tecla Windows + Alt + R, o la Herramienta Recortes → Grabar). Para la parte del celular, usa la grabación de pantalla del iPhone. Une los dos clips en uno.

| # | Qué se ve | Permiso que demuestra |
|---|---|---|
| 1 | La página de la herramienta en emstudiodigital.com (con el mismo nombre de la app) | — |
| 2 | GitHub → **Conectar TikTok** → Run → abrir el link → **pantalla de autorización de TikTok** (se lee el nombre de la app y los permisos) → **Autorizar** | Login Kit |
| 3 | Pegar la dirección → la ejecución termina con **"Cuenta: @tu_usuario"** y su foto | `user.info.basic` |
| 4 | Google Drive → carpeta de una historia → subir el video de Flow | — |
| 5 | GitHub → **Videos de Flow desde Google Drive** → Run → termina en verde | — |
| 6 | En el celular: abrir TikTok → **notificación de la bandeja** → abrir el borrador → editar el caption → activar **Contenido generado por IA** → Publicar | `video.upload` |

> El paso 6 es el que hoy falla en *sandbox* (la notificación no aparece). Graba primero ese paso: si no aparece, la revisión no se puede demostrar y no conviene mandarla todavía.

### 4. Antes de dar *Submit for review*

- [ ] Quitar de la app cualquier producto o permiso que no se muestre en el video (TikTok lo marca como *scope overreach*).
- [ ] Páginas legales y página de la herramienta publicadas, con el mismo nombre de la app.
- [ ] Mismos valores que la sandbox: Redirect URI `http://localhost:8765/callback/`, Content Posting API con **Direct Post desactivado**.
- [ ] Hacer *Reset* del Client secret que se vio en capturas y actualizar `TIKTOK_CLIENT_SECRET`.

### 5. Después de aprobada

1. Cambia los secretos `TIKTOK_CLIENT_KEY` y `TIKTOK_CLIENT_SECRET` por los **de producción**.
2. Corre otra vez **Conectar TikTok**.
3. En `config.json` pon `"tiktok": {"subir": true}`. Telegram puede seguir activo o puedes apagarlo.
