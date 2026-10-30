"""Generación de clips con Veo 3.1 en Vertex AI (o clips simulados con ffmpeg para pruebas)."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .comun import log

ESPERA_SONDEO = 10          # segundos entre consultas del estado de la generación
TIMEOUT_CLIP = 15 * 60      # máximo por clip


@dataclass
class ResultadoClips:
    clips: list[Path]
    modelo: str
    segundos: int
    avisos: list[str] = field(default_factory=list)


class ErrorVeo(RuntimeError):
    pass


def armar_prompt(escena: str, idea: dict, conf: dict) -> str:
    partes = []
    estilo = (idea.get("estilo") or "").strip()
    if estilo:
        partes.append(f"Style: {estilo}.")
    partes.append(escena.strip())
    partes.append("Vertical 9:16 composition for TikTok, subject centered, no on-screen text.")
    if conf.get("audio", True):
        partes.append(f"Si alguien habla, habla en {conf.get('idioma_audio', 'español de México')}.")
    return " ".join(partes)


# ------------------------------------------------------------------ simulación

def _clip_simulado(destino: Path, numero: int, segundos: int) -> None:
    texto = f"Escena {numero} (simulada)"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=720x1280:rate=24:duration={segundos}",
        "-f", "lavfi", "-i", f"sine=frequency={330 + 110 * numero}:duration={segundos}",
        "-vf", (
            "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"text='{texto}':fontsize=56:fontcolor=white:box=1:boxcolor=black@0.6:"
            "boxborderw=20:x=(w-tw)/2:y=h*0.75"
        ),
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(destino),
    ]
    subprocess.run(cmd, check=True)


# ------------------------------------------------------------------ Veo real

def _descargar_gcs(uri: str, destino: Path) -> None:
    import google.auth
    import google.auth.transport.requests
    import requests
    from urllib.parse import quote

    sin_prefijo = uri.removeprefix("gs://")
    bucket, _, objeto = sin_prefijo.partition("/")
    cred, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    cred.refresh(google.auth.transport.requests.Request())
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(objeto, safe='')}?alt=media"
    r = requests.get(url, headers={"Authorization": f"Bearer {cred.token}"}, timeout=300)
    r.raise_for_status()
    destino.write_bytes(r.content)


def _es_error_de_modelo(e: Exception) -> bool:
    """Errores que indican que el modelo no existe o no está habilitado: conviene probar otro."""
    texto = str(e).lower()
    return any(s in texto for s in ("404", "not_found", "not found", "is not supported",
                                    "publisher model", "permission_denied"))


def _es_error_temporal(e: Exception) -> bool:
    texto = str(e).lower()
    return any(s in texto for s in ("429", "resource_exhausted", "503", "unavailable",
                                    "deadline", "timeout", "500", "internal"))


def ultimo_cuadro(clip: Path, destino: Path) -> Path:
    """Extrae el último cuadro del clip (PNG) para que la siguiente escena arranque desde ahí."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.25", "-i", str(clip),
         "-frames:v", "1", "-update", "1", str(destino)],
        check=True,
    )
    if not destino.exists() or destino.stat().st_size == 0:
        raise ErrorVeo(f"No se pudo extraer el último cuadro de {clip.name}")
    return destino


def _generar_un_clip(client, modelo: str, prompt: str, conf: dict, destino: Path,
                     imagen_inicial: Path | None = None) -> None:
    from google.genai import types

    imagen = None
    if imagen_inicial is not None:
        imagen = types.Image(image_bytes=imagen_inicial.read_bytes(), mime_type="image/png")

    config = types.GenerateVideosConfig(
        aspect_ratio="9:16",
        resolution=conf.get("resolucion", "1080p"),
        duration_seconds=int(conf.get("segundos_por_clip", 8)),
        generate_audio=bool(conf.get("audio", True)),
        number_of_videos=1,
        negative_prompt=conf.get("prompt_negativo") or None,
        person_generation=conf.get("generacion_personas") or None,
    )
    if imagen is not None:
        op = client.models.generate_videos(model=modelo, prompt=prompt, image=imagen, config=config)
    else:
        op = client.models.generate_videos(model=modelo, prompt=prompt, config=config)
    inicio = time.monotonic()
    while not op.done:
        if time.monotonic() - inicio > TIMEOUT_CLIP:
            raise ErrorVeo("La generación tardó más de 15 minutos.")
        time.sleep(ESPERA_SONDEO)
        op = client.operations.get(op)
    if op.error:
        raise ErrorVeo(f"Veo devolvió error: {op.error}")
    resp = op.response or op.result
    videos = list(getattr(resp, "generated_videos", None) or [])
    if not videos:
        filtrados = getattr(resp, "rai_media_filtered_count", 0)
        razones = getattr(resp, "rai_media_filtered_reasons", None)
        raise ErrorVeo(
            "Veo no entregó video"
            + (f" (bloqueado por filtros de seguridad: {razones})" if filtrados else "")
        )
    video = videos[0].video
    if getattr(video, "video_bytes", None):
        destino.write_bytes(video.video_bytes)
    elif getattr(video, "uri", None) and video.uri.startswith("gs://"):
        _descargar_gcs(video.uri, destino)
    else:
        raise ErrorVeo("La respuesta de Veo no trae ni bytes ni ruta del video.")
    if destino.stat().st_size < 10_000:
        raise ErrorVeo("El archivo de video recibido está vacío o incompleto.")


