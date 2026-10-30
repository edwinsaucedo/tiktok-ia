"""Piezas compartidas por los dos modos (automático con Veo y videos de Flow):
subir a TikTok como borrador y escribir el aviso que se convierte en issue."""
from __future__ import annotations

import os
import traceback
from dataclasses import dataclass
from pathlib import Path

from . import tiktok
from .comun import env_requerida, escribir_salida_github, log


@dataclass
class ResultadoTikTok:
    publish_id: str | None = None
    estado: str | None = None
    error: str | None = None


def url_ejecucion() -> str:
    servidor = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    return f"{servidor}/{repo}/actions/runs/{run_id}" if repo and run_id else ""


def escribir_aviso(salida: Path, titulo: str, cuerpo: str) -> None:
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "aviso.md").write_text(cuerpo, encoding="utf-8")
    (salida / "aviso_titulo.txt").write_text(titulo[:200], encoding="utf-8")
    escribir_salida_github("aviso_titulo", titulo[:200])
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(f"# {titulo}\n\n{cuerpo}\n")
    log(f"\n=== {titulo} ===\n{cuerpo}")


def bloque_caption(idea: dict) -> str:
    caption = (idea.get("caption") or "").strip() or "(esta historia no tiene caption; escribe uno)"
    return f"```\n{caption}\n```"


def instrucciones_publicar(idea: dict) -> str:
    return ("### Para publicarlo\n"
            "1. Abre TikTok: te llegó una notificación en la **Bandeja de entrada** para terminar el borrador.\n"
            "2. Pega este caption:\n"
            f"{bloque_caption(idea)}\n"
            "3. En **Más opciones**, activa **Contenido generado por IA**.\n"
            "4. Publica.\n")


def subir_a_tiktok(video: Path, salida: Path, segundos_espera: int = 300) -> ResultadoTikTok:
    """Renueva el token, sube el video como borrador y espera a que llegue a la bandeja.
    Nunca lanza excepción: el error queda en ResultadoTikTok.error."""
    res = ResultadoTikTok()
    try:
        refresh_actual = env_requerida("TIKTOK_REFRESH_TOKEN")
        tokens = tiktok.refrescar_tokens(env_requerida("TIKTOK_CLIENT_KEY"),
                                         env_requerida("TIKTOK_CLIENT_SECRET"), refresh_actual)
        if tokens.refresh_token != refresh_actual:
            # TikTok puede rotar el refresh token: el workflow lo guarda en el secreto.
            (salida / "nuevo_refresh_token.txt").write_text(tokens.refresh_token)
        res.publish_id = tiktok.subir_borrador(video, tokens.access_token)
        res.estado = tiktok.esperar_estado(res.publish_id, tokens.access_token, segundos_espera)
        log(f"Estado en TikTok: {res.estado}")
    except Exception as e:
        traceback.print_exc()
        res.error = str(e)
    return res
