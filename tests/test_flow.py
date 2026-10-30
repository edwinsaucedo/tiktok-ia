"""Pruebas del modo Flow con un Google Drive falso y el TikTok falso de test_pipeline."""
from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from test_pipeline import _PUERTO, _TikTokFalso  # fija TIKTOK_API_BASE antes de importar pipeline

from pipeline import drive as drive_mod  # noqa: E402
from pipeline import editar, flow, ideas, tiktok  # noqa: E402
from pipeline.comun import cargar_config  # noqa: E402

tiktok.API = f"http://127.0.0.1:{_PUERTO}"


def _hace(minutos: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat().replace("+00:00", "Z")


class _Resp:
    def __init__(self, codigo=200, datos=None, contenido=b""):
        self.status_code, self._datos, self._contenido = codigo, datos or {}, contenido

    def json(self):
        return self._datos

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._contenido), chunk_size):
            yield self._contenido[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class DriveFalso:
    """Simula /drive/v3/files: listar por carpeta, descargar (alt=media) y renombrar (PATCH)."""

    def __init__(self):
        self.hijos: dict[str, list[dict]] = {}
        self.contenido: dict[str, bytes] = {}
        self.renombrados: list[tuple[str, str]] = []
        self.descargas: list[str] = []
        self.falla_renombrar = False

    def carpeta(self, padre, id_, nombre):
        item = {"id": id_, "name": nombre, "mimeType": drive_mod.CARPETA,
                "createdTime": _hace(500), "modifiedTime": _hace(500)}
        self.hijos.setdefault(padre, []).append(item)
        self.hijos.setdefault(id_, [])
        return item

    def archivo(self, padre, id_, nombre, datos: bytes, hace_min=30, mime="video/mp4"):
        self.hijos.setdefault(padre, []).append(
            {"id": id_, "name": nombre, "mimeType": mime, "size": str(len(datos)),
             "createdTime": _hace(hace_min), "modifiedTime": _hace(hace_min)})
        self.contenido[id_] = datos

    def get(self, url, params=None, stream=False, timeout=None):
        params = params or {}
        if url.endswith("/drive/v3/files"):
            padre = re.match(r"'([^']+)' in parents", params["q"]).group(1)
            return _Resp(200, {"files": list(self.hijos.get(padre, []))})
        archivo_id = url.rsplit("/", 1)[-1]
        if params.get("alt") == "media" and archivo_id in self.contenido:
            self.descargas.append(archivo_id)
            return _Resp(200, contenido=self.contenido[archivo_id])
        return _Resp(404)

    def patch(self, url, params=None, json=None, timeout=None):
        if self.falla_renombrar:
            return _Resp(403)
        archivo_id = url.rsplit("/", 1)[-1]
        for items in self.hijos.values():
            for it in items:
                if it["id"] == archivo_id:
                    it["name"] = json["name"]
                    self.renombrados.append((archivo_id, json["name"]))
                    return _Resp(200, it)
        return _Resp(404)


def _video(ruta: Path, ancho: int, alto: int, segundos: int) -> bytes:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size={ancho}x{alto}:rate=24:duration={segundos}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(ruta)], check=True)
    return ruta.read_bytes()


class TestFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servidor = http.server.ThreadingHTTPServer(("127.0.0.1", _PUERTO), _TikTokFalso)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()
        tmp = Path(tempfile.mkdtemp())
        cls.vertical = _video(tmp / "v.mp4", 720, 1280, 3)
        cls.horizontal = _video(tmp / "h.mp4", 1280, 720, 2)
        shutil.rmtree(tmp)

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.flow_dir = self.tmp / "ideas" / "flow"
        self.hechas = self.tmp / "ideas" / "hechas"
        self.salida = self.tmp / "salida"
        self.flow_dir.mkdir(parents=True)
        self.hechas.mkdir(parents=True)
        historia = {"id": "001-anillo", "titulo": "El anillo", "gancho": "Le pidió matrimonio",
                    "escenas": ["x"] * 8, "caption": "Caption del anillo #novela"}
        (self.flow_dir / "001-anillo.json").write_text(json.dumps(historia), encoding="utf-8")
        self.cfg = cargar_config()
        self.cfg["flow"]["carpeta_drive_id"] = "RAIZ"
        self.cfg["flow"]["resolucion"] = "720p"  # más rápido en pruebas
        self.d = DriveFalso()
        _TikTokFalso.estado = {}
        self.parches = [
            mock.patch.object(flow, "CARPETA_FLOW", self.flow_dir),
            mock.patch.object(flow, "REGISTRO", self.tmp / "ideas" / "flow_procesadas.json"),
            mock.patch.object(flow, "CARPETA_SALIDA", self.salida),
            mock.patch.object(ideas, "CARPETA_HECHAS", self.hechas),
            mock.patch.object(flow, "cargar_config", lambda: self.cfg),
            mock.patch.object(flow, "Drive", lambda: drive_mod.Drive(sesion=self.d)),
            mock.patch.dict(os.environ, {"TIKTOK_CLIENT_KEY": "ck", "TIKTOK_CLIENT_SECRET": "cs",
                                         "TIKTOK_REFRESH_TOKEN": "rft.viejo"}),
        ]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- pruebas

    def test_solo_procesa_carpetas_listas(self):
        self.d.carpeta("RAIZ", "F1", "001 - El anillo")
        self.d.archivo("F1", "V1", "escena.mp4", self.vertical, hace_min=30)
        self.d.archivo("F1", "DOC", "Guion para Flow", b"x", mime="application/vnd.google-apps.document")
        self.d.carpeta("RAIZ", "F2", "002 - Subiendo")
        self.d.archivo("F2", "V2", "escena.mp4", self.vertical, hace_min=2)   # todavía subiendo
        self.d.carpeta("RAIZ", "F3", "✅ 003 - Ya hecha")
        self.d.archivo("F3", "V3", "escena.mp4", self.vertical, hace_min=90)
        self.d.carpeta("RAIZ", "F4", "004 - Vacía")                           # sin video
        self.d.carpeta("RAIZ", "F5", "Otra carpeta")
        listas = flow.buscar_listas(drive_mod.Drive(sesion=self.d), "RAIZ", 10)
        self.assertEqual([p.numero for p in listas], ["001"])
        self.assertEqual([v["id"] for v in listas[0].videos], ["V1"])

    def test_flujo_completo_a_tiktok(self):
        self.d.carpeta("RAIZ", "F1", "001 - El anillo")
        self.d.archivo("F1", "V1", "flow-export.mp4", self.horizontal)
        self.assertEqual(flow.main([]), 0)
        # TikTok recibió exactamente el video final
        video = next(self.salida.glob("*.mp4"))
        self.assertEqual(bytes(_TikTokFalso.estado["recibido"]), video.read_bytes())
        w, h = flow._dimensiones(video)
        self.assertEqual((w, h), (720, 1280))  # el horizontal quedó vertical
        # la carpeta de Drive quedó marcada y la historia pasó a hechas
        self.assertEqual(self.d.renombrados, [("F1", "✅ 001 - El anillo")])
        self.assertFalse(list(self.flow_dir.glob("*.json")))
        hecha = json.loads((self.hechas / "001-anillo.json").read_text())
        self.assertEqual(hecha["resultado"]["modo"], "flow")
        self.assertEqual(hecha["resultado"]["estado"], "borrador_en_tiktok")
        aviso = (self.salida / "aviso.md").read_text()
        self.assertIn("Caption del anillo #novela", aviso)
        self.assertIn("horizontal", aviso)
        self.assertIn("Recompensas", aviso)  # dura menos de 60 s
        self.assertIn("Borrador listo", (self.salida / "aviso_titulo.txt").read_text())
        # la siguiente revisión ya no encuentra trabajo
        self.assertEqual(flow.buscar_listas(drive_mod.Drive(sesion=self.d), "RAIZ", 10), [])

    def test_varios_clips_se_unen_en_orden(self):
        self.d.carpeta("RAIZ", "F1", "001 - El anillo")
        self.d.archivo("F1", "B", "2.mp4", self.horizontal)
        self.d.archivo("F1", "A", "1.mp4", self.vertical)
        self.assertEqual(flow.main([]), 0)
        self.assertEqual(self.d.descargas, ["A", "B"])
        self.assertAlmostEqual(editar.duracion(next(self.salida.glob("*.mp4"))), 5.0, delta=0.3)

    def test_si_no_puede_renombrar_no_sube_dos_veces(self):
        self.d.falla_renombrar = True
        self.d.carpeta("RAIZ", "F1", "001 - El anillo")
        self.d.archivo("F1", "V1", "video.mp4", self.vertical)
        self.assertEqual(flow.main([]), 0)
        self.assertIn("No pude renombrar", (self.salida / "aviso.md").read_text())
        self.assertEqual(flow.buscar_listas(drive_mod.Drive(sesion=self.d), "RAIZ", 10), [])

    def test_error_de_tiktok_marca_advertencia_y_se_puede_reintentar(self):
        os.environ["TIKTOK_REFRESH_TOKEN"] = "rft.caducado"
        self.d.carpeta("RAIZ", "F1", "001 - El anillo")
        self.d.archivo("F1", "V1", "video.mp4", self.vertical)
        self.assertEqual(flow.main([]), 1)
        self.assertEqual(self.d.renombrados, [("F1", "⚠️ 001 - El anillo")])
        self.assertEqual(len(list(self.flow_dir.glob("*.json"))), 1)  # la historia sigue pendiente
        # la usuaria le quita el ⚠️ al nombre y arregla el token: se reintenta
        self.d.hijos["RAIZ"][0]["name"] = "001 - El anillo"
        os.environ["TIKTOK_REFRESH_TOKEN"] = "rft.viejo"
        self.assertEqual(flow.main([]), 0)
        self.assertEqual(self.d.renombrados[-1], ("F1", "✅ 001 - El anillo"))

    def test_historia_desconocida_se_sube_igual_con_aviso(self):
        self.d.carpeta("RAIZ", "F9", "009 - Mi propia historia")
        self.d.archivo("F9", "V9", "video.mp4", self.vertical)
        self.assertEqual(flow.main([]), 0)
        self.assertIn("No encontré la historia 009", (self.salida / "aviso.md").read_text())

    def test_video_danado_marca_error(self):
        self.d.carpeta("RAIZ", "F1", "001 - El anillo")
        self.d.archivo("F1", "V1", "roto.mp4", b"esto no es un video" * 100)
        self.assertEqual(flow.main([]), 1)
        self.assertEqual(self.d.renombrados, [("F1", "❌ 001 - El anillo")])
        self.assertNotIn("init", _TikTokFalso.estado)

    def test_sin_carpeta_configurada_no_hace_nada(self):
        self.cfg["flow"]["carpeta_drive_id"] = ""
        self.assertEqual(flow.main(["--revisar"]), 0)


if __name__ == "__main__":
    unittest.main()
