"""Subida a TikTok como BORRADOR (Content Posting API, modo Upload / bandeja de entrada).

El video llega como notificación a tu app de TikTok; tú lo abres, pegas el caption y publicas.
Usa el permiso `video.upload`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .comun import log, ocultar_en_log

API = os.environ.get("TIKTOK_API_BASE", "https://open.tiktokapis.com").rstrip("/")

MB = 1024 * 1024
CHUNK_MIN = 5 * MB
CHUNK_MAX = 64 * MB
CHUNK_PREFERIDO = 10 * MB


class ErrorTikTok(RuntimeError):
    pass


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    open_id: str
    scope: str


def refrescar_tokens(client_key: str, client_secret: str, refresh_token: str) -> Tokens:
    r = requests.post(
        f"{API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=60,
    )
    datos = _json(r)
    if "access_token" not in datos:
        raise ErrorTikTok(
            "No se pudo renovar el acceso a TikTok "
            f"({datos.get('error')}: {datos.get('error_description')}). "
            "Si el refresh token caducó o lo revocaste, vuelve a correr tools/tiktok_login.py."
        )
    ocultar_en_log(datos["access_token"])
    ocultar_en_log(datos.get("refresh_token", ""))
    scope = datos.get("scope", "")
    if scope and "video.upload" not in scope:
        raise ErrorTikTok(
            f"El token no tiene el permiso video.upload (tiene: {scope}). "
            "Agrega Content Posting API a tu app y vuelve a correr tools/tiktok_login.py."
        )
    return Tokens(
        access_token=datos["access_token"],
        refresh_token=datos.get("refresh_token") or refresh_token,
        open_id=datos.get("open_id", ""),
        scope=scope,
    )


def plan_chunks(tamano: int) -> tuple[int, int]:
    """Devuelve (chunk_size, total_chunk_count) según las reglas de TikTok:
    chunks de 5 a 64 MB, el último puede llegar a 128 MB, total = tamaño // chunk (redondeo hacia abajo).
    Archivos de hasta 64 MB se suben en un solo pedazo."""
    if tamano <= 0:
        raise ValueError("El archivo está vacío.")
    if tamano <= CHUNK_MAX:
        return tamano, 1
    chunk = CHUNK_PREFERIDO
    total = tamano // chunk
    if total > 1000:
        raise ValueError("El video es demasiado grande para subirlo a TikTok.")
    return chunk, total


def rangos(tamano: int, chunk: int, total: int) -> list[tuple[int, int]]:
    """Rangos de bytes (inicio, fin inclusive). El último absorbe el sobrante."""
    salida = []
    for i in range(total):
        inicio = i * chunk
        fin = tamano - 1 if i == total - 1 else inicio + chunk - 1
        salida.append((inicio, fin))
    return salida


def _json(r: requests.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        raise ErrorTikTok(f"Respuesta inesperada de TikTok (HTTP {r.status_code}): {r.text[:300]}")


def _revisar(datos: dict, accion: str) -> dict:
    error = datos.get("error") or {}
    codigo = error.get("code", "ok")
    if codigo != "ok":
        pistas = {
            "spam_risk_too_many_pending_share": "Tienes demasiados borradores pendientes en TikTok "
            "(máximo 5). Publica o borra algunos desde la app.",
            "scope_not_authorized": "Falta el permiso video.upload; vuelve a correr tools/tiktok_login.py.",
            "access_token_invalid": "El token de acceso no es válido; revisa TIKTOK_REFRESH_TOKEN.",
            "rate_limit_exceeded": "Demasiadas peticiones; se reintentará en la próxima ejecución.",
        }
        pista = pistas.get(codigo, "")
        raise ErrorTikTok(
            f"TikTok rechazó '{accion}': {codigo} - {error.get('message', '')}. {pista}".strip()
        )
    return datos.get("data") or {}


def subir_borrador(video: Path, access_token: str) -> str:
    """Sube el video a la bandeja de TikTok y devuelve el publish_id."""
    tamano = video.stat().st_size
    chunk, total = plan_chunks(tamano)
    cab = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"}
    r = requests.post(
        f"{API}/v2/post/publish/inbox/video/init/",
        headers=cab,
        json={"source_info": {"source": "FILE_UPLOAD", "video_size": tamano,
                              "chunk_size": chunk, "total_chunk_count": total}},
        timeout=60,
    )
    datos = _revisar(_json(r), "iniciar subida")
    publish_id, upload_url = datos.get("publish_id"), datos.get("upload_url")
    if not publish_id or not upload_url:
        raise ErrorTikTok(f"TikTok no devolvió publish_id/upload_url: {datos}")

    log(f"Subiendo {tamano / 1e6:.1f} MB a TikTok en {total} parte(s)…")
    with open(video, "rb") as f:
        for n, (inicio, fin) in enumerate(rangos(tamano, chunk, total), start=1):
            f.seek(inicio)
            pedazo = f.read(fin - inicio + 1)
            for intento in range(3):
                resp = requests.put(
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(pedazo)),
                        "Content-Range": f"bytes {inicio}-{fin}/{tamano}",
                    },
                    data=pedazo,
                    timeout=300,
                )
                if resp.status_code in (200, 201, 206):
                    break
                log(f"  parte {n}: HTTP {resp.status_code}, reintento {intento + 1}…")
                time.sleep(5 * (intento + 1))
            else:
                raise ErrorTikTok(f"No se pudo subir la parte {n}: HTTP {resp.status_code} {resp.text[:200]}")
    return publish_id


def esperar_estado(publish_id: str, access_token: str, segundos_max: int = 300) -> str:
    """Consulta el estado hasta que TikTok lo mande a tu bandeja (SEND_TO_USER_INBOX) o falle."""
    cab = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"}
    limite = time.monotonic() + segundos_max
    estado = "DESCONOCIDO"
    while time.monotonic() < limite:
        r = requests.post(f"{API}/v2/post/publish/status/fetch/", headers=cab,
                          json={"publish_id": publish_id}, timeout=60)
        datos = _revisar(_json(r), "consultar estado")
        estado = datos.get("status", "DESCONOCIDO")
        if estado in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return estado
        if estado == "FAILED":
            raise ErrorTikTok(f"TikTok no pudo procesar el video: {datos.get('fail_reason', 'sin motivo')}")
        time.sleep(5)
    return estado
