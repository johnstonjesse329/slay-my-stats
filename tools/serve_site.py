"""
tools/serve_site.py — Local dev server emulating the S3 + CloudFront setup.

stdlib-only (http.server), so no extra install is needed to preview the
built site. Routing mirrors what CloudFront will be configured to do against
the site bucket:

    /, /u/<anything>, /<page> -> index.html, built fresh (client-side router)
    /page-<page>.html    -> site/pages/<page>.html      (read live, so edits
    /home-intro.html     -> site/home-intro.html         show on refresh)
    /users/<name>        -> local_data/users/<name>     (gzip'd profile summaries,
                                                         index, site stats)
    /users/<slug>/<month> -> local_data/users/<slug>/<month>  (a profile's runs, by month)
    /users/_uploads/<id> -> local_data/users/_uploads/<id>  (upload results)
    /card_final/...      -> card_final/...              (game art, repo root)
    /card_portraits/...  -> card_portraits/...
    /node_icons/...      -> node_icons/...
    /relic_images/...    -> relic_images/...
    /potion_images/...   -> potion_images/...
    /ui_icons/...        -> ui_icons/...
    /thumbs/...          -> thumbs/...                  (icon-size copies of the art)
    everything else      -> dist/...   (/ -> dist/index.html)

    POST /api/ingest     -> the ingest Lambda's authorize(), storing into
                            local_data/ (stands in for the Function URL); the
                            upload URL it hands out is this server's own:
    POST /api/ingest/mod -> the same for the game mod: authorize_mod(), for
                            the SteamID64s in $MOD_ALLOWLIST (stands in for
                            the Function URL's /mod)
    POST /api/raw-upload -> stands in for the presigned S3 POST: stores the
                            file under local_data/raw/ and processes it on
                            the spot (stands in for the S3 event)

A missing /users/<name> answers 403, not 404 — that's what S3 (behind
CloudFront with Origin Access Control) returns for a key that doesn't exist,
and boot.js needs to tell "no data yet" apart from a real network failure.

Only one dev server is ever needed, so starting this again on the same port
replaces an earlier one -- see "One dev server per port" below.

Usage:
    python tools/serve_site.py
    python tools/serve_site.py --port 8080
"""

import email.parser
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

_REPO_ROOT = Path(__file__).resolve().parent.parent
# The ingest Lambda's handler (and the run.py it imports), so /api/ingest
# runs exactly the code that's deployed.
sys.path[:0] = [str(_REPO_ROOT), str(_REPO_ROOT / "infra" / "lambda" / "ingest")]
import handler as ingest_handler  # noqa: E402
import build_site  # noqa: E402
_DIST = _REPO_ROOT / "dist"
_USERS_DIR = _REPO_ROOT / "local_data" / "users"
_DATA_DIR = _USERS_DIR.parent

# Raw keys handed out by /api/ingest and not yet used, with the size each may
# be: what the presigned POST's signature pins down on real S3.
_issued_keys: dict[str, int] = {}
_issued_lock = threading.Lock()

# Committed game-art folders, served straight from the repo root — these
# mirror the root-absolute paths the real site bucket serves them at.
_ART_DIRS = {"card_final", "card_portraits", "node_icons", "relic_images", "potion_images", "ui_icons", "thumbs"}

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".webp": "image/webp",
    ".png":  "image/png",
    ".ttf":  "font/ttf",
    ".gz":   "application/gzip",
}


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _safe_join(root: Path, parts: list[str]) -> Path | None:
    """Join URL path segments onto root, refusing to let them escape it."""
    candidate = root
    for part in parts:
        if part in ("", ".", ".."):
            continue
        candidate = candidate / part
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:
        return None
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        return None
    return resolved_candidate


