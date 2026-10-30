"""Conecta tu cuenta de TikTok desde GitHub Actions, sin instalar nada en tu computadora.

Se usa con el workflow "Conectar TikTok" en dos pasos:

  1) Corre el workflow con el campo vacío. Genera la dirección de autorización (con PKCE) y la
     muestra en el resumen de la ejecución. El code_verifier se guarda como secreto temporal.
  2) Abre esa dirección, autoriza con tu cuenta de TikTok. El navegador intentará abrir
     http://localhost:8765/callback/?code=... y dirá que no puede conectar: es normal.
     Copia esa dirección completa y vuelve a correr el workflow pegándola en el campo.
     El workflow cambia el código por el refresh token y lo guarda en el secreto
     TIKTOK_REFRESH_TOKEN. No se muestra en ningún lado.

Variables de entorno: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, GH_TOKEN (= secreto GH_PAT),
GITHUB_REPOSITORY, TIKTOK_PKCE (secreto temporal del paso 1), URL_REGRESO (entrada del paso 2).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import urllib.parse

import requests

REDIRECT_URI = "http://localhost:8765/callback/"
SCOPES = "user.info.basic,video.upload"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = os.environ.get("TIKTOK_API_BASE", "https://open.tiktokapis.com").rstrip("/")


def _resumen(texto: str) -> None:
    print(texto, flush=True)
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def _ocultar(valor: str) -> None:
    if valor and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{valor}", flush=True)


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise SystemExit(f"❌ Falta el secreto {nombre}. Guárdalo en Settings → Secrets and variables → Actions.")
    return valor


def _guardar_secreto(nombre: str, valor: str) -> None:
    repo = _requerida("GITHUB_REPOSITORY")
    if not os.environ.get("GH_TOKEN", "").strip():
        raise SystemExit("❌ Falta el secreto GH_PAT (token de GitHub con permiso Secrets: Read and write).")
    r = subprocess.run(["gh", "secret", "set", nombre, "--repo", repo], input=valor,
                       text=True, capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"❌ No pude guardar el secreto {nombre}: {r.stderr.strip()}\n"
                         "Revisa que GH_PAT tenga permiso Secrets: Read and write sobre este repositorio.")


def _borrar_secreto(nombre: str) -> None:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    subprocess.run(["gh", "secret", "delete", nombre, "--repo", repo], text=True, capture_output=True)


def generar_pkce() -> tuple[str, str]:
    """TikTok (desktop) pide code_challenge = SHA256(code_verifier) en HEXADECIMAL."""
    verifier = secrets.token_urlsafe(64)[:64]
    return verifier, hashlib.sha256(verifier.encode("ascii")).hexdigest()


def paso_1() -> None:
    client_key = _requerida("TIKTOK_CLIENT_KEY")
    verifier, challenge = generar_pkce()
    estado = secrets.token_urlsafe(16)
    _guardar_secreto("TIKTOK_PKCE", json.dumps({"verifier": verifier, "state": estado}))
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": client_key, "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT_URI, "state": estado,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    _resumen(
        "## Paso 1 listo ✅\n\n"
        f"1. Abre esta dirección en tu navegador y autoriza con tu cuenta de TikTok:\n\n   {url}\n\n"
        "2. Al final el navegador dirá que **no puede conectar con localhost**. Es normal.\n"
        "3. Copia la dirección completa de la barra (empieza con `http://localhost:8765/callback/?code=`).\n"
        "4. Vuelve a correr **Conectar TikTok** y pégala en el campo. Hazlo en menos de 5 minutos.\n"
    )


def paso_2(url_regreso: str) -> None:
    client_key = _requerida("TIKTOK_CLIENT_KEY")
    client_secret = _requerida("TIKTOK_CLIENT_SECRET")
    try:
        pkce = json.loads(os.environ.get("TIKTOK_PKCE", "") or "{}")
    except json.JSONDecodeError:
        pkce = {}
    if not pkce.get("verifier"):
        raise SystemExit("❌ No encontré el paso 1. Corre primero el workflow con el campo vacío.")

    params = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url_regreso.strip()).query).items()}
    if "error" in params:
        raise SystemExit(f"❌ TikTok no autorizó: {params.get('error')} {params.get('error_description', '')}")
    if "code" not in params:
        raise SystemExit("❌ La dirección no trae el código. Copia la dirección completa que empieza con "
                         "http://localhost:8765/callback/?code=")
    if params.get("state") != pkce.get("state"):
        raise SystemExit("❌ La dirección no corresponde al último paso 1. Repite desde el paso 1.")

    _ocultar(params["code"])
    r = requests.post(
        f"{API}/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={"client_key": client_key, "client_secret": client_secret, "code": params["code"],
              "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
              "code_verifier": pkce["verifier"]},
        timeout=60,
    )
    try:
        datos = r.json()
    except ValueError:
        raise SystemExit(f"❌ Respuesta inesperada de TikTok (HTTP {r.status_code}).")
    if "refresh_token" not in datos:
        raise SystemExit(f"❌ TikTok no entregó el token: {datos.get('error')} - "
                         f"{datos.get('error_description', '')}. Si tardaste más de unos minutos, repite "
                         "desde el paso 1.")
    _ocultar(datos["refresh_token"])
    _ocultar(datos.get("access_token", ""))
    _guardar_secreto("TIKTOK_REFRESH_TOKEN", datos["refresh_token"])
    _borrar_secreto("TIKTOK_PKCE")
    scopes = datos.get("scope", "")
    aviso = "" if "video.upload" in scopes else (
        "\n\n⚠️ El permiso **video.upload** no aparece. Revisa que la app tenga Content Posting API.")
    _resumen(f"## Cuenta de TikTok conectada ✅\n\nPermisos: `{scopes}`\n\n"
             f"El refresh token quedó guardado en el secreto `TIKTOK_REFRESH_TOKEN`.{aviso}")


def main() -> int:
    url = os.environ.get("URL_REGRESO", "").strip()
    if url:
        paso_2(url)
    else:
        paso_1()
    return 0


if __name__ == "__main__":
    sys.exit(main())
