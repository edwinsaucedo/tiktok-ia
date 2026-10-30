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


# ------------------------------------------------------------------ pausas en los cortes
# Al alargar en Flow (o encadenar escenas en el modo automático) cada parte arranca del último
# cuadro de la anterior: quedan instantes con la imagen congelada en los cortes. Aquí se detectan
# y se recortan (imagen y audio), sin dejar el video por debajo de un mínimo de duración.

def detectar_congelados(video: Path, ruido: float = 0.003, minimo: float = 0.25) -> list[tuple[float, float]]:
    """Intervalos (inicio, fin) en segundos donde la imagen no cambia."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-map", "0:v:0",
                        "-vf", f"freezedetect=n={ruido}:d={minimo}", "-f", "null", "-"],
                       capture_output=True, text=True)
    intervalos, inicio = [], None
    for linea in r.stderr.splitlines():
        if "freeze_start:" in linea:
            inicio = float(linea.rsplit(":", 1)[1])
        elif "freeze_end:" in linea and inicio is not None:
            intervalos.append((inicio, float(linea.rsplit(":", 1)[1])))
            inicio = None
    if inicio is not None:
        intervalos.append((inicio, duracion(video)))
    return intervalos


def planear_cortes(congelados: list[tuple[float, float]], total: float, minimo_total: float,
                   margen: float = 0.12, max_corte: float = 1.5) -> list[tuple[float, float]]:
    """Qué tramos quitar: de cada pausa se deja `margen` s y se quita hasta `max_corte` s,
    empezando por las pausas más largas y sin bajar de `minimo_total` segundos."""
    disponible = total - minimo_total
    if disponible <= 0:
        return []
    candidatos = []
    for inicio, fin in congelados:
        a = max(inicio + margen, fin - max_corte)
        if fin - a > 0.05:
            candidatos.append((a, fin))
    cortes = []
    for a, b in sorted(candidatos, key=lambda c: c[1] - c[0], reverse=True):
        if disponible <= 0.05:
            break
        largo = min(b - a, disponible)
        cortes.append((b - largo, b))
        disponible -= largo
    return sorted(cortes)


def quitar_pausas(video: Path, minimo_total: float = 61.0) -> tuple[Path, int, float]:
    """Recorta las pausas congeladas. Regresa (video, cuántas se quitaron, segundos quitados).
    Si no hay nada que quitar regresa el mismo archivo."""
    total = duracion(video)
    cortes = planear_cortes(detectar_congelados(video), total, minimo_total)
    if not cortes:
        return video, 0, 0.0
    tramos, actual = [], 0.0
    for a, b in cortes:
        if a - actual > 0.04:
            tramos.append((actual, a))
        actual = b
    if total - actual > 0.04:
        tramos.append((actual, total))
    con_audio = tiene_audio(video)
    partes = []
    for i, (a, b) in enumerate(tramos):
        partes.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        if con_audio:
            partes.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    entradas = "".join(f"[v{i}]" + (f"[a{i}]" if con_audio else "") for i in range(len(tramos)))
    partes.append(f"{entradas}concat=n={len(tramos)}:v=1:a={1 if con_audio else 0}[v]" + ("[a]" if con_audio else ""))
    destino = video.with_name(video.stem + "-sin-pausas.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-filter_complex", ";".join(partes),
           "-map", "[v]"]
    if con_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(destino)]
    subprocess.run(cmd, check=True)
    destino.replace(video)
    quitado = sum(b - a for a, b in cortes)
    log(f"Pausas quitadas en los cortes: {len(cortes)} ({quitado:.1f} s).")
    return video, len(cortes), quitado