def generar_clips(idea: dict, cfg: dict, carpeta: Path, proyecto: str | None,
                  simular: bool) -> ResultadoClips:
    conf = cfg["video"]
    segundos = int(conf.get("segundos_por_clip", 8))
    escenas = idea["escenas"][: max(1, int(conf.get("max_clips_por_video", 3)))]
    carpeta.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    avisos: list[str] = []

    if simular:
        for i, _ in enumerate(escenas, start=1):
            destino = carpeta / f"clip_{i:02d}.mp4"
            _clip_simulado(destino, i, segundos)
            clips.append(destino)
        return ResultadoClips(clips, "simulado", segundos * len(clips), avisos)

    from google import genai

    if not proyecto:
        raise ErrorVeo("Falta GCP_PROJECT (ID del proyecto de Google Cloud).")
    client = genai.Client(vertexai=True, project=proyecto, location=conf.get("region", "us-central1"))
    modelos = list(conf.get("modelos") or [])
    if not modelos:
        raise ErrorVeo("config.json no tiene modelos de video en video.modelos.")
    reintentos = max(0, int(conf.get("reintentos_por_clip", 2)))
    modelo_usado = modelos[0]
    # Continuidad: la escena 2 en adelante arranca desde el último cuadro de la anterior,
    # así los personajes y el lugar se mantienen iguales.
    continuidad = bool(idea.get("continuidad", conf.get("continuidad", True)))

    for i, escena in enumerate(escenas, start=1):
        destino = carpeta / f"clip_{i:02d}.mp4"
        prompt = armar_prompt(escena, idea, conf)
        imagen_inicial = None
        if continuidad and clips:
            imagen_inicial = ultimo_cuadro(clips[-1], carpeta / f"cuadro_{i - 1:02d}.png")
        hecho = False
        ultimo_error: Exception | None = None
        while modelos and not hecho:
            modelo = modelos[0]
            for intento in range(reintentos + 1):
                try:
                    log(f"Escena {i}/{len(escenas)} con {modelo} (intento {intento + 1})…")
                    _generar_un_clip(client, modelo, prompt, conf, destino, imagen_inicial)
                    log(f"  ✓ clip {i} listo ({destino.stat().st_size / 1e6:.1f} MB)")
                    modelo_usado = modelo
                    hecho = True
                    break
                except Exception as e:
                    ultimo_error = e
                    log(f"  ✗ {e}")
                    if _es_error_de_modelo(e):
                        break  # este modelo no sirve, probamos el siguiente
                    if _es_error_temporal(e):
                        time.sleep(30 * (intento + 1))
            if not hecho:
                if ultimo_error is not None and _es_error_de_modelo(ultimo_error) and len(modelos) > 1:
                    avisos.append(f"El modelo {modelo} no está disponible; se usó el siguiente de la lista.")
                    modelos.pop(0)
                    continue
                break
        if not hecho:
            raise ErrorVeo(f"No se pudo generar la escena {i}: {ultimo_error}")
        clips.append(destino)

    return ResultadoClips(clips, modelo_usado, segundos * len(clips), avisos)


def costo_estimado(cfg: dict, modelo: str, segundos: int) -> float | None:
    tabla = cfg.get("precios_usd_por_segundo", {}).get(modelo)
    if not isinstance(tabla, dict):
        return None
    precio = tabla.get(cfg["video"].get("resolucion", "1080p"))
    return round(precio * segundos, 2) if precio is not None else None
