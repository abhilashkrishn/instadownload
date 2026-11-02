import asyncio
from collections import defaultdict
import glob
import hashlib
import hmac
import os
import re
import secrets
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ---------------------------------------------------------------------------
# Native .env Parser
# ---------------------------------------------------------------------------
def load_env(filepath: str | Path = ".env") -> None:
    env_file = Path(__file__).parent / filepath
    if env_file.is_file():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip("'\"")

load_env()

import instaloader
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

app = FastAPI()

# ---------------------------------------------------------------------------
# Auth Configuration
# ---------------------------------------------------------------------------
VALID_USERNAME = os.getenv("APP_USER", "dhanya")
VALID_PASSWORD = os.getenv("APP_PASSWORD")

if not VALID_PASSWORD:
    raise RuntimeError("APP_PASSWORD is missing or not set in your .env file!")

raw_session_secret = os.getenv("SESSION_SECRET")
if not raw_session_secret:
    raise RuntimeError("SESSION_SECRET is missing or not set in your .env file!")
SECRET_KEY = raw_session_secret.encode()

COOKIE_NAME = "session_token"
COOKIE_PATH = os.getenv("COOKIE_PATH", "/")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
SESSION_DURATION_SECONDS = 86400 * 30  # 30 days


def create_session_token(username: str) -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(SECRET_KEY, f"{username}:{timestamp}".encode(), hashlib.sha256).hexdigest()
    return f"{username}:{timestamp}:{signature}"


def verify_session_token(token: str | None) -> bool:
    if not token or token.count(":") != 2:
        return False
    username, timestamp_str, signature = token.split(":")
    if username != VALID_USERNAME:
        return False

    expected_sig = hmac.new(SECRET_KEY, f"{username}:{timestamp_str}".encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected_sig):
        return False

    try:
        timestamp = int(timestamp_str)
    except (ValueError, TypeError):
        return False

    # Reject future timestamps and expired tokens
    if not (0 <= time.time() - timestamp <= SESSION_DURATION_SECONDS):
        return False

    return True


# ---------------------------------------------------------------------------
# Storage & Active Download Tracking
# ---------------------------------------------------------------------------
STORAGE_DIR = os.path.join(tempfile.gettempdir(), "fastapi_insta_storage")
os.makedirs(STORAGE_DIR, exist_ok=True)

TEMPLATES_DIR = Path(__file__).parent / "templates"

_executor = ThreadPoolExecutor(max_workers=2)

# Reference counter for shortcodes actively in use (processing, waiting, or streaming)
_active_refs: dict[str, int] = defaultdict(int)
# Events to allow concurrent requests to wait if a shortcode is already fetching
_in_flight_events: dict[str, asyncio.Event] = {}
# Detached tasks tracking thread pool workers across client disconnections
_in_flight_tasks: dict[str, asyncio.Task] = {}
_lifecycle_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def extract_shortcode(url: str) -> str | None:
    if not url:
        return None
    match = re.search(r"/(?:p|reels?|tv)/([A-Za-z0-9_-]+)", url.strip())
    return match.group(1) if match else None


def _find_media_files(target_folder: str) -> tuple[list[str], list[str]]:
    mp4_files = glob.glob(os.path.join(target_folder, "*.mp4"))
    image_files = (
        glob.glob(os.path.join(target_folder, "*.jpg"))
        + glob.glob(os.path.join(target_folder, "*.webp"))
    )
    return mp4_files, image_files


async def _cleanup_old_temp_files(max_age_seconds: int = 600) -> None:
    """Safely cleans up stale folders, verifying lock state immediately before deletion."""
    now = time.time()
    try:
        entries = list(os.scandir(STORAGE_DIR))
    except Exception:
        return

    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            if now - entry.stat().st_mtime <= max_age_seconds:
                continue

            folder_name = entry.name
            async with _lifecycle_lock:
                if _active_refs.get(folder_name, 0) > 0 or folder_name in _in_flight_events:
                    continue
                shutil.rmtree(entry.path, ignore_errors=True)
        except Exception:
            continue


def _run_instaloader(shortcode: str, target_folder: str) -> None:
    loader = instaloader.Instaloader(
        dirname_pattern=target_folder,
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
    )
    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    loader.download_post(post, target="")


def _decrement_shortcode_locked(shortcode: str) -> None:
    """Decrements active usage reference count; MUST be called while holding _lifecycle_lock."""
    if _active_refs[shortcode] > 1:
        _active_refs[shortcode] -= 1
    else:
        _active_refs.pop(shortcode, None)


async def _release_shortcode(shortcode: str) -> None:
    """Helper to decrement reference count safely under lock."""
    async with _lifecycle_lock:
        _decrement_shortcode_locked(shortcode)


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if verify_session_token(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse(url="./", status_code=303)

    login_file = TEMPLATES_DIR / "login.html"
    if not login_file.exists():
        return HTMLResponse("<h2>Error: templates/login.html not found</h2>", status_code=500)

    with open(login_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def api_login(credentials: LoginRequest):
    user_ok = secrets.compare_digest(credentials.username, VALID_USERNAME)
    pass_ok = secrets.compare_digest(credentials.password, VALID_PASSWORD)

    if not (user_ok and pass_ok):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Invalid username or password"},
        )

    token = create_session_token(credentials.username)
    res = JSONResponse(content={"success": True})
    res.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        max_age=SESSION_DURATION_SECONDS,
        expires=SESSION_DURATION_SECONDS,
        path=COOKIE_PATH,
    )
    return res


@app.get("/logout")
async def logout():
    res = RedirectResponse(url="login", status_code=303)
    res.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
    return res


