"""Ejecución diaria: toma la siguiente idea, genera el video y lo manda a TikTok como borrador.

Variables de entorno:
  GCP_PROJECT            ID del proyecto de Google Cloud (Vertex AI)
  TIKTOK_CLIENT_KEY      Client key de tu app de TikTok for Developers
  TIKTOK_CLIENT_SECRET   Client secret de tu app
  TIKTOK_REFRESH_TOKEN   Refresh token que te da tools/tiktok_login.py
  SIMULAR=1              Crea clips de prueba con ffmpeg (no gasta créditos de Google)
  NO_SUBIR=1             No sube a TikTok (solo genera el video)
"""
from __future__ import annotations

import os
import shutil
import sys
import traceback

from . import editar, ideas, publicar, veo
from .comun import (CARPETA_SALIDA, aviso_github, cargar_config, es_verdadero,
                    escribir_salida_github, log)

IDEA_DEMO = {
    "id": "demo-simulada",
    "titulo": "Video de prueba (simulado)",
    "gancho": "Esto es una prueba del sistema",
    "estilo": "",
    "escenas": ["Escena de prueba 1", "Escena de prueba 2"],
    "caption": "Prueba del sistema automático #prueba",
}


_url_ejecucion = publicar.url_ejecucion
_bloque_caption = publicar.bloque_caption


def _escribir_aviso(titulo: str, cuerpo: str) -> None:
    publicar.escribir_aviso(CARPETA_SALIDA, titulo, cuerpo)


