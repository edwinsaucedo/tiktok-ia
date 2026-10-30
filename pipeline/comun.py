"""Utilidades compartidas: rutas, configuración y registro."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_COLA = RAIZ / "ideas" / "cola"
CARPETA_HECHAS = RAIZ / "ideas" / "hechas"
CARPETA_SALIDA = RAIZ / "salida"


def log(mensaje: str) -> None:
    print(mensaje, flush=True)


def aviso_github(tipo: str, mensaje: str) -> None:
    """Muestra un aviso en la interfaz de GitHub Actions (warning/error/notice)."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{tipo}::{mensaje}", flush=True)
    else:
        log(f"[{tipo.upper()}] {mensaje}")


def ocultar_en_log(valor: str) -> None:
    """Pide a GitHub Actions que no muestre este valor en los registros."""
    if valor and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{valor}", flush=True)


def cargar_config(ruta: Path | None = None) -> dict:
    ruta = ruta or RAIZ / "config.json"
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def escribir_salida_github(nombre: str, valor: str) -> None:
    """Escribe un output del paso para que el workflow lo use."""
    archivo = os.environ.get("GITHUB_OUTPUT")
    if not archivo:
        return
    with open(archivo, "a", encoding="utf-8") as f:
        if "\n" in valor:
            f.write(f"{nombre}<<FIN_VALOR\n{valor}\nFIN_VALOR\n")
        else:
            f.write(f"{nombre}={valor}\n")


def env_requerida(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta la variable/secreto {nombre}. Revisa la sección de secretos del README."
        )
    return valor


def es_verdadero(valor: str | None) -> bool:
    return (valor or "").strip().lower() in {"1", "true", "si", "sí", "yes"}


if sys.version_info < (3, 10):  # pragma: no cover
    raise SystemExit("Se necesita Python 3.10 o superior.")
