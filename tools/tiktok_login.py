"""Inicio de sesión de TikTok (una sola vez) para obtener el REFRESH TOKEN.

Córrelo en tu computadora (no en GitHub):

    pip install requests
    python tools/tiktok_login.py

Te pedirá tu Client key y Client secret (de developers.tiktok.com), abrirá el navegador para que
autorices tu cuenta y al final te mostrará el refresh token para guardarlo como secreto
TIKTOK_REFRESH_TOKEN en GitHub. El refresh token dura 365 días y el workflow lo renueva solo.

Requisito en tu app de TikTok (Login Kit → Desktop → Redirect URI):
    http://localhost:8765/callback/
"""
from __future__ import annotations

import getpass
import hashlib
import http.server
import secrets
import sys
import threading
import urllib.parse
import webbrowser

import requests

PUERTO = 8765
REDIRECT_URI = f"http://localhost:{PUERTO}/callback/"
SCOPES = "user.info.basic,video.upload"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def generar_pkce() -> tuple[str, str]:
    """TikTok (desktop) pide code_challenge = SHA256(code_verifier) en HEXADECIMAL."""
    verifier = secrets.token_urlsafe(64)[:64]
    challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
    return verifier, challenge


class _Receptor(http.server.BaseHTTPRequestHandler):
    resultado: dict = {}
    listo = threading.Event()

    def do_GET(self):  # noqa: N802
        consulta = urllib.parse.urlparse(self.path)
        if not consulta.path.startswith("/callback"):
            self.send_response(404)
            self.end_headers()
            return
        params = {k: v[0] for k, v in urllib.parse.parse_qs(consulta.query).items()}
        _Receptor.resultado = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in params
        mensaje = ("✅ Listo, ya puedes cerrar esta pestaña y volver a la terminal."
                   if ok else f"❌ TikTok devolvió un error: {params}")
        self.wfile.write(f"<h2 style='font-family:sans-serif'>{mensaje}</h2>".encode("utf-8"))
        _Receptor.listo.set()

    def log_message(self, *args):  # silencio
        pass


def main() -> int:
    print("=== Conectar tu cuenta de TikTok ===\n")
    client_key = input("Client key: ").strip()
    client_secret = getpass.getpass("Client secret (no se verá al escribir): ").strip()
    if not client_key or not client_secret:
        print("Faltan datos.")
        return 1

    verifier, challenge = generar_pkce()
    estado = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": estado,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    servidor = http.server.HTTPServer(("127.0.0.1", PUERTO), _Receptor)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    print("\nAbriendo el navegador… Si no se abre, copia esta dirección:\n")
    print(url + "\n")
    webbrowser.open(url)

    if not _Receptor.listo.wait(timeout=600):
        print("Se acabó el tiempo (10 min). Vuelve a intentarlo.")
        servidor.shutdown()
        return 1
    servidor.shutdown()

    params = _Receptor.resultado
    if params.get("state") != estado:
        print("El parámetro state no coincide; por seguridad no continúo. Vuelve a intentarlo.")
        return 1
    if "code" not in params:
        print(f"TikTok no autorizó: {params}")
        return 1

    r = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": params["code"],
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=60,
    )
    datos = r.json()
    if "refresh_token" not in datos:
        print(f"No se obtuvo el token: {datos}")
        return 1

    print("\n✅ Cuenta conectada. Permisos:", datos.get("scope"))
    if "video.upload" not in datos.get("scope", ""):
        print("⚠️  El token NO tiene video.upload. Revisa que tu app tenga Content Posting API.")
    print("\nCopia este valor y guárdalo en GitHub como secreto TIKTOK_REFRESH_TOKEN:\n")
    print(datos["refresh_token"])
    print("\n(No lo compartas con nadie: da acceso para subir videos a tu cuenta.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
