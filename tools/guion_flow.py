"""Arma el texto del «Guion para Flow» de una historia (el documento que va en su carpeta de Drive).

Uso:  python -m tools.guion_flow ideas/flow/007-chambelan-tactico.json  > guion.txt
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pipeline.comun import cargar_config
from pipeline.veo import armar_prompt

LINEA = "━━━━━━━━"

INSTRUCCIONES = """ANTES DE EMPEZAR (en Flow)

• Abre tu proyecto (o crea uno nuevo).
• En la caja de abajo deja: Video · 9:16 (vertical) · x1 (un resultado por prompt; con x2 gastas el doble).

• PARTE 1: pega el prompt y genera.
• PARTES 2 a 8: haz clic en la imagen del clip para abrirlo en grande → botón + al final de la línea de tiempo → «Alargar (Veo 3.1 - Lite)» → pega SOLO el prompt de la parte → genera. Revisa que la caja diga Alargar y no «Describe cómo editar este vídeo».
• Copia solo el texto de «Prompt para copiar», no la línea «Qué pasa».
• Si una parte sale mal, bórrala de la línea de tiempo y vuelve a alargar con el mismo prompt.

• Al terminar (unos 64 segundos): ícono de descarga ⬇ arriba a la derecha → Hecho.
• Sube el video descargado a ESTA MISMA carpeta de Drive. En menos de 1 hora te llega a Telegram (Canaca Reels) con el texto gancho y el caption listo para copiar."""


def _sin_emoji(texto: str) -> str:
    # Google Docs creados por la API a veces rompen los emoji; en el guion no hacen falta.
    return re.sub(r"[\U0001F000-\U0001FFFF☀-➿️]", "", texto).replace("  ", " ").strip()


def texto_guion(idea: dict, numero: str, conf_video: dict | None = None) -> str:
    conf = conf_video if conf_video is not None else cargar_config()["video"]
    escenas = idea["escenas"]
    resumen = idea.get("resumen_partes") or [""] * len(escenas)
    total = len(escenas)
    partes = [
        f"GUION PARA FLOW · {numero} · {idea['titulo']}",
        f"{total} partes de 8 segundos = {total * 8} segundos aprox.",
        INSTRUCCIONES,
    ]
    for i, (escena, que) in enumerate(zip(escenas, resumen), start=1):
        modo = "generar" if i == 1 else "Alargar"
        bloque = [f"{LINEA} PARTE {i} de {total} ({modo}) {LINEA}"]
        if que:
            bloque.append(f"Qué pasa: {que}")
        bloque.append("Prompt para copiar:")
        bloque.append(armar_prompt(escena, idea, conf))
        partes.append("\n\n".join(bloque))
    partes.append(LINEA * 4)
    partes.append(f"TEXTO GANCHO (lo pone el sistema solo, primeros 3 segundos): {idea.get('gancho', '')}")
    partes.append(f"CAPTION (te llega a Telegram listo para copiar): {_sin_emoji(idea.get('caption', ''))}")
    return "\n\n".join(partes) + "\n"


def main(argv: list[str]) -> int:
    for ruta in argv:
        idea = json.loads(Path(ruta).read_text(encoding="utf-8"))
        numero = Path(ruta).name.split("-", 1)[0]
        sys.stdout.write(texto_guion(idea, numero))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
