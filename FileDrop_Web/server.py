import argparse
import json
import os
import socket
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Dict, Optional, List
import asyncio

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

try:
    import qrcode
except Exception:  # pragma: no cover - optional dependency
    qrcode = None

APP_NAME = "FileDrop Web"
DEFAULT_PORT = 8000

app = FastAPI()

STATE = {
    "host": "0.0.0.0",
    "port": DEFAULT_PORT,
    "save_dir": Path.home() / "Downloads" / "FileDrop",
    "access_code": "",
    "clients": {},  # session_id -> {"name": str, "client_id": str, "ws": WebSocket, "can_receive": bool}
    "file_index": {},  # filename -> {"targets": Optional[List[str]], "size": int, "ts": int, "from": str}
}

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"


def _score_ip(ip: str) -> int:
    if ip.startswith("192.168."):
        return 3
    if ip.startswith("10."):
        return 2
    if ip.startswith("172."):
        parts = ip.split(".")
        try:
            second = int(parts[1])
        except Exception:
            return 0
        if 16 <= second <= 31:
            return 1
    return 0


def get_lan_ip() -> str:
    try:
        for iface in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface[4][0]
            if not (ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.")):
                continue
            if ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("100.64."):
                continue
            return ip
        # Prefer higher-scored private IPs if multiple exist
        candidates = []
        for iface in socket.getaddrinfo(socket.gethostname(), None):
            ip = iface[4][0]
            if not (ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172.")):
                continue
            if ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("100.64."):
                continue
            candidates.append((_score_ip(ip), ip))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def sanitize_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "Guest"
    return name[:40]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def unique_path(directory: Path, filename: str) -> Path:
    safe_name = Path(filename).name
    dest = directory / safe_name
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def require_code(request: Request, code: str | None = None) -> None:
    access_code = STATE["access_code"]
    if not access_code:
        return
    header_code = request.headers.get("x-filedrop-code")
    query_code = request.query_params.get("code")
    supplied = code or header_code or query_code
    if supplied != access_code:
        raise HTTPException(status_code=401, detail="Invalid access code")


async def broadcast(message: dict) -> None:
    dead = []
    for client_id, info in STATE["clients"].items():
        ws = info["ws"]
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(client_id)
    for client_id in dead:
        STATE["clients"].pop(client_id, None)


async def broadcast_except(session_id: str, message: dict) -> None:
    dead = []
    for cid, info in STATE["clients"].items():
        if cid == session_id:
            continue
        ws = info["ws"]
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(cid)
    for cid in dead:
        STATE["clients"].pop(cid, None)


async def notify_session(session_id: str, message: dict) -> None:
    info = STATE["clients"].get(session_id)
    if not info:
        return
    try:
        await info["ws"].send_text(json.dumps(message))
    except Exception:
        STATE["clients"].pop(session_id, None)


async def notify_target(target_id: str, message: dict) -> None:
    for session_id, info in STATE["clients"].items():
        if info["client_id"] == target_id:
            await notify_session(session_id, message)


async def notify_targets(target_ids: List[str], message: dict) -> None:
    for target_id in target_ids:
        await notify_target(target_id, message)


def is_admin_client(client_id: str | None) -> bool:
    if not client_id:
        return False
    return any(
        info.get("is_admin") and info.get("client_id") == client_id
        for info in STATE["clients"].values()
    )


def is_admin_request(request: Request, client_id: str | None) -> bool:
    if is_admin_client(client_id):
        return True
    remote_host = getattr(request.client, "host", "")
    lan_ip = get_lan_ip()
    return remote_host in {"127.0.0.1", "::1", lan_ip}


async def kick_session(session_id: str) -> None:
    info = STATE["clients"].get(session_id)
    if not info:
        return
    try:
        await info["ws"].close(code=4000)
    except Exception:
        pass
    STATE["clients"].pop(session_id, None)
    await broadcast_clients()


async def broadcast_clients() -> None:
    items = [
        {
            "session_id": session_id,
            "client_id": info["client_id"],
            "name": info["name"],
            "can_receive": info.get("can_receive", True),
            "is_admin": info.get("is_admin", False),
        }
        for session_id, info in STATE["clients"].items()
    ]
    await broadcast({"type": "clients", "items": items})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/info")
def info(request: Request) -> dict:
    lan_ip = get_lan_ip()
    port = STATE["port"]
    host = request.headers.get("host")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    origin = f"{scheme}://{host}" if host else ""
    lan_url = f"http://{lan_ip}:{port}"
    remote_host = getattr(request.client, "host", "")
    is_admin = remote_host in {"127.0.0.1", "::1", lan_ip}
    return {
        "name": APP_NAME,
        "lan_ip": lan_ip,
        "port": port,
        "lan_url": lan_url,
        "origin": origin,
        "requires_code": bool(STATE["access_code"]),
        "save_dir": str(STATE["save_dir"]),
        "is_admin": is_admin,
    }


@app.get("/api/settings")
def get_settings(request: Request) -> dict:
    require_code(request)
    return {
        "save_dir": str(STATE["save_dir"]),
        "port": STATE["port"],
        "requires_code": bool(STATE["access_code"]),
    }


@app.post("/api/settings")
async def update_settings(request: Request) -> dict:
    data = await request.json()
    code = data.get("code")
    if STATE["access_code"]:
        if code != STATE["access_code"]:
            raise HTTPException(status_code=401, detail="Invalid access code")
    save_dir = data.get("save_dir")
    if save_dir:
        STATE["save_dir"] = Path(save_dir)
        ensure_dir(STATE["save_dir"])
    access_code = data.get("access_code")
    if access_code is not None:
        STATE["access_code"] = access_code.strip()
    await broadcast(
        {
            "type": "settings",
            "save_dir": str(STATE["save_dir"]),
            "requires_code": bool(STATE["access_code"]),
        }
    )
    return {"ok": True}


@app.post("/api/settings/save-dialog")
async def save_dialog(request: Request) -> dict:
    require_code(request)
    client_id = request.headers.get("x-filedrop-client") or request.query_params.get("client_id")
    if not is_admin_request(request, client_id):
        raise HTTPException(status_code=403, detail="Only the server can choose the folder")
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Folder picker not available: {exc}") from exc
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.update()
        path = filedialog.askdirectory()
        root.destroy()
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Folder picker failed: {exc}") from exc
    if not path:
        raise HTTPException(status_code=400, detail="No folder chosen")
    STATE["save_dir"] = Path(path)
    ensure_dir(STATE["save_dir"])
    await broadcast(
        {
            "type": "settings",
            "save_dir": str(STATE["save_dir"]),
            "requires_code": bool(STATE["access_code"]),
        }
    )
    return {"ok": True, "save_dir": str(STATE["save_dir"])}


@app.get("/api/qr")
def qr(request: Request, url: str | None = None) -> Response:
    if qrcode is None:
        raise HTTPException(status_code=500, detail="qrcode is not installed")
    if not url:
        host = request.headers.get("host")
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        url = f"{scheme}://{host}" if host else ""
    img = qrcode.make(url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/files")
def list_files(request: Request) -> dict:
    require_code(request)
    ensure_dir(STATE["save_dir"])
    client_id = request.headers.get("x-filedrop-client") or request.query_params.get("client_id")
    files = []
    for entry in sorted(STATE["save_dir"].iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith("."):
            continue
        if entry.is_file():
            stat = entry.stat()
            meta = STATE["file_index"].get(entry.name)
            targets = meta.get("targets") if meta else None
            if targets and client_id not in targets:
                continue
            files.append(
                {
                    "name": entry.name,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "private": bool(targets),
                }
            )
    return {"files": files}


@app.get("/api/files/{filename}")
def download_file(filename: str, request: Request) -> FileResponse:
    require_code(request)
    client_id = request.headers.get("x-filedrop-client") or request.query_params.get("client_id")
    safe_name = Path(filename).name
    meta = STATE["file_index"].get(safe_name)
    targets = meta.get("targets") if meta else None
    if targets and client_id not in targets:
        raise HTTPException(status_code=403, detail="Not authorized")
    path = STATE["save_dir"] / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=safe_name)


@app.delete("/api/files/{filename}")
def delete_file(filename: str, request: Request) -> dict:
    require_code(request)
    client_id = request.headers.get("x-filedrop-client") or request.query_params.get("client_id")
    if not is_admin_request(request, client_id):
        raise HTTPException(status_code=403, detail="Only the server can remove files")
    safe_name = Path(filename).name
    meta = STATE["file_index"].get(safe_name)
    targets = meta.get("targets") if meta else None
    if targets and client_id not in targets:
        raise HTTPException(status_code=403, detail="Not authorized")
    path = STATE["save_dir"] / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    path.unlink()
    STATE["file_index"].pop(safe_name, None)
    return {"ok": True}


@app.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    name: str | None = Form(None),
    client_id: str | None = Form(None),
    target_ids: str | None = Form(None),
    code: str | None = Form(None),
) -> dict:
    require_code(request, code)
    # Require at least one receiver (other than sender) to avoid saving only locally
    receivers = {
        info["client_id"]
        for info in STATE["clients"].values()
        if info.get("can_receive", True) and info.get("client_id") != client_id
    }
    if target_ids:
        requested = [t for t in target_ids.split(",") if t]
        valid_targets = [t for t in requested if t in receivers]
        if not valid_targets:
            raise HTTPException(status_code=409, detail="No receivers connected")
        # Include sender so they can see the file in their list.
        if client_id and client_id not in valid_targets:
            valid_targets.append(client_id)
        targets = valid_targets
    else:
        if not receivers:
            raise HTTPException(status_code=409, detail="No receivers connected")
        targets = None

    ensure_dir(STATE["save_dir"])
    dest = unique_path(STATE["save_dir"], file.filename)
    size = 0
    with dest.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            size += len(chunk)
    await file.close()
    meta = {
        "targets": targets,
        "size": size,
        "ts": int(time.time()),
        "from": sanitize_name(name),
    }
    STATE["file_index"][dest.name] = meta
    payload = {
        "type": "file",
        "name": dest.name,
        "size": size,
        "from": sanitize_name(name),
        "client_id": client_id,
        "targets": targets,
        "ts": int(time.time()),
    }
    if targets:
        await notify_targets(targets, payload)
    else:
        await broadcast(payload)
    return {"ok": True, "name": dest.name, "size": size}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = None
    try:
        hello = await websocket.receive_text()
        data = json.loads(hello)
        if data.get("type") != "hello":
            await websocket.close(code=1002)
            return
        if STATE["access_code"] and data.get("code") != STATE["access_code"]:
            await websocket.send_text(json.dumps({"type": "error", "code": "unauthorized"}))
            await websocket.close(code=1008)
            return
        name = sanitize_name(data.get("name"))
        can_receive = bool(data.get("can_receive", True))
        remote_host = getattr(websocket.client, "host", "")
        lan_ip = get_lan_ip()
        is_admin = remote_host in {"127.0.0.1", "::1", lan_ip}
        client_id = data.get("client_id") or str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        STATE["clients"][session_id] = {
            "name": name,
            "client_id": client_id,
            "ws": websocket,
            "can_receive": can_receive,
            "is_admin": is_admin,
        }
        await websocket.send_text(
            json.dumps(
                {
                    "type": "welcome",
                    "session_id": session_id,
                    "client_id": client_id,
                    "name": name,
                    "server": {
                        "name": APP_NAME,
                        "requires_code": bool(STATE["access_code"]),
                        "can_receive": can_receive,
                    },
                    "is_admin": is_admin,
                }
            )
        )
        await broadcast_clients()
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "note":
                payload = {
                    "type": "note",
                    "from": name,
                    "session_id": session_id,
                    "client_id": client_id,
                    "text": (msg.get("text") or "")[:4000],
                    "ts": int(time.time()),
                }
                targets = msg.get("to")
                if isinstance(targets, list) and targets:
                    await asyncio.gather(*(notify_session(t, payload) for t in targets))
                else:
                    await broadcast_except(session_id, payload)
            elif mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif mtype == "kick":
                target = msg.get("target")
                code = msg.get("code")
                if STATE["access_code"] and code != STATE["access_code"]:
                    continue
                if target:
                    await kick_session(target)
            elif mtype == "mode":
                can_receive = bool(msg.get("can_receive", True))
                info = STATE["clients"].get(session_id)
                if info:
                    info["can_receive"] = can_receive
                    await broadcast_clients()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if session_id and session_id in STATE["clients"]:
            STATE["clients"].pop(session_id, None)
            await broadcast_clients()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FileDrop Web server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--save-dir", default=str(Path.home() / "Downloads" / "FileDrop"))
    parser.add_argument("--access-code", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    STATE["host"] = args.host
    STATE["port"] = args.port
    STATE["save_dir"] = Path(args.save_dir)
    STATE["access_code"] = args.access_code
    ensure_dir(STATE["save_dir"])

    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover
        raise SystemExit("uvicorn is required. Install with: pip install -r requirements.txt") from exc

    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
