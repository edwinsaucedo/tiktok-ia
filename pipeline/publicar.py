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


@dataclass
class Entrega:
    """Resultado de entregar el video: borrador en TikTok y/o mensaje en Telegram."""
    tiktok: ResultadoTikTok | None = None
    telegram: "telegram.ResultadoTelegram | None" = None

    @property
    def tiktok_ok(self) -> bool:
        return self.tiktok is not None and not self.tiktok.error

    @property
    def telegram_ok(self) -> bool:
        return self.telegram is not None and self.telegram.enviado

    @property
    def entregado(self) -> bool:
        return self.tiktok_ok or self.telegram_ok

    @property
    def intentado(self) -> bool:
        return self.tiktok is not None or self.telegram is not None

    @property
    def estado(self) -> str:
        if self.tiktok_ok:
            return "borrador_en_tiktok"
        if self.telegram_ok:
            return "enviado_por_telegram"
        return "generado_sin_subir" if self.intentado else "generado"


def entregar(video: Path, idea: dict, titulo: str, salida: Path, cfg: dict,
             subir_tiktok: bool) -> Entrega:
    """Manda el video por los canales activos. Nunca lanza excepción."""
    from . import telegram

    e = Entrega()
    if subir_tiktok:
        e.tiktok = subir_a_tiktok(video, salida, int(cfg.get("tiktok", {}).get("segundos_espera_estado", 300)))
    if cfg.get("telegram", {}).get("activo", False):
        e.telegram = telegram.enviar(video, titulo, idea.get("caption", ""))
        if e.telegram.chat_id_nuevo:
            (salida / "nuevo_telegram_chat_id.txt").write_text(e.telegram.chat_id_nuevo)
    return e


def aviso_de_entrega(e: Entrega, idea: dict, titulo: str, datos: str, pie: str,
                     prefijo: str = "") -> tuple[str, str, int]:
    """Arma (título, cuerpo, código de salida) del aviso según cómo se entregó el video."""
    lineas = []
    if e.tiktok is not None:
        lineas.append(f"📥 TikTok: borrador enviado (estado `{e.tiktok.estado}`)." if e.tiktok_ok
                      else f"⚠️ **TikTok:** {e.tiktok.error}")
    if e.telegram is not None:
        lineas.append("📲 Telegram: te mandé el video y el caption." if e.telegram_ok
                      else f"⚠️ **Telegram:** {e.telegram.error}")
    canales = ("\n\n" + "\n\n".join(lineas)) if lineas else ""

    if e.tiktok_ok:
        return (f"{prefijo}🎬 Borrador listo en TikTok: {titulo}",
                f"{datos}{canales}\n\n{instrucciones_publicar(idea)}{pie}", 0)
    if e.telegram_ok:
        return (f"{prefijo}📲 Video listo en Telegram: {titulo}",
                f"{datos}{canales}\n\n### Para publicarlo\n"
                "Abre el chat de tu bot en Telegram: guarda el video, súbelo en TikTok, pega el caption "
                "(está en el mensaje, tócalo para copiarlo) y activa **Contenido generado por IA**.\n\n"
                f"Caption:\n{bloque_caption(idea)}{pie}", 0)
    if e.intentado:
        return (f"{prefijo}⚠️ Video listo pero no se pudo entregar: {titulo}",
                f"{datos}{canales}\n\nDescarga el video desde el link de abajo y súbelo a mano con este "
                f"caption:\n{bloque_caption(idea)}{pie}", 1)
    return (f"{prefijo}🎬 Video generado: {titulo}",
            f"{datos}\n\nNo hay canales de entrega activos (TikTok y Telegram apagados).\n\n"
            f"Caption:\n{bloque_caption(idea)}{pie}", 0)


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
