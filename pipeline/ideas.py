"""Cola de ideas: un archivo JSON por idea en ideas/cola/, procesadas en orden alfabético.

Formato de cada idea (ideas/cola/AAAA-MM-DD-x.json):
{
  "id": "2026-11-02-a",
  "titulo": "Título interno corto",
  "gancho": "Texto que aparece en pantalla los primeros segundos",
  "estilo": "Estilo visual común a todas las escenas (para que se vean coherentes)",
  "escenas": ["Prompt de la escena 1", "Prompt de la escena 2"],
  "caption": "Descripción para TikTok con #hashtags"
}
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .comun import CARPETA_COLA, CARPETA_HECHAS, log

CAMPOS_TEXTO = ("id", "caption")
MAX_CAPTION = 2200  # límite de caracteres de TikTok


def validar(idea: dict) -> list[str]:
    errores = []
    if not isinstance(idea, dict):
        return ["la idea no es un objeto JSON"]
    for campo in CAMPOS_TEXTO:
        if not isinstance(idea.get(campo), str) or not idea[campo].strip():
            errores.append(f"falta el campo '{campo}'")
    escenas = idea.get("escenas")
    if not isinstance(escenas, list) or not escenas or not all(
        isinstance(e, str) and e.strip() for e in escenas
    ):
        errores.append("'escenas' debe ser una lista con al menos un texto")
    if isinstance(idea.get("caption"), str) and len(idea["caption"]) > MAX_CAPTION:
        errores.append(f"el caption pasa de {MAX_CAPTION} caracteres")
    if isinstance(idea.get("id"), str) and not re.fullmatch(r"[A-Za-z0-9_.-]+", idea["id"]):
        errores.append("el id solo puede tener letras, números, punto, guion y guion bajo")
    return errores


def _leer(ruta: Path) -> dict | None:
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"No pude leer {ruta.name}: {e}")
        return None


def _guardar(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _mover_a_hechas(ruta: Path, idea: dict, estado: str, datos: dict) -> Path:
    idea = dict(idea)
    idea["resultado"] = {
        "estado": estado,
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **datos,
    }
    nombre = ruta.name if ruta.suffix == ".json" else f"{ruta.name}.json"
    destino = CARPETA_HECHAS / nombre
    if destino.exists():
        destino = CARPETA_HECHAS / f"{ruta.stem}-{datetime.now():%Y%m%d%H%M%S}.json"
    _guardar(destino, idea)
    ruta.unlink(missing_ok=True)
    return destino


def archivos_en_cola() -> list[Path]:
    if not CARPETA_COLA.exists():
        return []
    return sorted(p for p in CARPETA_COLA.glob("*.json") if p.is_file())


def siguiente() -> tuple[Path, dict] | None:
    """Devuelve la siguiente idea válida. Las inválidas se mueven a hechas/ con su error."""
    for ruta in archivos_en_cola():
        idea = _leer(ruta)
        if idea is None:
            _mover_a_hechas(ruta, {"id": ruta.stem}, "invalida", {"error": "JSON mal formado"})
            continue
        errores = validar(idea)
        if errores:
            log(f"Idea {ruta.name} inválida: {'; '.join(errores)}")
            _mover_a_hechas(ruta, idea, "invalida", {"error": "; ".join(errores)})
            continue
        return ruta, idea
    return None


def cuantas_en_cola() -> int:
    return len(archivos_en_cola())


def gasto_del_mes(ahora: datetime | None = None) -> float:
    """Suma el costo estimado de los videos generados en el mes actual (UTC)."""
    ahora = ahora or datetime.now(timezone.utc)
    prefijo = f"{ahora:%Y-%m}"
    total = 0.0
    if not CARPETA_HECHAS.exists():
        return 0.0
    for ruta in CARPETA_HECHAS.glob("*.json"):
        datos = _leer(ruta) or {}
        res = datos.get("resultado") or {}
        if str(res.get("fecha", "")).startswith(prefijo) and res.get("costo_estimado_usd"):
            total += float(res["costo_estimado_usd"])
    return round(total, 2)


def marcar_hecha(ruta: Path, idea: dict, estado: str, datos: dict) -> Path:
    return _mover_a_hechas(ruta, idea, estado, datos)


def registrar_fallo(ruta: Path, idea: dict, error: str, intentos_max: int) -> str:
    """Suma un intento fallido. Si llega al máximo, la idea sale de la cola. Devuelve el estado."""
    idea = dict(idea)
    idea["intentos"] = int(idea.get("intentos", 0)) + 1
    idea["ultimo_error"] = error[:500]
    if idea["intentos"] >= intentos_max:
        _mover_a_hechas(ruta, idea, "fallida", {"error": error[:500]})
        return "fallida"
    _guardar(ruta, idea)
    return "reintentar"


# ---------------------------------------------------------------- respaldo con Gemini

PROMPT_RESPALDO = """Eres guionista de videos cortos para TikTok en México.
Tema de la cuenta: {tema}

