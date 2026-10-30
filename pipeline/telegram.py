"""Entrega por Telegram: te manda el video listo y el caption (toca el texto para copiarlo).

Configuración (una vez):
  1. En Telegram habla con @BotFather → /newbot → elige nombre y usuario → te da un TOKEN.
  2. Abre tu bot nuevo y mándale /start.
  3. Guarda el TOKEN en GitHub como secreto TELEGRAM_BOT_TOKEN.
  El ID de tu chat se detecta solo la primera vez y se guarda como secreto TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import html
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import requests

from .comun import log, ocultar_en_log

API = os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
LIMITE_BYTES = 48 * 1024 * 1024   # los bots de Telegram aceptan archivos de hasta 50 MB


class ErrorTelegram(RuntimeError):
    pass


@dataclass
class ResultadoTelegram:
    enviado: bool = False
    error: str | None = None
    chat_id_nuevo: str | None = None


def _url(token: str, metodo: str) -> str:
    return f"{API}/bot{token}/{metodo}"


def _revisar(r: requests.Response, accion: str) -> dict:
    try:
        datos = r.json()
    except ValueError:
        raise ErrorTelegram(f"Telegram respondió algo inesperado al {accion} (HTTP {r.status_code}).")
    if not datos.get("ok"):
        desc = datos.get("description", "")
        pista = ""
        if r.status_code == 401:
            pista = " Revisa el secreto TELEGRAM_BOT_TOKEN (cópialo otra vez de @BotFather)."
        elif "chat not found" in desc.lower() or r.status_code == 403:
            pista = " Abre tu bot en Telegram y mándale /start."
        raise ErrorTelegram(f"Telegram rechazó {accion}: {desc}.{pista}")
    return datos.get("result")


def descubrir_chat_id(token: str) -> str:
    """Busca el chat privado más reciente que le escribió al bot (por ejemplo con /start)."""
    r = requests.get(_url(token, "getUpdates"), params={"timeout": 0}, timeout=30)
    actualizaciones = _revisar(r, "leer los mensajes del bot") or []
    for upd in reversed(actualizaciones):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and chat.get("id") is not None:
            return str(chat["id"])
    raise ErrorTelegram("No encontré tu chat: abre tu bot en Telegram, mándale /start y vuelve a correr "
                        "el workflow (Telegram solo guarda esos mensajes 24 horas).")


def _duracion(video: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
                        str(video)], capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def ajustar_tamano(video: Path, limite: int = LIMITE_BYTES) -> Path:
    """Si el video pasa del límite de Telegram, hace una copia más ligera (misma resolución)."""
    if video.stat().st_size <= limite:
        return video
    segundos = max(1.0, _duracion(video))
    kbps = int((limite * 8 / 1000) / segundos * 0.85) - 128   # margen y 128 kbps de audio
    destino = video.with_name(video.stem + "-telegram.mp4")
    log(f"El video pesa {video.stat().st_size / 1e6:.1f} MB; preparo una copia más ligera para Telegram…")
    for _ in range(3):  # el codificador a veces se pasa un poco: se ajusta y se reintenta
        kbps = max(500, min(kbps, 8000))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
                        "-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{kbps}k",
                        "-maxrate", f"{kbps}k", "-bufsize", f"{kbps}k", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destino)], check=True)
        tam = destino.stat().st_size
        if tam <= limite:
            return destino
        kbps = int(kbps * limite / tam * 0.9)
    if destino.stat().st_size > 50 * 1024 * 1024:
        raise ErrorTelegram("El video sigue pesando más de 50 MB; descárgalo desde el aviso de GitHub.")
    return destino


def mensaje_instrucciones(titulo: str, caption: str) -> str:
    caption = caption.strip() or "(esta historia no tiene caption; escribe uno)"
    return (
        f"🎬 <b>{html.escape(titulo)}</b>\n\n"
        "<b>Para publicarlo:</b>\n"
        "1. Mantén presionado el video de arriba → <b>Guardar</b> (en Fotos o Galería).\n"
        "2. En TikTok toca <b>+</b> y súbelo.\n"
        "3. Toca el texto de abajo para copiarlo y pégalo como descripción:\n\n"
        f"<code>{html.escape(caption)}</code>\n\n"
        "4. En <b>Más opciones</b> activa <b>Contenido generado por IA</b> y publica."
    )


def enviar(video: Path, titulo: str, caption: str) -> ResultadoTelegram:
    """Manda el video y las instrucciones. Nunca lanza excepción: el error queda en el resultado."""
    res = ResultadoTelegram()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        res.error = "Falta el secreto TELEGRAM_BOT_TOKEN."
        return res
    ocultar_en_log(token)
    try:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not chat_id:
            chat_id = descubrir_chat_id(token)
            res.chat_id_nuevo = chat_id
            log("Encontré tu chat de Telegram; se guardará como secreto TELEGRAM_CHAT_ID.")
        archivo = ajustar_tamano(video)
        log(f"Enviando a Telegram ({archivo.stat().st_size / 1e6:.1f} MB)…")
        with open(archivo, "rb") as f:
            r = requests.post(_url(token, "sendVideo"),
                              data={"chat_id": chat_id, "supports_streaming": "true",
                                    "caption": f"🎬 {titulo}"[:1000]},
                              files={"video": (archivo.name, f, "video/mp4")}, timeout=600)
        _revisar(r, "recibir el video")
        r = requests.post(_url(token, "sendMessage"),
                          data={"chat_id": chat_id, "parse_mode": "HTML",
                                "text": mensaje_instrucciones(titulo, caption)}, timeout=60)
        _revisar(r, "recibir el caption")
        res.enviado = True
        log("✓ Video enviado por Telegram.")
    except Exception as e:  # el pipeline sigue y lo reporta en el aviso
        # Los errores de conexión traen la URL completa (con el token): nunca la dejamos pasar al aviso.
        res.error = str(e).replace(token, "***")
        log(f"✗ Telegram: {res.error}")
    return res
