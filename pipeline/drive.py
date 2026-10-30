"""Acceso mínimo a Google Drive (API v3) con la misma cuenta de servicio de Google Cloud.

La cuenta de servicio solo necesita permiso de EDITOR sobre la carpeta "TikTok IA"
(se comparte desde Drive con el correo de la cuenta de servicio). Solo lee, descarga y renombra:
no crea archivos, así que no usa almacenamiento.
"""
from __future__ import annotations

import os
from pathlib import Path

API = os.environ.get("DRIVE_API_BASE", "https://www.googleapis.com").rstrip("/")
CARPETA = "application/vnd.google-apps.folder"
EXTENSIONES_VIDEO = (".mp4", ".mov", ".m4v", ".webm")


def es_video(archivo: dict) -> bool:
    return (archivo.get("mimeType", "").startswith("video/")
            or archivo.get("name", "").lower().endswith(EXTENSIONES_VIDEO))


class Drive:
    def __init__(self, sesion=None):
        if sesion is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            cred, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
            sesion = AuthorizedSession(cred)
        self.s = sesion

    def listar(self, carpeta_id: str) -> list[dict]:
        archivos, token = [], None
        while True:
            params = {
                "q": f"'{carpeta_id}' in parents and trashed = false",
                "fields": "nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, size)",
                "pageSize": 200,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if token:
                params["pageToken"] = token
            r = self.s.get(f"{API}/drive/v3/files", params=params, timeout=60)
            if r.status_code == 404:
                raise RuntimeError(
                    "Drive no encuentra la carpeta. Revisa flow.carpeta_drive_id en config.json y que la "
                    "carpeta esté compartida (como Editor) con el correo de la cuenta de servicio.")
            r.raise_for_status()
            datos = r.json()
            archivos += datos.get("files", [])
            token = datos.get("nextPageToken")
            if not token:
                return archivos

    def descargar(self, archivo_id: str, destino: Path) -> Path:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with self.s.get(f"{API}/drive/v3/files/{archivo_id}",
                        params={"alt": "media", "supportsAllDrives": "true"},
                        stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(destino, "wb") as f:
                for pedazo in r.iter_content(chunk_size=1024 * 1024):
                    f.write(pedazo)
        return destino

    def renombrar(self, archivo_id: str, nombre: str) -> None:
        r = self.s.patch(f"{API}/drive/v3/files/{archivo_id}",
                         params={"supportsAllDrives": "true"}, json={"name": nombre}, timeout=60)
        if r.status_code in (403, 404):
            raise RuntimeError(
                "Drive no dejó renombrar la carpeta: comparte la carpeta 'TikTok IA' como EDITOR "
                "con el correo de la cuenta de servicio.")
        r.raise_for_status()
