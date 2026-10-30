"""Modo Flow: toma los videos que generas en Google Flow y subes a Google Drive.

En tu Drive:
    TikTok IA/
      001 - El anillo equivocado/    <- aquí subes el video que descargaste de Flow
        Guion para Flow (documento con las 8 partes)
      002 - La herencia/
      ...

Cada hora el workflow revisa las carpetas "NNN - Título". Cuando una tiene video y lleva
unos minutos sin cambios (para no agarrarla a medio subir):
  1. Descarga el video (o los clips, si subiste varios: se unen en orden por nombre).
  2. Le pone el texto gancho de la historia NNN (ideas/flow/NNN-*.json).
  3. Lo manda a TikTok como borrador y te avisa con el caption.
  4. Renombra la carpeta: "✅ 001 - …" si salió bien, "⚠️ 001 - …" o "❌ 001 - …" si no.
     Para reintentar, quítale el ⚠️/❌ al nombre de la carpeta.

Uso:  python -m pipeline.flow            (procesa una carpeta lista)
      python -m pipeline.flow --revisar  (solo dice si hay trabajo; no descarga nada)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import editar, ideas, publicar
from .comun import CARPETA_SALIDA, RAIZ, cargar_config, escribir_salida_github, log
from .drive import CARPETA, Drive, es_video

CARPETA_FLOW = RAIZ / "ideas" / "flow"
REGISTRO = RAIZ / "ideas" / "flow_procesadas.json"
PATRON = re.compile(r"^\s*(\d{3})\s*-")


@dataclass
class Pendiente:
    carpeta: dict
    numero: str
    videos: list[dict]


def _fecha(texto: str) -> datetime:
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def _leer_registro() -> dict:
    if REGISTRO.exists():
        try:
            return json.loads(REGISTRO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _guardar_registro(registro: dict) -> None:
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def buscar_listas(drive: Drive, raiz_id: str, minutos_espera: int,
                  ahora: datetime | None = None) -> list[Pendiente]:
    ahora = ahora or datetime.now(timezone.utc)
    registro = _leer_registro()
    listas = []
    for item in drive.listar(raiz_id):
        if item.get("mimeType") != CARPETA:
            continue
        m = PATRON.match(item.get("name", ""))
        if not m:
            continue  # carpetas ya marcadas (✅ ⚠️ ❌) u otras que no son historias
        videos = [a for a in drive.listar(item["id"]) if es_video(a)]
        if not videos:
            continue
        previo = registro.get(item["id"])
        if previo and previo.get("estado") == "borrador_en_tiktok" and \
                sorted(previo.get("videos", [])) == sorted(v["id"] for v in videos):
            # Ya se mandó a TikTok pero no se pudo renombrar la carpeta: no la repetimos.
            log(f"'{item['name']}' ya se procesó antes; se omite.")
            continue
        ultimo = max(_fecha(v.get("modifiedTime") or v["createdTime"]) for v in videos)
        if ahora - ultimo < timedelta(minutes=minutos_espera):
            log(f"'{item['name']}' tiene archivos muy recientes; se revisa en la próxima ejecución.")
            continue
        listas.append(Pendiente(item, m.group(1), sorted(videos, key=lambda v: v["name"].lower())))
    return sorted(listas, key=lambda p: p.numero)


def buscar_historia(numero: str) -> tuple[Path | None, dict | None]:
    """Busca la historia NNN en ideas/flow/ (pendiente) o en ideas/hechas/ (si se reintenta)."""
    for carpeta in (CARPETA_FLOW, ideas.CARPETA_HECHAS):
        for ruta in sorted(carpeta.glob(f"{numero}-*.json")):
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            return (ruta if carpeta == CARPETA_FLOW else None), datos
    return None, None


def _dimensiones(video: Path) -> tuple[int, int]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", str(video)],
                       capture_output=True, text=True)
    try:
        s = json.loads(r.stdout or "{}")["streams"][0]
        return int(s["width"]), int(s["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        raise RuntimeError("El archivo no se pudo leer como video (¿está incompleto o dañado?). "
                           "Vuelve a descargarlo de Flow y súbelo otra vez.") from None


def _renombrar_seguro(drive: Drive, carpeta: dict, nombre: str) -> str | None:
    try:
        drive.renombrar(carpeta["id"], nombre)
        return None
    except Exception as e:
        return str(e)


def main(argv: list[str]) -> int:
    solo_revisar = "--revisar" in argv
    cfg = cargar_config()
    conf_flow = cfg.get("flow", {})
    raiz_id = (conf_flow.get("carpeta_drive_id") or "").strip()
    if not raiz_id:
        log("flow.carpeta_drive_id está vacío en config.json; el modo Flow está apagado.")
        escribir_salida_github("hay_trabajo", "0")
        return 0

    drive = Drive()
    listas = buscar_listas(drive, raiz_id, int(conf_flow.get("minutos_espera", 10)))
    escribir_salida_github("hay_trabajo", "1" if listas else "0")
    log(f"Carpetas listas para procesar: {len(listas)}")
    if solo_revisar or not listas:
        return 0

    p = listas[0]  # una por ejecución; las demás salen en las siguientes horas
    nombre = p.carpeta["name"]
    ruta, idea = buscar_historia(p.numero)
    avisos: list[str] = []
    if idea is None:
        avisos.append(f"No encontré la historia {p.numero} en el repositorio: se subió sin texto gancho "
                      "ni caption.")
        idea = {"id": f"{p.numero}-flow", "titulo": nombre, "caption": "", "gancho": ""}
    titulo = idea.get("titulo") or nombre
    url = publicar.url_ejecucion()

    if CARPETA_SALIDA.exists():
        shutil.rmtree(CARPETA_SALIDA)
    CARPETA_SALIDA.mkdir(parents=True)

    # 1) Descargar y preparar ------------------------------------------------------------
    try:
        locales = []
        for i, v in enumerate(p.videos, start=1):
            ext = Path(v["name"]).suffix.lower() or ".mp4"
            log(f"Descargando {v['name']}…")
            locales.append(drive.descargar(v["id"], CARPETA_SALIDA / "descargas" / f"{i:02d}{ext}"))
        ancho, alto = _dimensiones(locales[0])
        if ancho > alto:
            avisos.append("El video venía **horizontal**: se acomodó en vertical con franjas. "
                          "En Flow elige formato **9:16** antes de generar.")
        conf_video = dict(cfg["video"], resolucion=conf_flow.get("resolucion", "1080p"),
                          texto_gancho=conf_flow.get("texto_gancho", True))
        video = editar.unir(locales, idea.get("gancho"), conf_video, CARPETA_SALIDA / f"{idea['id']}.mp4")
        duracion = editar.duracion(video)
    except Exception as e:
        traceback.print_exc()
        err = _renombrar_seguro(drive, p.carpeta, f"❌ {nombre}")
        publicar.escribir_aviso(
            CARPETA_SALIDA, f"❌ No se pudo preparar el video de Flow: {titulo}",
            f"**Error:** {e}\n\nLa carpeta de Drive quedó como `❌ {nombre}`. Revisa que el archivo sea un "
            "video completo y quítale el ❌ al nombre para reintentar." + (f"\n\n(No pude renombrarla: {err})" if err else "")
            + f"\n\nDetalle: {url}")
        return 1

    if duracion < 60:
        avisos.append(f"Dura {duracion:.0f} s: el programa de Recompensas de TikTok pide más de 1 minuto.")
    escribir_salida_github("video", str(video.relative_to(CARPETA_SALIDA.parent)))

    # 2) TikTok ---------------------------------------------------------------------------
    subir = bool(cfg.get("tiktok", {}).get("subir", True))
    r = publicar.ResultadoTikTok()
    if subir:
        r = publicar.subir_a_tiktok(video, CARPETA_SALIDA,
                                    int(cfg.get("tiktok", {}).get("segundos_espera_estado", 300)))
    ok = subir and not r.error
    estado = "borrador_en_tiktok" if ok else ("generado" if not subir else "generado_sin_subir")

    # 3) Registro y carpeta de Drive ------------------------------------------------------
    registro = _leer_registro()
    registro[p.carpeta["id"]] = {
        "carpeta": nombre, "historia": idea["id"], "estado": estado,
        "videos": [v["id"] for v in p.videos],
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _guardar_registro(registro)
    if ruta is not None and ok:
        ideas.marcar_hecha(ruta, idea, estado, {
            "modo": "flow", "carpeta_drive": nombre, "segundos": round(duracion, 1),
            "publish_id": r.publish_id, "estado_tiktok": r.estado, "ejecucion": url})

    err_nombre = _renombrar_seguro(drive, p.carpeta, f"{'✅' if ok else '⚠️'} {nombre}")
    if err_nombre:
        avisos.append(f"No pude renombrar la carpeta de Drive: {err_nombre}")

    # 4) Aviso ----------------------------------------------------------------------------
    datos = f"**Historia:** {titulo}  \n**Origen:** Flow (Drive: `{nombre}`) · **Duración:** {duracion:.0f} s"
    extra = "".join(f"\n> ⚠️ {a}" for a in avisos)
    descarga = f"\n\n📥 Video descargable 7 días (sección *Artifacts*): {url}" if url else ""
    pendientes = sum(1 for _ in CARPETA_FLOW.glob("*.json"))
    resto = f"\n\n🗂️ Historias para Flow que siguen pendientes: **{pendientes}**"

    if not subir:
        publicar.escribir_aviso(CARPETA_SALIDA, f"🎬 Video de Flow listo: {titulo}",
                                f"{datos}{extra}\n\nNo se subió a TikTok (subida desactivada).\n\n"
                                f"Caption:\n{publicar.bloque_caption(idea)}{descarga}{resto}")
        return 0
    if r.error:
        publicar.escribir_aviso(
            CARPETA_SALIDA, f"⚠️ Video de Flow listo pero no llegó a TikTok: {titulo}",
            f"{datos}{extra}\n\n**Error de TikTok:** {r.error}\n\nLa carpeta quedó como `⚠️ {nombre}`. "
            "Para reintentar, quítale el ⚠️ al nombre. O descarga el video y súbelo a mano con este caption:\n"
            f"{publicar.bloque_caption(idea)}{descarga}{resto}")
        return 1
    publicar.escribir_aviso(
        CARPETA_SALIDA, f"🎬 Borrador listo en TikTok: {titulo}",
        f"{datos}{extra}\n\n{publicar.instrucciones_publicar(idea)}"
        f"\nEstado reportado por TikTok: `{r.estado}`{descarga}{resto}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        traceback.print_exc()
        if "--revisar" in sys.argv:
            # La revisión corre cada hora: no la marcamos como fallida para no llenarte de correos.
            from .comun import aviso_github
            aviso_github("warning", f"No se pudo revisar Google Drive: {e}")
            escribir_salida_github("hay_trabajo", "0")
            sys.exit(0)
        publicar.escribir_aviso(CARPETA_SALIDA, "❌ Error en el modo Flow",
                                f"```\n{e}\n```\n\n{publicar.url_ejecucion()}")
        sys.exit(1)
