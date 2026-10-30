"""Pruebas de la entrega por Telegram contra un servidor falso de la Bot API."""
from __future__ import annotations

import email.parser
import email.policy
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from test_pipeline import _Base  # fija TIKTOK_API_BASE antes de importar pipeline

from pipeline import publicar, run, telegram, veo  # noqa: E402

_PUERTO_TG = 18766
TOKEN = "123456:SECRETO-del-bot"


class _TelegramFalso(http.server.BaseHTTPRequestHandler):
    """Imita getUpdates, sendVideo y sendMessage. Guarda lo recibido en `estado`."""
    estado: dict = {}
    actualizaciones: list = []

    def log_message(self, *a):
        pass

    def _responder(self, codigo: int, datos: dict):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _token_y_metodo(self):
        partes = self.path.split("?")[0].strip("/").split("/")
        return partes[0].removeprefix("bot"), partes[1]

    def do_GET(self):
        token, metodo = self._token_y_metodo()
        if token != TOKEN:
            return self._responder(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        if metodo == "getUpdates":
            return self._responder(200, {"ok": True, "result": self.actualizaciones})
        self._responder(404, {"ok": False, "description": "Not Found"})

    def do_POST(self):
        token, metodo = self._token_y_metodo()
        if token != TOKEN:
            return self._responder(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        campos, archivos = _leer_formulario(self)
        if campos.get("chat_id") != "777":
            return self._responder(400, {"ok": False, "description": "Bad Request: chat not found"})
        if metodo == "sendVideo":
            self.estado["video"] = archivos["video"]
            self.estado["video_campos"] = campos
        elif metodo == "sendMessage":
            self.estado["mensaje"] = campos
        else:
            return self._responder(404, {"ok": False, "description": "Not Found"})
        self._responder(200, {"ok": True, "result": {"message_id": 1}})


def _leer_formulario(h: http.server.BaseHTTPRequestHandler) -> tuple[dict, dict]:
    """Lee un POST multipart/form-data o urlencoded (cgi ya no existe en Python 3.13)."""
    cuerpo = h.rfile.read(int(h.headers.get("Content-Length", 0)))
    tipo = h.headers.get("Content-Type", "")
    if tipo.startswith("application/x-www-form-urlencoded"):
        from urllib.parse import parse_qsl
        return dict(parse_qsl(cuerpo.decode())), {}
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        f"Content-Type: {tipo}\r\n\r\n".encode() + cuerpo)
    campos, archivos = {}, {}
    for parte in msg.iter_parts():
        nombre = parte.get_param("name", header="content-disposition")
        datos = parte.get_payload(decode=True)
        if parte.get_filename():
            archivos[nombre] = datos
        else:
            campos[nombre] = datos.decode("utf-8")
    return campos, archivos


def _chat_privado(chat_id: int) -> dict:
    return {"update_id": chat_id, "message": {"chat": {"id": chat_id, "type": "private"}, "text": "/start"}}


class _ConTelegram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tg = http.server.ThreadingHTTPServer(("127.0.0.1", _PUERTO_TG), _TelegramFalso)
        threading.Thread(target=cls.tg.serve_forever, daemon=True).start()
        cls._api = mock.patch.object(telegram, "API", f"http://127.0.0.1:{_PUERTO_TG}")
        cls._api.start()

    @classmethod
    def tearDownClass(cls):
        cls._api.stop()
        cls.tg.shutdown()
        cls.tg.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        _TelegramFalso.estado = {}
        _TelegramFalso.actualizaciones = [_chat_privado(555), {"update_id": 9, "my_chat_member": {}},
                                          _chat_privado(777)]
        self.dir = Path(tempfile.mkdtemp())
        self.video = self.dir / "v.mp4"
        veo._clip_simulado(self.video, 1, 1)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        super().tearDown()


class TestEnviar(_ConTelegram):
    def test_descubre_el_chat_y_manda_video_y_caption(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": ""}):
            r = telegram.enviar(self.video, "El <anillo>", "Ella dijo que sí & él lloró #novela")
        self.assertTrue(r.enviado, r.error)
        self.assertEqual(r.chat_id_nuevo, "777")          # el chat privado más reciente
        e = _TelegramFalso.estado
        self.assertEqual(e["video"], self.video.read_bytes())
        self.assertEqual(e["video_campos"]["caption"], "🎬 El <anillo>")
        texto = e["mensaje"]["text"]
        self.assertEqual(e["mensaje"]["parse_mode"], "HTML")
        self.assertIn("<code>Ella dijo que sí &amp; él lloró #novela</code>", texto)
        self.assertIn("El &lt;anillo&gt;", texto)
        self.assertIn("Contenido generado por IA", texto)

    def test_con_chat_guardado_no_busca_otro(self):
        _TelegramFalso.actualizaciones = []
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "777"}):
            r = telegram.enviar(self.video, "t", "c")
        self.assertTrue(r.enviado, r.error)
        self.assertIsNone(r.chat_id_nuevo)

    def test_sin_start_pide_mandarlo(self):
        _TelegramFalso.actualizaciones = []
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": ""}):
            r = telegram.enviar(self.video, "t", "c")
        self.assertFalse(r.enviado)
        self.assertIn("/start", r.error)

    def test_token_malo_da_pista_y_no_se_filtra(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "999:otro", "TELEGRAM_CHAT_ID": "777"}):
            r = telegram.enviar(self.video, "t", "c")
        self.assertFalse(r.enviado)
        self.assertIn("TELEGRAM_BOT_TOKEN", r.error)

    def test_error_de_conexion_no_muestra_el_token(self):
        with mock.patch.object(telegram, "API", "http://127.0.0.1:9"), \
                mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": "777"}):
            r = telegram.enviar(self.video, "t", "c")
        self.assertFalse(r.enviado)
        self.assertNotIn("SECRETO", r.error)
        self.assertIn("***", r.error)

    def test_sin_token(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            r = telegram.enviar(self.video, "t", "c")
        self.assertIn("TELEGRAM_BOT_TOKEN", r.error)

    def test_video_pesado_se_aligera(self):
        grande = self.dir / "grande.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=720x1280:rate=24:duration=4", "-vf", "noise=alls=60:allf=t",
                        "-c:v", "libx264", "-preset", "veryfast", "-b:v", "8M", "-pix_fmt", "yuv420p",
                        str(grande)], check=True)
        tam = grande.stat().st_size
        self.assertIs(telegram.ajustar_tamano(grande, tam + 1), grande)
        ligero = telegram.ajustar_tamano(grande, tam // 2)
        self.assertNotEqual(ligero, grande)
        self.assertLess(ligero.stat().st_size, tam // 2)


class TestEntregaEnPipeline(_ConTelegram, _Base):
    """Modo automático con Telegram activo y TikTok apagado (la configuración por defecto)."""

    def setUp(self):
        super().setUp()
        self.cfg["tiktok"]["subir"] = False
        self.cfg["telegram"]["activo"] = True
        idea = {"id": "2026-11-02-a", "titulo": "Prueba", "gancho": "Mira", "escenas": ["uno", "dos"],
                "caption": "Hola #prueba"}
        (self.cola / "2026-11-02-a.json").write_text(json.dumps(idea), encoding="utf-8")

    def _correr(self, env: dict):
        with mock.patch.dict(os.environ, {"GCP_PROJECT": "p", "SIMULAR": "1", **env}):
            return run.main()

    def test_video_llega_por_telegram(self):
        self.assertEqual(self._correr({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": ""}), 0)
        self.assertEqual(_TelegramFalso.estado["video"], next(self.salida.glob("*.mp4")).read_bytes())
        self.assertEqual((self.salida / "nuevo_telegram_chat_id.txt").read_text(), "777")
        self.assertIn("Video listo en Telegram", (self.salida / "aviso_titulo.txt").read_text())
        aviso = (self.salida / "aviso.md").read_text()
        self.assertIn("Hola #prueba", aviso)
        self.assertNotIn("TikTok:", aviso)                 # no se intentó TikTok
        self.assertNotIn("init", __import__("test_pipeline")._TikTokFalso.estado)

    def test_telegram_falla_avisa_con_error(self):
        self.assertEqual(self._correr({"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}), 1)
        self.assertIn("no se pudo entregar", (self.salida / "aviso_titulo.txt").read_text())
        self.assertIn("TELEGRAM_BOT_TOKEN", (self.salida / "aviso.md").read_text())


class TestEstadoEntrega(unittest.TestCase):
    def test_estados(self):
        E, T, G = publicar.Entrega, publicar.ResultadoTikTok, telegram.ResultadoTelegram
        self.assertEqual(E().estado, "generado")
        self.assertEqual(E(tiktok=T(error="x")).estado, "generado_sin_subir")
        self.assertEqual(E(tiktok=T(error="x"), telegram=G(enviado=True)).estado, "enviado_por_telegram")
        self.assertEqual(E(tiktok=T(estado="SEND_TO_USER_INBOX"), telegram=G(enviado=True)).estado,
                         "borrador_en_tiktok")


if __name__ == "__main__":
    unittest.main()
