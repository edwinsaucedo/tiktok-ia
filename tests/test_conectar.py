"""Pruebas de tools/conectar_tiktok.py (sin internet: se simulan gh y TikTok)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

RUTA = Path(__file__).resolve().parent.parent / "tools" / "conectar_tiktok.py"
spec = importlib.util.spec_from_file_location("conectar_tiktok", RUTA)
conectar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conectar)


class _GhFalso:
    def __init__(self):
        self.secretos: dict[str, str] = {}
        self.borrados: list[str] = []

    def __call__(self, cmd, input=None, text=None, capture_output=None):
        if cmd[:3] == ["gh", "secret", "set"]:
            self.secretos[cmd[3]] = input
        elif cmd[:3] == ["gh", "secret", "delete"]:
            self.borrados.append(cmd[3])
        return mock.Mock(returncode=0, stderr="")


class TestConectar(unittest.TestCase):
    def setUp(self):
        self.resumen = Path(tempfile.mkstemp()[1])
        self.env = mock.patch.dict(os.environ, {
            "TIKTOK_CLIENT_KEY": "ck123", "TIKTOK_CLIENT_SECRET": "cs456", "GH_TOKEN": "ghp",
            "GITHUB_REPOSITORY": "yo/tiktok-ia", "GITHUB_STEP_SUMMARY": str(self.resumen),
            "URL_REGRESO": "", "TIKTOK_PKCE": "",
        })
        self.env.start()
        self.gh = _GhFalso()
        self.p = mock.patch.object(conectar.subprocess, "run", self.gh)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.env.stop()
        self.resumen.unlink(missing_ok=True)

    def _paso_1(self):
        conectar.main()
        pkce = json.loads(self.gh.secretos["TIKTOK_PKCE"])
        texto = self.resumen.read_text()
        url = next(p for p in texto.split() if p.startswith("https://www.tiktok.com/v2/auth/authorize/"))
        # GitHub tapa con *** los valores de secretos: el key no debe aparecer tal cual en el texto
        self.assertNotIn("ck123", texto)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
        return pkce, q

    def test_paso_1_arma_url_con_pkce_hex(self):
        pkce, q = self._paso_1()
        self.assertEqual(q["client_key"], "ck123")
        self.assertEqual(q["redirect_uri"], "http://localhost:8765/callback/")
        self.assertEqual(q["scope"], "user.info.basic,video.upload")
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["code_challenge"], hashlib.sha256(pkce["verifier"].encode()).hexdigest())
        self.assertEqual(q["state"], pkce["state"])
        self.assertTrue(43 <= len(pkce["verifier"]) <= 128)

    def test_paso_2_guarda_refresh_token(self):
        pkce, q = self._paso_1()
        regreso = ("http://localhost:8765/callback/?code=abc%2A123%21&scopes=user.info.basic%2Cvideo.upload"
                   f"&state={q['state']}")
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"access_token": "act.x", "refresh_token": "rft.nuevo",
                                  "scope": "user.info.basic,video.upload", "open_id": "o"}
        info = mock.Mock(status_code=200)
        info.json.return_value = {"data": {"user": {"open_id": "o", "display_name": "elcanacacod",
                                                    "avatar_url": "https://x/a.jpg"}}}
        with mock.patch.dict(os.environ, {"URL_REGRESO": regreso, "TIKTOK_PKCE": json.dumps(pkce)}), \
                mock.patch.object(conectar.requests, "post", return_value=resp) as post, \
                mock.patch.object(conectar.requests, "get", return_value=info) as get:
            conectar.main()
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer act.x")
        self.assertIn("Cuenta: **elcanacacod**", self.resumen.read_text())
        datos = post.call_args.kwargs["data"]
        self.assertEqual(datos["code"], "abc*123!")  # decodificado
        self.assertEqual(datos["code_verifier"], pkce["verifier"])
        self.assertEqual(datos["grant_type"], "authorization_code")
        self.assertEqual(datos["client_secret"], "cs456")
        self.assertEqual(self.gh.secretos["TIKTOK_REFRESH_TOKEN"], "rft.nuevo")
        self.assertIn("TIKTOK_PKCE", self.gh.borrados)
        self.assertNotIn("rft.nuevo", self.resumen.read_text())  # el token nunca se muestra

    def test_paso_2_rechaza_state_distinto(self):
        pkce, _ = self._paso_1()
        with mock.patch.dict(os.environ, {"URL_REGRESO": "http://localhost:8765/callback/?code=a&state=otro",
                                          "TIKTOK_PKCE": json.dumps(pkce)}):
            with self.assertRaises(SystemExit) as e:
                conectar.main()
        self.assertIn("paso 1", str(e.exception))

    def test_paso_2_sin_paso_1(self):
        with mock.patch.dict(os.environ, {"URL_REGRESO": "http://localhost:8765/callback/?code=a&state=b"}):
            with self.assertRaises(SystemExit) as e:
                conectar.main()
        self.assertIn("paso 1", str(e.exception))

    def test_falta_gh_pat(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": ""}):
            with self.assertRaises(SystemExit) as e:
                conectar.main()
        self.assertIn("GH_PAT", str(e.exception))


if __name__ == "__main__":
    unittest.main()
