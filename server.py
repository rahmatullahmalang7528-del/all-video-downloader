"""Video Downloader backend: FastAPI + yt-dlp. Needs ffmpeg installed (for best-quality merge).
Run:  pip install -r requirements.txt && uvicorn server:app --host 0.0.0.0 --port 8000
"""
import ipaddress, os, shutil, socket, tempfile
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp

app = FastAPI()
HERE = os.path.dirname(os.path.abspath(__file__))


def check_url(url: str) -> str:
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "invalid link")
    try:
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(400, "blocked address")
    except socket.gaierror:
        raise HTTPException(400, "host not found")
    return url.strip()


@app.get("/api/info")
def info(url: str):
    url = check_url(url)
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            d = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(422, f"could not read this link: {str(e)[:160]}")
    fmts = d.get("formats") or []
    heights = sorted({f["height"] for f in fmts if f.get("height") and f.get("vcodec") not in (None, "none")}, reverse=True)
    prog = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none") and f.get("ext") == "mp4" and f.get("url", "").startswith("http")]
    prog.sort(key=lambda f: f.get("height") or 0, reverse=True)
    return {
        "title": d.get("title"),
        "thumbnail": d.get("thumbnail"),
        "duration": d.get("duration"),
        "uploader": d.get("uploader"),
        "site": d.get("extractor_key"),
        "heights": heights,
        "preview_url": prog[0]["url"] if prog else None,
    }


@app.get("/api/download")
def download(url: str, bg: BackgroundTasks, height: int = 0):
    url = check_url(url)
    tmp = tempfile.mkdtemp(prefix="vd_")
    cap = f"[height<={height}]" if height else ""
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": f"bv*{cap}+ba/b{cap}/b",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(tmp, "video.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(422, f"download failed: {str(e)[:160]}")
    files = os.listdir(tmp)
    if not files:
        shutil.rmtree(tmp, ignore_errors=True)
        raise HTTPException(500, "no file produced")
    path = os.path.join(tmp, files[0])
    bg.add_task(shutil.rmtree, tmp, True)
    return FileResponse(path, media_type="video/mp4", filename="video.mp4")


app.mount("/", StaticFiles(directory=HERE, html=True), name="static")
