# Jarvis Local — Windows 11 Personal AI Assistant

A local-first personal assistant with a browser chat UI, Ollama model support, optional OpenAI cloud fallback, SQLite conversation memory, and guarded Windows tools.

## Requirements
- Windows 11
- Python 3.11 or 3.12 (64-bit)
- Ollama for local AI: https://ollama.com/download/windows
- 8 GB RAM: start with `qwen2.5:3b` or `llama3.2:3b`; performance depends on available memory.

## Quick start
1. Install Python and Ollama from the links above. During Python setup, enable **Add Python to PATH**.
2. Open PowerShell in this project folder.
3. Run:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\setup.ps1
   ```
4. If Ollama is installed but the model isn't downloaded yet:
   ```powershell
   ollama pull qwen2.5:3b
   ```
   Ollama should be running in the background. Check with `ollama list`.
5. Start the assistant:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn app:app --host 127.0.0.1 --port 8000
   ```
6. Open http://127.0.0.1:8000 in your browser.

## Optional cloud model
Local mode is the default. To enable cloud fallback:
1. Copy `.env.example` to `.env`.
2. Set `CLOUD_ENABLED=true`, `OPENAI_API_KEY=...`, and optionally `CLOUD_MODEL=gpt-4.1-mini`.
3. Restart the server.
The app only sends a user message and recent conversation turns to the cloud when you explicitly choose **Use cloud for this reply** in the UI. Do not send secrets or private documents to cloud models.

## What it can do
- Chat locally with Ollama.
- Remember conversation history in a local SQLite database.
- Create and read notes inside `workspace/notes`.
- List/search files only inside the app's `workspace` folder.
- Open a website after a confirmation click.
- Open Calculator or Notepad after a confirmation click.
- Read the current time and show available tools.

## Safety model
- The server binds to `127.0.0.1` only. Do not expose it to your LAN or the public internet.
- It does not provide arbitrary shell execution.
- File tools are sandboxed to `workspace/`.
- Website/app actions require a separate confirmation click.
- Treat model output as untrusted. Review notes and actions before confirming.
- Keep API keys only in `.env`; never commit `.env` to GitHub.

## Troubleshooting
- **`ollama` not found**: install Ollama, then close and reopen PowerShell.
- **Model unavailable**: run `ollama pull qwen2.5:3b`, then `ollama list`.
- **Connection refused to Ollama**: launch Ollama from the Start menu or run `ollama serve` in a separate terminal if needed.
- **Python package errors**: run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- **Port in use**: use `--port 8001` and open `http://127.0.0.1:8001`.
- **Voice input**: the microphone button uses browser speech recognition where supported; browser availability and language support vary. Typed chat always works.
- **Cloud option missing**: configure `.env` and restart the server.

## Project structure
```text
jarvis-local/
  app.py
  requirements.txt
  setup.ps1
  .env.example
  .gitignore
  static/index.html
  workspace/notes/
  data/
```

## Limitations
This is a useful local-first MVP, not unrestricted autonomous control of Windows. It does not silently read all your files, execute arbitrary commands, send email, or bypass permissions. More integrations can be added incrementally with explicit approvals.
