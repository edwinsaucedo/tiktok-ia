"""Pruebas sin internet: simulan Veo (con ffmpeg) y TikTok (con un servidor local falso).

Correr:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

# El servidor falso de TikTok debe configurarse antes de importar pipeline.tiktok
_PUERTO = 18765
os.environ["TIKTOK_API_BASE"] = f"http://127.0.0.1:{_PUERTO}"

from google.genai import types  # noqa: E402

from pipeline import editar, ideas, run, tiktok, veo  # noqa: E402
from pipeline.comun import cargar_config  # noqa: E402

MB = 1024 * 1024


# ------------------------------------------------------------------ servidor falso de TikTok

class _TikTokFalso(http.server.BaseHTTPRequestHandler):
    estado: dict = {}

    def _json(self, codigo: int, datos: dict) -> None:
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo)
        e = _TikTokFalso.estado
        if self.path == "/v2/oauth/token/":
            from urllib.parse import parse_qs
            form = {k: v[0] for k, v in parse_qs(cuerpo.decode()).items()}
            e["token_form"] = form
            if form.get("refresh_token") != "rft.viejo":
                return self._json(400, {"error": "invalid_grant", "error_description": "malo"})
            return self._json(200, {"access_token": "act.nuevo", "expires_in": 86400,
                                    "refresh_token": "rft.rotado", "open_id": "abc",
                                    "scope": "user.info.basic,video.upload", "token_type": "Bearer"})
        if self.path == "/v2/post/publish/inbox/video/init/":
            if self.headers.get("Authorization") != "Bearer act.nuevo":
                return self._json(401, {"error": {"code": "access_token_invalid", "message": "x"}})
            info = json.loads(cuerpo)["source_info"]
            e["init"] = info
            e["recibido"] = bytearray()
            e["rangos"] = []
            return self._json(200, {"data": {"publish_id": "v_inbox_file~v2.123",
                                             "upload_url": f"http://127.0.0.1:{_PUERTO}/upload/?id=1"},
                                    "error": {"code": "ok", "message": ""}})
        if self.path == "/v2/post/publish/status/fetch/":
            return self._json(200, {"data": {"status": "SEND_TO_USER_INBOX"},
                                    "error": {"code": "ok", "message": ""}})
        self._json(404, {})

    def do_PUT(self):  # noqa: N802
        e = _TikTokFalso.estado
        largo = int(self.headers["Content-Length"])
        datos = self.rfile.read(largo)
        rango = self.headers["Content-Range"]  # bytes inicio-fin/total
        inicio, resto = rango.removeprefix("bytes ").split("-")
        fin, total = resto.split("/")
        assert int(fin) - int(inicio) + 1 == len(datos), "Content-Range no cuadra con el tamaño"
        assert int(inicio) == len(e["recibido"]), "Los pedazos no llegan en orden"
        e["recibido"].extend(datos)
        e["rangos"].append(rango)
        self.send_response(201 if len(e["recibido"]) == int(total) else 206)
        self.end_headers()

    def log_message(self, *args):
        pass


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = http.server.ThreadingHTTPServer(("127.0.0.1", _PUERTO), _TikTokFalso)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cola = self.tmp / "ideas" / "cola"
        self.hechas = self.tmp / "ideas" / "hechas"
        self.salida = self.tmp / "salida"
        self.cola.mkdir(parents=True)
        self.hechas.mkdir(parents=True)
        self.cfg = cargar_config()
        self.cfg["video"]["max_clips_por_video"] = 2
        self.parches = [
            mock.patch.object(ideas, "CARPETA_COLA", self.cola),
            mock.patch.object(ideas, "CARPETA_HECHAS", self.hechas),
            mock.patch.object(run, "CARPETA_SALIDA", self.salida),
            mock.patch.object(run, "cargar_config", lambda: self.cfg),
        ]
        for p in self.parches:
            p.start()
        _TikTokFalso.estado = {}

    def tearDown(self):
        for p in self.parches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ------------------------------------------------------------------ pruebas

class TestChunks(unittest.TestCase):
    def test_archivo_chico_un_pedazo(self):
        self.assertEqual(tiktok.plan_chunks(3 * MB), (3 * MB, 1))
        self.assertEqual(tiktok.plan_chunks(64 * MB), (64 * MB, 1))

    def test_archivo_grande_redondea_hacia_abajo(self):
        tam = 150_000_123
        chunk, total = tiktok.plan_chunks(tam)
        self.assertEqual(chunk, 10 * MB)
        self.assertEqual(total, tam // (10 * MB))
        r = tiktok.rangos(tam, chunk, total)
        self.assertEqual(r[0][0], 0)
        self.assertEqual(r[-1][1], tam - 1)
        for (a, b), (c, _) in zip(r, r[1:]):
            self.assertEqual(b + 1, c)
        ultimo = r[-1][1] - r[-1][0] + 1
        self.assertLessEqual(ultimo, 128 * MB)
        self.assertGreaterEqual(ultimo, 5 * MB)


class TestIdeas(unittest.TestCase):
    def test_validacion(self):
        buena = {"id": "2026-11-02-a", "escenas": ["x"], "caption": "hola #a"}
        self.assertEqual(ideas.validar(buena), [])
        self.assertTrue(ideas.validar({"id": "a b", "escenas": [], "caption": ""}))


class TestVeoConFalso(unittest.TestCase):
    """Comprueba que usamos bien el SDK de Google con objetos reales de google.genai.types."""

    def _cliente(self, falla_primero: str | None = None):
        llamadas = []

        class Modelos:
            def generate_videos(self_inner, model, prompt, config):
                llamadas.append((model, prompt, config))
                if falla_primero and model == falla_primero:
                    raise RuntimeError("404 NOT_FOUND: Publisher model not found")
                return types.GenerateVideosOperation(name="op/1", done=False)

        class Operaciones:
            def get(self_inner, op):
                return types.GenerateVideosOperation(
                    name="op/1", done=True,
                    response=types.GenerateVideosResponse(generated_videos=[
                        types.GeneratedVideo(video=types.Video(video_bytes=b"\x00" * 20_000,
                                                               mime_type="video/mp4"))]))

        cliente = mock.Mock()
        cliente.models = Modelos()
        cliente.operations = Operaciones()
        return cliente, llamadas

    def test_config_y_respaldo_de_modelo(self):
        cfg = cargar_config()
        cfg["video"]["max_clips_por_video"] = 3
        cliente, llamadas = self._cliente(falla_primero=cfg["video"]["modelos"][0])
        idea = {"id": "x", "estilo": "warm cinematic", "escenas": ["a dog runs", "a cat jumps"],
                "caption": "c"}
        tmp = Path(tempfile.mkdtemp())
        with mock.patch("google.genai.Client", return_value=cliente), \
                mock.patch.object(veo, "ESPERA_SONDEO", 0):
            res = veo.generar_clips(idea, cfg, tmp, "proyecto-x", simular=False)
        self.assertEqual(len(res.clips), 2)
        self.assertEqual(res.modelo, cfg["video"]["modelos"][1])
        self.assertTrue(res.avisos)
        modelo, prompt, config = llamadas[-1]
        self.assertIn("warm cinematic", prompt)
        self.assertEqual(config.aspect_ratio, "9:16")
        self.assertEqual(config.duration_seconds, 8)
        self.assertEqual(config.resolution, "1080p")
        self.assertTrue(config.generate_audio)
        shutil.rmtree(tmp)

    def test_filtro_de_seguridad_da_error_claro(self):
        cliente = mock.Mock()
        cliente.models.generate_videos.return_value = types.GenerateVideosOperation(
            name="op", done=True, response=types.GenerateVideosResponse(
                generated_videos=[], rai_media_filtered_count=1,
                rai_media_filtered_reasons=["violencia"]))
        with self.assertRaisesRegex(veo.ErrorVeo, "filtros de seguridad"):
            veo._generar_un_clip(cliente, "m", "p", cargar_config()["video"], Path("/tmp/x.mp4"))


class TestEdicion(unittest.TestCase):
    def test_unir_con_gancho_y_clip_sin_audio(self):
        tmp = Path(tempfile.mkdtemp())
        c1, c2 = tmp / "c1.mp4", tmp / "c2.mp4"
        veo._clip_simulado(c1, 1, 2)
        # clip 2 sin audio y en otra resolución, para probar la normalización
        os.system(f"ffmpeg -y -loglevel error -f lavfi -i testsrc2=size=1080x1920:rate=24:duration=2 "
                  f"-c:v libx264 -preset veryfast -pix_fmt yuv420p {c2}")
        self.assertFalse(editar.tiene_audio(c2))
        conf = dict(cargar_config()["video"], resolucion="720p")
        destino = editar.unir([c1, c2], "¿Sabías esto? 100% real: 'wow' \\ fin", conf, tmp / "final.mp4")
        self.assertTrue(editar.tiene_audio(destino))
        self.assertAlmostEqual(editar.duracion(destino), 4.0, delta=0.3)
        shutil.rmtree(tmp)


class TestFlujoCompleto(_Base):
    def _poner_idea(self, nombre="2026-11-02-a"):
        idea = {"id": nombre, "titulo": "Prueba", "gancho": "Mira esto",
                "estilo": "bright", "escenas": ["uno", "dos"], "caption": "Hola #prueba"}
        (self.cola / f"{nombre}.json").write_text(json.dumps(idea), encoding="utf-8")

    def _correr(self, extra_env: dict):
        env = {"TIKTOK_CLIENT_KEY": "ck", "TIKTOK_CLIENT_SECRET": "cs",
               "TIKTOK_REFRESH_TOKEN": "rft.viejo", "GCP_PROJECT": "p", **extra_env}
        original = veo.generar_clips

        def veo_simulado(idea, cfg, carpeta, proyecto, simular):
            res = original(idea, cfg, carpeta, proyecto, True)
            res.modelo = "veo-3.1-lite-generate-001"
            return res

        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(run.veo, "generar_clips", veo_simulado), \
                mock.patch.object(tiktok, "CHUNK_MAX", 200_000), \
                mock.patch.object(tiktok, "CHUNK_PREFERIDO", 100_000):
            return run.main()

    def test_idea_a_borrador_en_tiktok(self):
        self._poner_idea()
        codigo = self._correr({})
        self.assertEqual(codigo, 0)
        e = _TikTokFalso.estado
        video = next(self.salida.glob("*.mp4"))
        self.assertEqual(len(e["recibido"]), video.stat().st_size)
        self.assertEqual(bytes(e["recibido"]), video.read_bytes())
        self.assertGreater(e["init"]["total_chunk_count"], 1)  # se probó la subida en pedazos
        self.assertEqual(len(e["rangos"]), e["init"]["total_chunk_count"])
        self.assertFalse(list(self.cola.glob("*.json")))
        hecha = json.loads(next(self.hechas.glob("*.json")).read_text())
        self.assertEqual(hecha["resultado"]["estado"], "borrador_en_tiktok")
        self.assertEqual(hecha["resultado"]["publish_id"], "v_inbox_file~v2.123")
        self.assertEqual(hecha["resultado"]["costo_estimado_usd"], 1.28)  # 16 s x $0.08
        self.assertEqual((self.salida / "nuevo_refresh_token.txt").read_text(), "rft.rotado")
        aviso = (self.salida / "aviso.md").read_text()
        self.assertIn("Hola #prueba", aviso)
        self.assertIn("Contenido generado por IA", aviso)

    def test_token_malo_deja_video_y_avisa(self):
        self._poner_idea()
        codigo = self._correr({"TIKTOK_REFRESH_TOKEN": "rft.caducado"})
        self.assertEqual(codigo, 1)
        hecha = json.loads(next(self.hechas.glob("*.json")).read_text())
        self.assertEqual(hecha["resultado"]["estado"], "generado_sin_subir")
        self.assertTrue(list(self.salida.glob("*.mp4")))
        self.assertIn("tiktok_login.py", (self.salida / "aviso.md").read_text())

    def test_cola_vacia_sin_respaldo(self):
        with mock.patch.dict(os.environ, {"GCP_PROJECT": ""}):
            self.assertEqual(run.main(), 0)
        self.assertIn("vacía", (self.salida / "aviso_titulo.txt").read_text())

    def test_simulacion_no_mueve_la_cola(self):
        self._poner_idea()
        with mock.patch.dict(os.environ, {"SIMULAR": "1", "NO_SUBIR": "1"}):
            self.assertEqual(run.main(), 0)
        self.assertEqual(len(list(self.cola.glob("*.json"))), 1)
        self.assertIn("[SIMULACIÓN]", (self.salida / "aviso_titulo.txt").read_text())

    def test_tope_mensual_detiene_la_generacion(self):
        from datetime import datetime, timezone
        hecha = {"id": "vieja", "escenas": ["x"], "caption": "c",
                 "resultado": {"estado": "borrador_en_tiktok", "costo_estimado_usd": 9.5,
                               "fecha": datetime.now(timezone.utc).isoformat()}}
        (self.hechas / "vieja.json").write_text(json.dumps(hecha), encoding="utf-8")
        self._poner_idea()
        self.assertEqual(self._correr({}), 0)
        self.assertIn("Tope", (self.salida / "aviso_titulo.txt").read_text())
        self.assertEqual(len(list(self.cola.glob("*.json"))), 1)  # la idea sigue esperando
        self.assertNotIn("init", _TikTokFalso.estado)

    def test_config_de_entrega_es_un_clip(self):
        self.assertEqual(cargar_config()["video"]["max_clips_por_video"], 1)

    def test_idea_invalida_sale_de_la_cola(self):
        (self.cola / "0-mala.json").write_text('{"id": "mala"}', encoding="utf-8")
        self._poner_idea()
        self.assertEqual(self._correr({}), 0)
        estados = sorted(json.loads(p.read_text())["resultado"]["estado"] for p in self.hechas.glob("*.json"))
        self.assertEqual(estados, ["borrador_en_tiktok", "invalida"])


if __name__ == "__main__":
    unittest.main()