def main() -> int:
    cfg = cargar_config()
    simular = es_verdadero(os.environ.get("SIMULAR"))
    subir = bool(cfg.get("tiktok", {}).get("subir", True)) and not es_verdadero(os.environ.get("NO_SUBIR"))
    proyecto = os.environ.get("GCP_PROJECT", "").strip() or None
    url = _url_ejecucion()

    if not simular and not cfg.get("modo_automatico", {}).get("activo", True):
        log("El modo automático está apagado (config.json → modo_automatico.activo = false). No se hace nada.")
        return 0

    if CARPETA_SALIDA.exists():
        shutil.rmtree(CARPETA_SALIDA)
    CARPETA_SALIDA.mkdir(parents=True)

    # 0) Tope de gasto mensual ---------------------------------------------------------
    tope = cfg.get("presupuesto", {}).get("tope_mensual_usd")
    if not simular and tope is not None:
        conf_v = cfg["video"]
        estimado = veo.costo_estimado(
            cfg, (conf_v.get("modelos") or [""])[0],
            int(conf_v.get("segundos_por_clip", 8)) * int(conf_v.get("max_clips_por_video", 1))) or 0
        gastado = ideas.gasto_del_mes()
        if gastado + estimado > float(tope):
            _escribir_aviso(
                "💸 Tope de gasto del mes alcanzado",
                f"Este mes llevas **${gastado:.2f} USD** (estimado) y el siguiente video costaría "
                f"~${estimado:.2f}. El tope en `config.json` es **${float(tope):.2f}**, así que hoy no "
                "se generó video. Se reanuda solo el día 1 del próximo mes, o sube el tope si quieres.",
            )
            return 0

    # 1) Idea -------------------------------------------------------------------------
    seleccion = ideas.siguiente()
    es_demo = False
    if seleccion is None:
        if simular:
            seleccion, es_demo = (None, IDEA_DEMO), True
        elif cfg.get("ideas", {}).get("respaldo_gemini") and proyecto:
            try:
                seleccion = ideas.generar_idea_respaldo(cfg, proyecto)
            except Exception as e:
                aviso_github("warning", str(e))
        if seleccion is None:
            _escribir_aviso(
                "📭 La cola de ideas está vacía",
                "No hay ideas en `ideas/cola/` y no se pudo crear una de respaldo, así que hoy no se "
                "generó video.\n\nPídele a Claude más ideas o agrega archivos JSON a `ideas/cola/`.",
            )
            return 0
    ruta, idea = seleccion
    titulo = idea.get("titulo") or idea["id"]
    log(f"Idea: {titulo} ({len(idea['escenas'])} escena(s))" + (" [simulación]" if simular else ""))

    # 2) Video ------------------------------------------------------------------------
    try:
        res = veo.generar_clips(idea, cfg, CARPETA_SALIDA / "clips", proyecto, simular)
        video = editar.unir(res.clips, idea.get("gancho"), cfg["video"],
                            CARPETA_SALIDA / f"{idea['id']}.mp4")
    except Exception as e:
        traceback.print_exc()
        estado = "simulacion"
        if not simular and ruta is not None:
            estado = ideas.registrar_fallo(ruta, idea, str(e),
                                           int(cfg.get("ideas", {}).get("intentos_max_por_idea", 2)))
        siguiente_paso = ("Se volverá a intentar en la próxima ejecución." if estado == "reintentar"
                          else "La idea salió de la cola (se guardó en `ideas/hechas/` con el error).")
        _escribir_aviso(
            f"❌ No se pudo generar el video: {titulo}",
            f"**Error:** {e}\n\n{siguiente_paso}\n\nDetalle: {url}",
        )
        return 1

    escribir_salida_github("video", str(video.relative_to(CARPETA_SALIDA.parent)))
    costo = None if simular else veo.costo_estimado(cfg, res.modelo, res.segundos)
    texto_costo = f"${costo:.2f} USD (estimado)" if costo is not None else "—"

    # 3) TikTok -----------------------------------------------------------------------
    publish_id, estado_tiktok, error_tiktok = None, None, None
    if subir:
        r = publicar.subir_a_tiktok(video, CARPETA_SALIDA,
                                    int(cfg.get("tiktok", {}).get("segundos_espera_estado", 300)))
        publish_id, estado_tiktok, error_tiktok = r.publish_id, r.estado, r.error

    # 4) Registro de la cola ------------------------------------------------------------
    if not simular and ruta is not None:
        if not subir:
            estado = "generado"
        elif error_tiktok:
            estado = "generado_sin_subir"
        else:
            estado = "borrador_en_tiktok"
        ideas.marcar_hecha(ruta, idea, estado, {
            "modelo": res.modelo, "segundos": res.segundos, "costo_estimado_usd": costo,
            "publish_id": publish_id, "estado_tiktok": estado_tiktok, "error_tiktok": error_tiktok,
            "ejecucion": url,
        })

    # 5) Aviso --------------------------------------------------------------------------
    quedan = ideas.cuantas_en_cola()
    datos = (f"**Idea:** {titulo}  \n**Escenas:** {len(res.clips)} · **Duración:** {res.segundos} s · "
             f"**Modelo:** {res.modelo} · **Costo:** {texto_costo}")
    extra = "".join(f"\n> ⚠️ {a}" for a in res.avisos)
    descarga = f"\n\n📥 Video descargable 7 días (sección *Artifacts*): {url}" if url else ""
    cola = f"\n\n🗂️ Ideas que quedan en la cola: **{quedan}**" + (
        " — pídele más a Claude." if quedan < 3 and not es_demo else "")
    prefijo = "[SIMULACIÓN] " if simular else ""

    if not subir:
        _escribir_aviso(f"{prefijo}🎬 Video generado: {titulo}",
                        f"{datos}{extra}\n\nNo se subió a TikTok (subida desactivada).\n\n"
                        f"Caption sugerido:\n{_bloque_caption(idea)}{descarga}{cola}")
        return 0
    if error_tiktok:
        _escribir_aviso(
            f"{prefijo}⚠️ Video listo pero no llegó a TikTok: {titulo}",
            f"{datos}{extra}\n\n**Error de TikTok:** {error_tiktok}\n\n"
            f"Puedes descargar el video y subirlo a mano con este caption:\n{_bloque_caption(idea)}"
            f"{descarga}{cola}")
        return 1

    _escribir_aviso(
        f"{prefijo}🎬 Borrador listo en TikTok: {titulo}",
        f"{datos}{extra}\n\n{publicar.instrucciones_publicar(idea)}"
        f"\nEstado reportado por TikTok: `{estado_tiktok}`{descarga}{cola}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # cualquier error inesperado también genera aviso
        traceback.print_exc()
        _escribir_aviso("❌ Error inesperado en el pipeline", f"```\n{e}\n```\n\n{_url_ejecucion()}")
        sys.exit(1)
