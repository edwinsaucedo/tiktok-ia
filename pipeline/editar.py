"""Unión de clips con ffmpeg: normaliza tamaño, une audio y video, y pone el texto gancho."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

from .comun import log

FUENTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TAMANOS = {"1080p": (1080, 1920), "720p": (720, 1280)}
FPS = 24


def tiene_audio(clip: Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "json", str(clip)],
        capture_output=True, text=True, check=True,
    )
    return bool(json.loads(r.stdout or "{}").get("streams"))


def duracion(clip: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(clip)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def _filtro_gancho(archivo_texto: Path, ancho: int, segundos: float, centrar: bool) -> str:
    tam = int(ancho * 0.066)
    opciones = [
        f"fontfile={FUENTE}",
        f"textfile={archivo_texto}",
        f"fontsize={tam}",
        f"line_spacing={int(tam * 0.25)}",
        "fontcolor=white",
        "box=1",
        "boxcolor=black@0.55",
        f"boxborderw={int(tam * 0.4)}",
        "x=(w-tw)/2",
        "y=h*0.14",
        f"enable='lt(t,{segundos})'",
    ]
    if centrar:
        opciones.append("text_align=C")
    return "drawtext=" + ":".join(opciones)


def _comando(clips: list[Path], destino: Path, ancho: int, alto: int,
             filtro_gancho: str | None) -> list[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    entradas_audio = {}
    for clip in clips:
        cmd += ["-i", str(clip)]
    siguiente = len(clips)
    for i, clip in enumerate(clips):
        if not tiene_audio(clip):
            cmd += ["-f", "lavfi", "-t", f"{duracion(clip):.3f}",
                    "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            entradas_audio[i] = siguiente
            siguiente += 1

    partes = []
    pares = []
    for i in range(len(clips)):
        partes.append(
            f"[{i}:v]scale={ancho}:{alto}:force_original_aspect_ratio=decrease,"
            f"pad={ancho}:{alto}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p[v{i}]"
        )
        origen_audio = entradas_audio.get(i, i)
        partes.append(
            f"[{origen_audio}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        )
        pares.append(f"[v{i}][a{i}]")
    partes.append(f"{''.join(pares)}concat=n={len(clips)}:v=1:a=1[vc][ac]")
    salida_video = "[vc]"
    if filtro_gancho:
        partes.append(f"[vc]{filtro_gancho}[vt]")
        salida_video = "[vt]"

    cmd += [
        "-filter_complex", ";".join(partes),
        "-map", salida_video, "-map", "[ac]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart",
        str(destino),
    ]
    return cmd


def unir(clips: list[Path], gancho: str | None, conf_video: dict, destino: Path) -> Path:
    if not clips:
        raise ValueError("No hay clips para unir.")
    ancho, alto = TAMANOS.get(conf_video.get("resolucion", "1080p"), TAMANOS["1080p"])
    destino.parent.mkdir(parents=True, exist_ok=True)

    filtro = None
    archivo_texto = destino.parent / "gancho.txt"
    gancho = (gancho or "").strip()
    usar_gancho = bool(gancho) and conf_video.get("texto_gancho", True)
    if usar_gancho:
        archivo_texto.write_text(textwrap.fill(gancho, width=22), encoding="utf-8")
        segundos = float(conf_video.get("segundos_texto_gancho", 3))
        filtro = _filtro_gancho(archivo_texto, ancho, segundos, centrar=True)

    log(f"Uniendo {len(clips)} clip(s) en {ancho}x{alto}…")
    try:
        subprocess.run(_comando(clips, destino, ancho, alto, filtro), check=True,
                       capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        if not usar_gancho:
            raise RuntimeError(f"ffmpeg falló: {e.stderr[-1500:]}") from e
        # Versiones viejas de ffmpeg no conocen text_align: reintento sin centrar líneas.
        log("ffmpeg falló con el texto centrado; reintento sin text_align…")
        filtro = _filtro_gancho(archivo_texto, ancho, float(conf_video.get("segundos_texto_gancho", 3)),
                                centrar=False)
        try:
            subprocess.run(_comando(clips, destino, ancho, alto, filtro), check=True,
                           capture_output=True, text=True)
        except subprocess.CalledProcessError as e2:
            raise RuntimeError(f"ffmpeg falló: {e2.stderr[-1500:]}") from e2

    log(f"Video final: {destino.name} ({destino.stat().st_size / 1e6:.1f} MB, {duracion(destino):.1f} s)")
    return destino