def _presign(key, max_bytes, expires):
    """Stands in for the store's presign_post: an upload URL on this server."""
    with _issued_lock:
        _issued_keys[key] = max_bytes
    return {"url": "/api/raw-upload", "fields": {"key": key, "Content-Type": "application/gzip"}}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url_path = unquote(urlsplit(self.path).path)
        parts = [p for p in url_path.split("/") if p]

        # Point the upload page at this server's own /api/ingest instead of
        # whatever Function URL the last build baked in.
        if url_path == "/site-config.json":
            self._send_json(200, {"ingestUrl": "/api/ingest"})
            return

        # The SPA shell, built per request so a new site/pages/ file shows up
        # in the site bar without a rebuild.
        if (not parts or parts == ["index.html"] or parts[0] == "u"
                or (len(parts) == 1 and (build_site.PAGES_DIR / f"{parts[0]}.html").is_file())):
            self._send_body(build_site.build_index_html().encode("utf-8"), _CONTENT_TYPES[".html"])
            return

        # Hand-written page bodies, read from site/ rather than dist/.
        if url_path == "/home-intro.html":
            self._serve_file(build_site.HOME_INTRO)
            return
        if len(parts) == 1 and parts[0].startswith("page-") and parts[0].endswith(".html"):
            self._serve_file(_safe_join(build_site.PAGES_DIR, [parts[0][len("page-"):]]))
            return

        # /users/<name> -> a gzip'd per-user data blob; 403 if it's not there,
        # same as S3-via-OAC would answer for a missing key.
        if parts and parts[0] == "users":
            if len(parts) not in (2, 3) or not parts[-1].endswith(".json.gz"):
                self.send_error(403)
                return
            user_path = _safe_join(_USERS_DIR, parts[1:])
            if user_path is None or not user_path.is_file():
                self.send_error(403)
                return
            self._serve_file(user_path, content_type="application/json", content_encoding="gzip")
            return

        # Committed game-art folders, served from the repo root (not dist/ —
        # build_site.py never copies these in).
        if parts and parts[0] in _ART_DIRS:
            self._serve_file(_safe_join(_REPO_ROOT, parts))
            return

        # Everything else comes from dist/.
        self._serve_file(_safe_join(_DIST, parts))

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/ingest":
            self._authorize()
        elif path == "/api/ingest/mod":
            self._authorize_mod()
        elif path == "/api/raw-upload":
            self._raw_upload()
        else:
            self.send_error(404)

    def _authorize(self):
        # The real ingest Lambda's authorize(), writing into local_data/
        # instead of S3. Steam verification is still real: sign in through
        # Steam with a return_to on this server's origin.
        params = dict(parse_qsl(urlsplit(self.path).query, keep_blank_values=True))
        port = self.server.server_address[1]
        allowed = [f"http://127.0.0.1:{port}/", f"http://localhost:{port}/"]

        try:
            result = ingest_handler.authorize(params, self.client_address[0], ingest_handler.DirStore(_DATA_DIR),
                                              allowed, _presign)
        except ingest_handler.IngestError as e:
            self._send_json(e.status, {"error": e.code, "message": e.message})
            return
        self._send_json(200, result)

    def _authorize_mod(self):
        # The same for the mod's door: the real authorize_mod(), with the
        # allowlist from $MOD_ALLOWLIST (comma-separated SteamID64s; nobody
        # if unset). The Steam ticket check is real too, so it needs
        # $STEAM_API_KEY and a ticket from a running Steam client.
        length = int(self.headers.get("Content-Length") or 0)
        body = ingest_handler._mod_body({"body": self.rfile.read(length).decode("utf-8", "replace")})
        try:
            result = ingest_handler.authorize_mod(body, ingest_handler.DirStore(_DATA_DIR),
                                                  ingest_handler.mod_allowlist(), _presign)
        except ingest_handler.IngestError as e:
            self._send_json(e.status, {"error": e.code, "message": e.message})
            return
        self._send_json(200, result)

    def _raw_upload(self):
        # Stands in for S3: a multipart form POST whose "key" field must be
        # one /api/ingest handed out, and whose "file" is capped at the same
        # size. Then the S3 event's processing, run right here.
        length = int(self.headers.get("Content-Length") or 0)
        if length > ingest_handler.UPLOAD_MAX_BYTES + 64 * 1024:
            self.send_error(400, "EntityTooLarge")
            return
        head = f"Content-Type: {self.headers.get('Content-Type', '')}\r\n\r\n".encode()
        form = email.parser.BytesParser().parsebytes(head + self.rfile.read(length))
        fields = {part.get_param("name", header="content-disposition"): part.get_payload(decode=True)
                  for part in form.get_payload()} if form.is_multipart() else {}
        key = (fields.get("key") or b"").decode()
        data = fields.get("file")
        with _issued_lock:
            max_bytes = _issued_keys.pop(key, None)
        if max_bytes is None or data is None:
            self.send_error(403, "AccessDenied")
            return
        if len(data) > max_bytes:
            self.send_error(400, "EntityTooLarge")
            return
        store = ingest_handler.DirStore(_DATA_DIR)
        store.put(key, data, {}, None)
        self.send_response(204)
        self.end_headers()
        try:
            ingest_handler.process_upload(key, store)
        except ingest_handler.IngestError as e:
            # The Lambda would retry; here it just stays in raw/ for a rebuild.
            print(f"processing {key} failed: {e.code}", file=sys.stderr)

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, file_path: Path | None, content_type: str | None = None,
                     content_encoding: str | None = None):
        if file_path is None or not file_path.is_file():
            self.send_error(404)
            return
        self._send_body(file_path.read_bytes(), content_type or _content_type(file_path), content_encoding)

    def _send_body(self, body: bytes, content_type: str, content_encoding: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        # Text assets are the ones edited and reloaded while working on the site.
        # With no Cache-Control and no validator a browser falls back to
        # heuristic caching, so an ordinary refresh can keep serving the
        # previous dashboard.css or app.js however many times you rebuild --
        # which reads as "my change didn't take".
        #
        # Images deliberately keep the default: there are hundreds of them, they
        # change only when the art is re-baked, and re-fetching 200 thumbnails on
        # every navigation is the one thing that would make this server
        # noticeably slow to use.
        if content_type.startswith("text/") or "json" in content_type:
            self.send_header("Cache-Control", "no-store")
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


# ---------------------------------------------------------------------------
# One dev server per port
# ---------------------------------------------------------------------------
#
# http.server sets allow_reuse_address, and on Windows SO_REUSEADDR lets a
# second process bind an already-bound port instead of failing. So starting the
# server again while an older one is still up can leave BOTH listening, with
# requests going to whichever the OS happens to pick -- a "restart" that
# silently changed nothing, which is how a stale process ends up serving
# days-old responses (and a days-old build of /thumbs/).
#
# So a startup takes the port over. The target is whoever is LISTENING on the
# port, never "whoever mentions this script on their command line": the shell
# that ran the command and the venv's python.exe launcher both carry that same
# text, so matching on it kills the terminal or this very process with it.


class LocalHTTPServer(ThreadingHTTPServer):
    # On Windows this is what stops two servers sharing the port. Elsewhere the
    # flag is what lets a restart skip waiting out TIME_WAIT, and the silent
    # sharing problem doesn't exist, so leave the default alone.
    allow_reuse_address = sys.platform != "win32"


def _listening_pids(port: int) -> list[int]:
    """PIDs holding a listening socket on this port."""
    if sys.platform == "win32":
        cmd = ["netstat", "-ano", "-p", "TCP"]
    else:
        cmd = ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for line in out.splitlines():
        if sys.platform == "win32":
            parts = line.split()
            if (len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING"
                    and parts[1].endswith(f":{port}")):
                pids.append(int(parts[4]))
        elif line.strip().isdigit():
            pids.append(int(line.strip()))
    return pids


def _command_lines(pids: list[int]) -> dict[int, str]:
    """pid -> command line, to check a port holder really is our server."""
    if sys.platform != "win32":
        lines = {}
        for pid in pids:
            try:
                raw = Path(f"/proc/{pid}/cmdline").read_bytes()
            except OSError:
                continue
            lines[pid] = raw.decode(errors="replace").replace("\x00", " ").strip()
        return lines
    query = 'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId)|$($_.CommandLine)" }'
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", query],
                             capture_output=True, text=True, timeout=25).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    lines = {}
    for line in out.splitlines():
        pid, sep, cmdline = line.partition("|")
        if sep and pid.strip().isdigit():
            lines[int(pid.strip())] = cmdline
    return lines


def _take_port_over(port: int) -> bool:
    """Kill an earlier dev server listening on this port. True if one was."""
    holders = [p for p in _listening_pids(port) if p != os.getpid()]
    if not holders:
        return False
    command_lines = _command_lines(holders)
    ours = [p for p in holders if "serve_site.py" in command_lines.get(p, "")]
    if not ours:
        # Someone else's server on this port: leave it alone and let the bind
        # fail loudly rather than kill a process that isn't ours.
        return False
    shown = ", ".join(str(p) for p in ours)
    print(f"Taking port {port} over from {len(ours)} earlier dev server(s): {shown}")
    for pid in ours:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    return True


def _bind(port: int, retry_seconds: float):
    """Bind the port, giving a just-killed server a moment to let go of it."""
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            return LocalHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.15)


def main():
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8000

    killed = _take_port_over(port)
    try:
        server = _bind(port, 3.0 if killed else 0.0)
    except OSError as exc:
        print(f"Could not bind port {port}: {exc}\n"
              f"Something else is holding it. Check with:\n"
              f"  netstat -ano | findstr :{port}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Serving dist/ at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
