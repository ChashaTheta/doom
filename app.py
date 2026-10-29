from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
WORKSPACE = ROOT / "workspace"
NOTES_DIR = WORKSPACE / "notes"
STATIC_DIR = ROOT / "static"
DB_PATH = DATA_DIR / "jarvis.db"

for folder in (DATA_DIR, WORKSPACE, NOTES_DIR, STATIC_DIR):
    folder.mkdir(parents=True, exist_ok=True)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:latest")
CLOUD_ENABLED = os.getenv("CLOUD_ENABLED", "false").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLOUD_MODEL = os.getenv("CLOUD_MODEL", "gpt-4.1-mini")

app = FastAPI(title="Jarvis Local", version="1.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    use_cloud: bool = False


class ActionRequest(BaseModel):
    action: str
    args: dict[str, Any] = {}


def connect_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with connect_db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            filename TEXT NOT NULL, created_at TEXT NOT NULL)""")
    # Make the assistant's workspace visible in File Explorer if it is new.
    (WORKSPACE / "README.txt").touch(exist_ok=True)


init_db()

SYSTEM_PROMPT = """You are Jarvis Local, a personal assistant running on the user's Windows computer.
You can answer questions, plan tasks, and suggest actions. You do not directly control Windows from chat.
The app has a separate Tools panel. Any action there requires the user to review and approve it.
Never claim to have performed a computer action unless the app confirms it.
Never request passwords, API keys, or secrets. The workspace is the only area available to file tools."""


def history(limit: int = 16) -> list[dict[str, str]]:
    with connect_db() as con:
        rows = con.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def save_message(role: str, content: str) -> None:
    with connect_db() as con:
        con.execute("INSERT INTO messages(role,content,created_at) VALUES(?,?,?)",
                    (role, content, datetime.now().isoformat(timespec="seconds")))


def ollama_chat(messages: list[dict[str, str]]) -> str:
    try:
        r = requests.post(f"{OLLAMA_BASE_URL}/api/chat",
                          json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
                          timeout=180)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "").strip() or "The model returned an empty response."
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Could not reach Ollama at {OLLAMA_BASE_URL}. Check Ollama and model '{OLLAMA_MODEL}'. Details: {exc}") from exc


def cloud_chat(messages: list[dict[str, str]]) -> str:
    if not CLOUD_ENABLED or not OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="Cloud mode is not configured in .env.")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        result = client.chat.completions.create(model=CLOUD_MODEL, messages=messages)
        return result.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cloud request failed: {exc}") from exc


def safe_workspace_path(relative: str) -> Path:
    """Resolve a user-supplied relative path and reject traversal outside workspace."""
    if not relative or Path(relative).is_absolute():
        raise HTTPException(status_code=400, detail="Use a relative path inside workspace.")
    candidate = (WORKSPACE / relative).resolve()
    try:
        candidate.relative_to(WORKSPACE.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path must stay inside workspace.") from exc
    return candidate


def workspace_files(query: str = "") -> list[dict[str, Any]]:
    results = []
    q = query.casefold().strip()
    for p in WORKSPACE.rglob("*"):
        if not p.is_file():
            continue
        rel_path = p.relative_to(WORKSPACE)
        if any(part.startswith(".") for part in rel_path.parts):
            continue
        rel = rel_path.as_posix()
        if q and q not in rel.casefold():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        results.append({"path": rel, "size": size})
        if len(results) >= 300:
            break
    return results


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    connected, models = False, []
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        connected = True
    except requests.RequestException:
        pass
    return {"app": "Jarvis Local", "version": "1.1.0", "local_model": OLLAMA_MODEL,
            "ollama_connected": connected, "installed_models": models,
            "cloud_enabled": bool(CLOUD_ENABLED and OPENAI_API_KEY),
            "workspace": str(WORKSPACE)}


@app.get("/api/history")
def get_history():
    with connect_db() as con:
        rows = con.execute("SELECT role,content,created_at FROM messages ORDER BY id DESC LIMIT 100").fetchall()
    return {"messages": [dict(r) for r in reversed(rows)]}


@app.delete("/api/history")
def clear_history():
    with connect_db() as con:
        con.execute("DELETE FROM messages")
    return {"ok": True}


@app.post("/api/chat")
def chat(req: ChatRequest):
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    save_message("user", text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history(16)
    answer = cloud_chat(messages) if req.use_cloud else ollama_chat(messages)
    save_message("assistant", answer)
    return {"reply": answer, "mode": "cloud" if req.use_cloud else "local"}


@app.get("/api/files")
def get_files(q: str = ""):
    return {"files": workspace_files(q[:200])}


@app.get("/api/notes")
def get_notes():
    with connect_db() as con:
        rows = con.execute("SELECT id,title,filename,created_at FROM notes ORDER BY id DESC LIMIT 100").fetchall()
    return {"notes": [dict(r) for r in rows]}


@app.post("/api/actions")
def run_action(req: ActionRequest):
    """Narrow allowlist only. The UI requires a confirmation click before posting an action."""
    action, args = req.action, req.args

    if action == "get_time":
        return {"ok": True, "message": datetime.now().astimezone().strftime("%A, %d %B %Y, %I:%M:%S %p %Z")}

    if action == "open_app":
        name = str(args.get("name", "")).strip().lower()
        # Deliberately narrow allowlist; no arbitrary executable paths or shell commands.
        allowed = {
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "paint": ["mspaint.exe"],
            "file explorer": ["explorer.exe", str(WORKSPACE)],
        }
        if name not in allowed:
            raise HTTPException(status_code=400, detail="Allowed apps: Notepad, Calculator, Paint, File Explorer.")
        try:
            subprocess.Popen(allowed[name], shell=False)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not open {name}: {exc}") from exc
        return {"ok": True, "message": f"Requested opening {name.title()}."}

    if action == "open_website":
        url = str(args.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(status_code=400, detail="Enter a valid http:// or https:// website URL.")
        webbrowser.open(url)
        return {"ok": True, "message": f"Requested opening {url} in your default browser."}

    if action == "create_note":
        title = str(args.get("title", "Untitled note")).strip()[:100] or "Untitled note"
        content = str(args.get("content", ""))[:30000]
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title).strip("-_").lower()[:60] or "note"
        filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}.md"
        path = safe_workspace_path(f"notes/{filename}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        with connect_db() as con:
            con.execute("INSERT INTO notes(title,filename,created_at) VALUES(?,?,?)",
                        (title, f"notes/{filename}", datetime.now().isoformat(timespec="seconds")))
        return {"ok": True, "message": "Note created.", "path": f"notes/{filename}"}

    if action == "make_folder":
        rel = str(args.get("path", "")).strip()
        target = safe_workspace_path(rel)
        if target.exists():
            raise HTTPException(status_code=409, detail="That path already exists.")
        target.mkdir(parents=True)
        return {"ok": True, "message": f"Created folder '{rel}' inside workspace."}

    if action in {"copy_file", "move_file"}:
        src_rel, dst_rel = str(args.get("source", "")).strip(), str(args.get("destination", "")).strip()
        src, dst = safe_workspace_path(src_rel), safe_workspace_path(dst_rel)
        if not src.is_file():
            raise HTTPException(status_code=404, detail="Source file not found inside workspace.")
        if dst.exists():
            raise HTTPException(status_code=409, detail="Destination already exists; refusing to overwrite.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            if action == "copy_file":
                shutil.copy2(src, dst)
                msg = f"Copied '{src_rel}' to '{dst_rel}'."
            else:
                shutil.move(str(src), str(dst))
                msg = f"Moved '{src_rel}' to '{dst_rel}'."
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"File operation failed: {exc}") from exc
        return {"ok": True, "message": msg}

    if action == "open_workspace_item":
        rel = str(args.get("path", "")).strip()
        target = safe_workspace_path(rel)
        if not target.exists():
            raise HTTPException(status_code=404, detail="Path not found inside workspace.")
        try:
            if target.is_dir():
                os.startfile(str(target))
            elif target.is_file():
                os.startfile(str(target))
            else:
                raise HTTPException(status_code=400, detail="Unsupported filesystem item.")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Windows could not open this item: {exc}") from exc
        return {"ok": True, "message": f"Requested opening workspace item '{rel}'."}

    if action == "read_text_file":
        rel = str(args.get("path", "")).strip()
        target = safe_workspace_path(rel)
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found inside workspace.")
        if target.stat().st_size > 200_000:
            raise HTTPException(status_code=400, detail="File is too large to preview (limit 200 KB).")
        if target.suffix.lower() not in {".txt", ".md", ".json", ".csv", ".log", ".py", ".js", ".html", ".css"}:
            raise HTTPException(status_code=400, detail="Preview is limited to text and code files.")
        return {"ok": True, "path": rel, "content": target.read_text(encoding="utf-8", errors="replace")}

    if action == "search_files":
        query = str(args.get("query", ""))[:200]
        found = workspace_files(query)
        return {"ok": True, "message": f"Found {len(found)} matching file(s).", "files": found}

    raise HTTPException(status_code=400, detail="Unknown or unsupported action.")
