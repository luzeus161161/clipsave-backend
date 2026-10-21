import os
import re
import tempfile
import shutil
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from starlette.background import BackgroundTask
import yt_dlp

ROOT = Path(__file__).parent
app = FastAPI(title="ClipSave")

# Erlaubt die Verbindung von der Netlify-Website zum Render-Backend.
# Nach dem ersten Deployment kann diese Liste auf deine genaue Netlify-Domain begrenzt werden.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
ALLOWED_HOSTS = {
    "instagram.com", "www.instagram.com", "instagr.am", "www.instagr.am",
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com",
    "vt.tiktok.com"
}

class DownloadRequest(BaseModel):
    url: HttpUrl
    platform: str

def cleanup(path: str):
    shutil.rmtree(path, ignore_errors=True)

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/download")
def download(req: DownloadRequest):
    url = str(req.url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Bitte nutze einen HTTPS-Link.")
    if host not in ALLOWED_HOSTS:
        raise HTTPException(status_code=400, detail="Nur Instagram- und TikTok-Links sind erlaubt.")
    if req.platform not in ("instagram", "tiktok"):
        raise HTTPException(status_code=400, detail="Unbekannte Plattform.")
    if req.platform == "instagram" and not (host.endswith("instagram.com") or host.endswith("instagr.am")):
        raise HTTPException(status_code=400, detail="Das ist kein Instagram-Link.")
    if req.platform == "tiktok" and not host.endswith("tiktok.com"):
        raise HTTPException(status_code=400, detail="Das ist kein TikTok-Link.")

    temp_dir = tempfile.mkdtemp(prefix="clipsave-")
    output_template = str(Path(temp_dir) / "clip.%(ext)s")
    opts = {
        "outtmpl": output_template,
        "format": "mp4/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "retries": 1,
        "fragment_retries": 1,
        "max_filesize": 200 * 1024 * 1024,
        "restrictfilenames": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = Path(ydl.prepare_filename(info))
            if not filepath.exists():
                candidates = list(Path(temp_dir).glob("clip.*"))
                if candidates:
                    filepath = candidates[0]
            if not filepath.exists() or not filepath.is_file():
                raise RuntimeError("Die Videodatei wurde nicht erstellt.")
            ext = filepath.suffix or ".mp4"
            safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", str(info.get("title") or "clip")).strip("-._")
            safe_title = (safe_title[:70] or "clip") + ext
            return FileResponse(
                path=str(filepath),
                media_type="video/mp4" if ext.lower() == ".mp4" else "application/octet-stream",
                filename=safe_title,
                background=BackgroundTask(cleanup, temp_dir),
            )
    except HTTPException:
        cleanup(temp_dir)
        raise
    except Exception as exc:
        cleanup(temp_dir)
        message = str(exc)
        if "Private" in message or "login" in message.lower() or "Sign in" in message:
            raise HTTPException(status_code=422, detail="Der Clip ist möglicherweise privat oder erfordert eine Anmeldung. Diese Website umgeht keine Zugriffsbeschränkungen.")
        raise HTTPException(status_code=422, detail="Download nicht möglich. Der Link ist eventuell nicht öffentlich verfügbar oder die Plattform blockiert den Abruf. Bitte prüfe den Link und versuche es später erneut.")

app.mount("/", StaticFiles(directory=ROOT, html=True), name="static")