Crea UNA idea de video original de {n} escenas de {seg} segundos cada una (video vertical 9:16).
Reglas:
- "escenas": {n} prompts para un generador de video (Veo). Cada uno describe en inglés lo visual
  (sujeto, acción, lugar, cámara, luz) y repite la descripción completa de cada personaje (edad,
  cabello, ropa). Todas las escenas pasan en el mismo lugar y cada una continúa justo donde
  terminó la anterior. Si alguien habla, escribe el diálogo entre comillas en español de México,
  máximo 15 palabras por escena.
- "estilo": una frase en inglés con el estilo visual común a todas las escenas.
- "gancho": texto corto en español (máximo 45 caracteres) para mostrar en pantalla al inicio.
- "caption": descripción en español para TikTok, máximo 150 caracteres más 3 a 5 hashtags.
- Nada de personas reales famosas, marcas registradas ni personajes con derechos de autor.
Responde solo con JSON con las claves: titulo, gancho, estilo, escenas, caption."""


def generar_idea_respaldo(cfg: dict, proyecto: str) -> tuple[Path, dict]:
    """Pide a Gemini (Vertex AI) una idea y la guarda en la cola. Lanza excepción si falla."""
    from google import genai
    from google.genai import types

    conf_ideas = cfg["ideas"]
    conf_video = cfg["video"]
    n = max(1, int(conf_video["max_clips_por_video"]))
    prompt = PROMPT_RESPALDO.format(
        tema=cfg.get("tema_cuenta", ""), n=n, seg=conf_video["segundos_por_clip"]
    )
    client = genai.Client(
        vertexai=True, project=proyecto, location=conf_ideas.get("region_respaldo", "global")
    )
    ultimo_error = None
    for modelo in conf_ideas.get("modelos_respaldo", []):
        try:
            resp = client.models.generate_content(
                model=modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=1.0
                ),
            )
            datos = json.loads(resp.text)
            if isinstance(datos, list):
                datos = datos[0]
            ahora = datetime.now(timezone.utc)
            datos["id"] = f"gemini-{ahora:%Y%m%d-%H%M%S}"
            datos["origen"] = f"respaldo {modelo}"
            datos["escenas"] = list(datos.get("escenas", []))[:n]
            errores = validar(datos)
            if errores:
                raise ValueError("; ".join(errores))
            ruta = CARPETA_COLA / f"{datos['id']}.json"
            _guardar(ruta, datos)
            log(f"Idea de respaldo creada con {modelo}: {datos.get('titulo', datos['id'])}")
            return ruta, datos
        except Exception as e:  # probamos el siguiente modelo
            ultimo_error = e
            log(f"El modelo de respaldo {modelo} falló: {e}")
    raise RuntimeError(f"No se pudo crear idea de respaldo: {ultimo_error}")
