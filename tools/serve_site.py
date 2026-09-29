"""
tools/serve_site.py — Local dev server emulating the S3 + CloudFront setup.

stdlib-only (http.server), so no extra install is needed to preview the
built site. Routing mirrors what CloudFront will be configured to do against
the site bucket:

    /u/<anything>        -> dist/index.html            (client-side router)
    /users/<name>        -> local_data/users/<name>     (gzip'd user blobs)
    /card_final/...      -> card_final/...              (game art, repo root)
    /card_portraits/...  -> card_portraits/...
    /node_icons/...      -> node_icons/...
    /relic_images/...    -> relic_images/...
    /potion_images/...   -> potion_images/...
    /ui_icons/...        -> ui_icons/...
    everything else      -> dist/...   (/ -> dist/index.html)

    POST /api/ingest     -> the ingest Lambda's handler, storing into
                            local_data/users/ (stands in for the Function URL)

A missing /users/<name> answers 403, not 404 — that's what S3 (behind
CloudFront with Origin Access Control) returns for a key that doesn't exist,
and boot.js needs to tell "no data yet" apart from a real network failure.

Usage:
    python tools/serve_site.py
    python tools/serve_site.py --port 8080
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

_REPO_ROOT = Path(__file__).resolve().parent.parent
# The ingest Lambda's handler (and the run.py it imports), so /api/ingest
# runs exactly the code that's deployed.
sys.path[:0] = [str(_REPO_ROOT), str(_REPO_ROOT / "infra" / "lambda" / "ingest")]
import handler as ingest_handler  # noqa: E402
_DIST = _REPO_ROOT / "dist"
_USERS_DIR = _REPO_ROOT / "local_data" / "users"

# Committed game-art folders, served straight from the repo root — these
# mirror the root-absolute paths the real site bucket serves them at.
_ART_DIRS = {"card_final", "card_portraits", "node_icons", "relic_images", "potion_images", "ui_icons"}

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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url_path = unquote(urlsplit(self.path).path)
        parts = [p for p in url_path.split("/") if p]

        # /u/<anything> -> the SPA shell
        if parts and parts[0] == "u":
            self._serve_file(_DIST / "index.html")
            return

        # /users/<name> -> a gzip'd per-user data blob; 403 if it's not there,
        # same as S3-via-OAC would answer for a missing key.
        if parts and parts[0] == "users":
            if len(parts) != 2:
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

        # Everything else comes from dist/, with / -> index.html.
        if not parts:
            self._serve_file(_DIST / "index.html")
            return
        self._serve_file(_safe_join(_DIST, parts))

    def do_POST(self):
        # /api/ingest -> the real ingest Lambda's code, writing into
        # local_data/users/ instead of S3. Steam verification is still real:
        # sign in through Steam with a return_to on this server's origin.
        if urlsplit(self.path).path != "/api/ingest":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 6 * 1024 * 1024:  # the Function URL's own request limit
            self._send_json(413, {"error": "too_large", "message": "Upload is over 6 MB."})
            return
        body = self.rfile.read(length)
        params = dict(parse_qsl(urlsplit(self.path).query, keep_blank_values=True))
        port = self.server.server_address[1]
        allowed = [f"http://127.0.0.1:{port}/", f"http://localhost:{port}/"]
        try:
            result = ingest_handler.ingest(params, body, ingest_handler.DirStore(_USERS_DIR), allowed)
        except ingest_handler.IngestError as e:
            self._send_json(e.status, {"error": e.code, "message": e.message})
            return
        self._send_json(200, result)

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
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or _content_type(file_path))
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def main():
    args = sys.argv[1:]
    port = int(args[args.index("--port") + 1]) if "--port" in args else 8000

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving dist/ at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
