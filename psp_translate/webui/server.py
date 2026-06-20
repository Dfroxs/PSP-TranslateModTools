"""Stdlib HTTP server backing the FFT WoTL translation web UI.

Endpoints (all JSON unless noted):

  GET  /                              -> index.html (single-file frontend)
  GET  /api/chapters                  -> [{file, num, exists, counts, source}]
  GET  /api/chapter?file=chapter_03   -> {metadata, blocks}  (out.json or input)
  POST /api/block                     -> update one block's id_final/status
  POST /api/byte-length               -> {text} -> {length}  (real encoder)
  POST /api/translate                 -> {file,start?,end?} -> {job_id}
  POST /api/script-check              -> {file} -> {job_id}
  GET  /api/jobs/<id>/stream?since=N  -> text/event-stream live log
  POST /api/jobs/<id>/stop            -> kill a running job
  POST /api/chat                      -> {messages,[context]} -> {reply} (Gemini)

Design notes:
  - The canonical per-chapter data file is `chapter_NN.out.json`. If it does not
    exist yet, reads fall back to the input `chapter_NN.json`; the first write
    materializes the out.json (gemini's resume-merge then keeps hand edits).
  - Jobs are real subprocesses (`python -u -m psp_translate <sub> ...`) so the
    streamed log is byte-for-byte what the CLI prints. SSE polls a line buffer.
  - No new dependency: chat reuses `google.genai` (already used by `gemini`).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from psp_translate import paths

# --- status -> UI bucket (must mirror the JS in index.html) ----------------
DONE = {"approved"}
SKIP = {"skip"}
ERROR = {"error"}
# everything machine-produced or untouched that still wants human eyes
REVIEW = {"auto", "needs_review", "pending"}


# ---------------------------------------------------------------------------
# Chapter file helpers
# ---------------------------------------------------------------------------

CHAPTER_RE = re.compile(r"^chapter_(\d+)$")


def _stem(file_arg: str) -> str:
    """Normalize a ?file= argument to a bare stem like 'chapter_03'."""
    name = Path(file_arg).name
    for suf in (".out.json", ".json"):
        if name.endswith(suf):
            name = name[: -len(suf)]
            break
    return name


def _input_path(stem: str) -> Path:
    return paths.WORKSPACE / f"{stem}.json"


def _out_path(stem: str) -> Path:
    return paths.WORKSPACE / f"{stem}.out.json"


def _read_chapter(stem: str) -> dict | None:
    """Prefer the .out.json (has edits/translations); fall back to input."""
    out = _out_path(stem)
    src = out if out.is_file() else _input_path(stem)
    if not src.is_file():
        return None
    data = json.loads(src.read_text(encoding="utf-8"))
    data.setdefault("metadata", {})
    data["metadata"]["_file"] = stem
    data["metadata"]["_has_out"] = out.is_file()
    return data


def _recount(blocks: list[dict]) -> dict:
    from collections import Counter

    c = Counter(b.get("status", "pending") for b in blocks)
    return {
        "total_blocks": len(blocks),
        "translated": c.get("auto", 0),
        "flagged": c.get("needs_review", 0),
        "errors": c.get("error", 0),
        "pending": c.get("pending", 0),
        "approved": c.get("approved", 0),
        "skipped": c.get("skip", 0),
    }


def _list_chapters() -> list[dict]:
    out = []
    for p in sorted(paths.WORKSPACE.glob("chapter_*.json")):
        if p.name.endswith(".out.json"):
            continue
        stem = p.stem  # chapter_NN
        m = CHAPTER_RE.match(stem)
        num = int(m.group(1)) if m else 0
        data = _read_chapter(stem)
        blocks = data.get("blocks", []) if data else []
        out.append(
            {
                "file": stem,
                "num": num,
                "exists": _out_path(stem).is_file(),
                "counts": _recount(blocks),
                "model": (data.get("metadata", {}) or {}).get("model"),
                "timestamp": (data.get("metadata", {}) or {}).get("timestamp"),
            }
        )
    out.sort(key=lambda d: d["num"])
    return out


def _save_block(stem: str, block_id: int, id_final, status) -> dict:
    """Update one block in the out.json (materializing it from input if needed)."""
    out = _out_path(stem)
    if out.is_file():
        data = json.loads(out.read_text(encoding="utf-8"))
    else:
        inp = _input_path(stem)
        if not inp.is_file():
            raise FileNotFoundError(stem)
        data = json.loads(inp.read_text(encoding="utf-8"))
    blocks = data.get("blocks", [])
    target = None
    for b in blocks:
        if b.get("id") == block_id:
            target = b
            break
    if target is None:
        raise KeyError(block_id)
    if id_final is not None:
        target["id_final"] = id_final
    if status is not None:
        target["status"] = status
    meta = data.setdefault("metadata", {})
    meta.update(_recount(blocks))
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Real-encoder byte length (mirrors gemini.encoded_byte_length)
# ---------------------------------------------------------------------------

def _encoded_byte_length(text: str) -> int | None:
    try:
        from psp_translate.codec.encode import encode_string, load_table

        c2b, c2m, n2b = load_table(paths.CHAR_TABLE)
        b = encode_string(text, c2b, c2m, n2b)
        if not b.endswith(b"\xfe"):
            b = b + b"\xfe"
        return len(b)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Job manager (streamed subprocess log)
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, job_id: str, cmd: list[str], label: str):
        self.id = job_id
        self.cmd = cmd
        self.label = label
        self.lines: list[str] = []
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.done = False
        self.returncode: int | None = None

    def start(self) -> None:
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        self.lines.append(f"$ {' '.join(self.cmd)}")
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=str(paths.ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            with self.lock:
                self.lines.append(line.rstrip("\n"))
        self.proc.wait()
        self.returncode = self.proc.returncode
        with self.lock:
            self.lines.append(f"[process exited with code {self.returncode}]")
        self.done = True

    def snapshot(self, since: int):
        with self.lock:
            return list(self.lines[since:]), len(self.lines), self.done, self.returncode

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._n = 0
        self._lock = threading.Lock()

    def create(self, cmd: list[str], label: str) -> Job:
        with self._lock:
            self._n += 1
            jid = f"job{self._n}"
        job = Job(jid, cmd, label)
        self._jobs[jid] = job
        job.start()
        return job

    def get(self, jid: str) -> Job | None:
        return self._jobs.get(jid)


JOBS = JobManager()


# ---------------------------------------------------------------------------
# Gemini chat (reuses google.genai)
# ---------------------------------------------------------------------------

CHAT_SYSTEM = (
    "Kamu asisten lokalisasi game EN->ID untuk Final Fantasy Tactics: The War "
    "of the Lions. Bantu reviewer menilai & memperbaiki terjemahan Indonesia. "
    "Jawab ringkas dan langsung. ATURAN PENTING: pertahankan semua kode kontrol "
    "<...> (mis. <SPEAKER>, <f8>, <e0>, <PRAYER>) dengan jumlah yang sama, "
    "jangan terjemahkan proper noun (nama tokoh/tempat/item), dan jaga agar "
    "terjemahan tidak melebihi batas byte bubble. Default jawab dalam Bahasa "
    "Indonesia."
)


def _has_genai() -> bool:
    try:
        import google.genai  # noqa: F401
        return True
    except Exception:
        return False


def _gemini_chat(messages: list[dict], context: str | None, model: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY belum di-set di environment server.")
    if not _has_genai():
        raise RuntimeError(
            "Paket 'google-genai' tidak ada di interpreter server. Jalankan webui "
            "dengan Python yang sama dengan translator (yang punya google-genai)."
        )
    from google import genai
    from google.genai import types as gt

    client = genai.Client(api_key=key)
    parts = []
    if context:
        parts.append(f"[Konteks block saat ini]\n{context}\n")
    for m in messages:
        role = "User" if m.get("role") == "user" else "Asisten"
        parts.append(f"{role}: {m.get('content', '')}")
    parts.append("Asisten:")
    resp = client.models.generate_content(
        model=model or "gemini-2.5-flash",
        contents=["\n\n".join(parts)],
        config=gt.GenerateContentConfig(
            system_instruction=CHAT_SYSTEM,
            temperature=0.4,
            max_output_tokens=2048,
        ),
    )
    return resp.text or ""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "FFTWebUI/1.0"

    # quieter logging
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers --
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # -- GET --
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/" or path == "/index.html":
                return self._serve_index()
            if path == "/api/status":
                return self._send_json({
                    "gemini_key": bool(os.environ.get("GEMINI_API_KEY", "").strip()),
                    "genai": _has_genai(),
                    "python": sys.version.split()[0],
                    "workspace": str(paths.WORKSPACE),
                })
            if path == "/api/chapters":
                return self._send_json(_list_chapters())
            if path == "/api/chapter":
                stem = _stem((qs.get("file") or [""])[0])
                data = _read_chapter(stem)
                if data is None:
                    return self._send_json({"error": "not found"}, 404)
                return self._send_json(data)
            m = re.match(r"^/api/jobs/([^/]+)/stream$", path)
            if m:
                since = int((qs.get("since") or ["0"])[0])
                return self._stream_job(m.group(1), since)
            return self._send_json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": str(e)}, 500)

    # -- POST --
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_body()
            if path == "/api/block":
                target = _save_block(
                    _stem(body["file"]), int(body["id"]),
                    body.get("id_final"), body.get("status"),
                )
                return self._send_json({"ok": True, "block": target})
            if path == "/api/byte-length":
                n = _encoded_byte_length(body.get("text", ""))
                return self._send_json({"length": n})
            if path == "/api/translate":
                return self._start_translate(body)
            if path == "/api/script-check":
                return self._start_script_check(body)
            if path == "/api/chat":
                reply = _gemini_chat(
                    body.get("messages", []), body.get("context"),
                    body.get("model", "gemini-2.5-flash"),
                )
                return self._send_json({"reply": reply})
            m = re.match(r"^/api/jobs/([^/]+)/stop$", path)
            if m:
                job = JOBS.get(m.group(1))
                if job:
                    job.stop()
                return self._send_json({"ok": True})
            return self._send_json({"error": "not found"}, 404)
        except KeyError as e:
            self._send_json({"error": f"missing field {e}"}, 400)
        except Exception as e:  # noqa: BLE001
            self._send_json({"error": str(e)}, 500)

    # -- job launchers --
    def _start_translate(self, body):
        stem = _stem(body["file"])
        inp, out = _input_path(stem), _out_path(stem)
        if not inp.is_file():
            return self._send_json({"error": f"input missing: {inp.name}"}, 404)
        cmd = [sys.executable, "-u", "-m", "psp_translate", "gemini",
               str(inp), str(out)]
        if body.get("start") is not None:
            cmd += ["--start", str(int(body["start"]))]
        if body.get("end") is not None:
            cmd += ["--end", str(int(body["end"]))]
        if body.get("batch"):
            cmd += ["--batch", str(int(body["batch"]))]
        if body.get("dry_run"):
            cmd += ["--dry-run"]
        job = JOBS.create(cmd, f"translate {stem}")
        return self._send_json({"job_id": job.id})

    def _start_script_check(self, body):
        stem = _stem(body["file"])
        out = _out_path(stem)
        if not out.is_file():
            return self._send_json(
                {"error": f"belum ada {out.name}; translate dulu."}, 400)
        cmd = [sys.executable, "-u", "-m", "psp_translate", "script-check",
               str(out)]
        job = JOBS.create(cmd, f"script-check {stem}")
        return self._send_json({"job_id": job.id})

    # -- SSE --
    def _stream_job(self, jid, since):
        job = JOBS.get(jid)
        if job is None:
            return self._send_json({"error": "no such job"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        cursor = since
        try:
            while True:
                new, total, done, rc = job.snapshot(cursor)
                for line in new:
                    payload = json.dumps({"line": line, "cursor": cursor + 1})
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    cursor += 1
                self.wfile.flush()
                if done and cursor >= total:
                    fin = json.dumps({"returncode": rc})
                    self.wfile.write(f"event: done\ndata: {fin}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    break
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # -- static --
    def _serve_index(self):
        index = paths.WEBUI_STATIC / "index.html"
        if not index.is_file():
            return self._send_json({"error": "index.html missing"}, 500)
        body = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _reexec_with_genai() -> None:
    """If this interpreter lacks google-genai (used by translate + chat), re-launch
    the server under one that has it. Translation deps may live in a different
    Python than the one the user typed. No-op if the current interpreter is fine
    or if no suitable interpreter is found (UI still works as viewer/editor)."""
    if _has_genai() or os.environ.get("_FFT_WEBUI_REEXEC"):
        return
    candidates = [
        shutil.which("python3"),
        "/usr/local/bin/python3",
        "/opt/homebrew/bin/python3",
        shutil.which("python"),
    ]
    seen = set()
    for cand in candidates:
        if not cand or cand in seen or not os.path.exists(cand):
            continue
        seen.add(cand)
        if os.path.realpath(cand) == os.path.realpath(sys.executable):
            continue
        try:
            r = subprocess.run([cand, "-c", "import google.genai"],
                               capture_output=True, timeout=15)
        except Exception:
            continue
        if r.returncode == 0:
            print(f"[webui] google-genai missing here; re-launching under {cand}")
            env = dict(os.environ, _FFT_WEBUI_REEXEC="1")
            os.execve(cand, [cand, "-m", "psp_translate", "webui", *sys.argv[1:]], env)
    print("[webui] WARNING: google-genai not found in any interpreter — "
          "Full Translate & chat will be unavailable (viewer/editor still work).",
          file=sys.stderr)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="psp-translate webui",
        description="Local web UI for the FFT WoTL translation workflow.",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if not paths.WORKSPACE.is_dir():
        print(f"ERROR: workspace dir not found: {paths.WORKSPACE}", file=sys.stderr)
        return 1

    _reexec_with_genai()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    key = "set" if os.environ.get("GEMINI_API_KEY") else "NOT set (translate/chat disabled)"
    print("=" * 60, flush=True)
    print("  FFT WoTL Translation Web UI", flush=True)
    print(f"  Serving:   {url}", flush=True)
    print(f"  Workspace: {paths.WORKSPACE}", flush=True)
    print(f"  Python:    {sys.version.split()[0]}  (genai: {_has_genai()})", flush=True)
    print(f"  GEMINI_API_KEY: {key}", flush=True)
    print("  Ctrl-C to stop.", flush=True)
    print("=" * 60, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