# ---------------------------------------------------------------------------
# App Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not verify_session_token(token):
        return RedirectResponse(url="login", status_code=303)

    index_file = TEMPLATES_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h2>Error: templates/index.html not found</h2>", status_code=500)

    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


class ProcessRequest(BaseModel):
    url: str = ""


async def _execute_download_job(shortcode: str, target_folder: str) -> str | None:
    """Executes the Instaloader download in the worker pool and guarantees
    lifecycle teardown only after the worker thread finishes, independent of
    client HTTP cancellation.
    """
    loop = asyncio.get_running_loop()
    error_msg = None
    try:
        await loop.run_in_executor(_executor, _run_instaloader, shortcode, target_folder)
    except Exception as exc:
        error_msg = str(exc)
    finally:
        async with _lifecycle_lock:
            _in_flight_tasks.pop(shortcode, None)
            event = _in_flight_events.pop(shortcode, None)
            if event:
                event.set()
            _decrement_shortcode_locked(shortcode)
    return error_msg
    
@app.post("/api/process")
async def process_url(body: ProcessRequest, request: Request) -> JSONResponse:
    if not verify_session_token(request.cookies.get(COOKIE_NAME)):
        return JSONResponse({"success": False, "error": "Unauthorized. Please log in."}, status_code=401)

    shortcode = extract_shortcode(body.url)
    if not shortcode:
        return JSONResponse(
            {"success": False, "error": "Invalid Instagram URL. Please provide a valid link."},
            status_code=400,
        )

    # 1. Stale directory cleanup
    await _cleanup_old_temp_files()

    target_folder = os.path.join(STORAGE_DIR, shortcode)
    should_download = False
    in_flight_event = None

    # 2. Concurrency arbitration under lock
    async with _lifecycle_lock:
        if shortcode in _in_flight_events:
            in_flight_event = _in_flight_events[shortcode]
            _active_refs[shortcode] += 1
        elif _active_refs.get(shortcode, 0) > 0:
            mp4_files, image_files = _find_media_files(target_folder)
            if mp4_files or image_files:
                download_url = f"download/{shortcode}?t={int(time.time())}"
                return JSONResponse({"success": True, "download_url": download_url})
            
            # Directory registered but empty or missing valid files; clean and redownload
            should_download = True
            _in_flight_events[shortcode] = asyncio.Event()
            _active_refs[shortcode] += 1
            shutil.rmtree(target_folder, ignore_errors=True)
            os.makedirs(target_folder, exist_ok=True)
        else:
            should_download = True
            _in_flight_events[shortcode] = asyncio.Event()
            _active_refs[shortcode] += 1
            shutil.rmtree(target_folder, ignore_errors=True)
            os.makedirs(target_folder, exist_ok=True)

    # 3. Handle waiting requests safely
    if in_flight_event:
        try:
            await in_flight_event.wait()
            async with _lifecycle_lock:
                mp4_files, image_files = _find_media_files(target_folder)
            if mp4_files or image_files:
                download_url = f"download/{shortcode}?t={int(time.time())}"
                return JSONResponse({"success": True, "download_url": download_url})
            return JSONResponse(
                {"success": False, "error": f"Failed to retrieve media for post {shortcode}."},
                status_code=500,
            )
        finally:
            await _release_shortcode(shortcode)

    # 4. Perform extraction
# 4. Perform extraction decoupled from HTTP request cancellation
    if should_download:
        task = asyncio.create_task(_execute_download_job(shortcode, target_folder))
        async with _lifecycle_lock:
            _in_flight_tasks[shortcode] = task

        try:
            # Shield the download task from caller cancellation
            download_error = await asyncio.shield(task)
        except asyncio.CancelledError:
            # If the HTTP client aborts, allow the task to continue to completion
            # so the thread and directories are not abandoned or corrupt.
            raise

        if download_error:
            return JSONResponse(
                {"success": False, "error": f"Download failed: {download_error}"},
                status_code=500,
            )

    async with _lifecycle_lock:
        mp4_files, image_files = _find_media_files(target_folder)

    if not mp4_files and not image_files:
        return JSONResponse(
            {"success": False, "error": f"No media found for post {shortcode}."},
            status_code=404,
        )

    download_url = f"download/{shortcode}?t={int(time.time())}"
    return JSONResponse({"success": True, "download_url": download_url})


@app.get("/download/{shortcode}")
async def download_file(shortcode: str, request: Request):
    if not verify_session_token(request.cookies.get(COOKIE_NAME)):
        return JSONResponse({"error": "Unauthorized. Please log in."}, status_code=401)

    if not re.fullmatch(r"[A-Za-z0-9_-]+", shortcode):
        return JSONResponse({"error": "File not found or expired."}, status_code=404)

    target_folder = os.path.join(STORAGE_DIR, shortcode)

    # Atomic discovery, selection, and refcount increment
    async with _lifecycle_lock:
        mp4_files, image_files = _find_media_files(target_folder)
        if mp4_files:
            selected_file = mp4_files[0]
            ext = "mp4"
            media_type = "video/mp4"
        elif image_files:
            selected_file = image_files[0]
            ext = selected_file.rsplit(".", 1)[-1]
            media_type = "image/jpeg" if ext == "jpg" else "image/webp"
        else:
            return JSONResponse({"error": "File not found or expired."}, status_code=404)

        _active_refs[shortcode] += 1

    filename = f"{shortcode}.{ext}"
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }

    try:
        return FileResponse(
            path=selected_file,
            media_type=media_type,
            filename=filename,
            headers=headers,
            background=BackgroundTask(_release_shortcode, shortcode),
        )
    except Exception:
        await _release_shortcode(shortcode)
        raise


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8200, reload=True)