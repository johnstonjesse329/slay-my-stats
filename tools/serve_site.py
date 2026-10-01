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
    POST /api/raw-upload -> stands in for the presigned S3 POST: stores the
                            file under local_data/raw/ and processes it on
                            the spot (stands in for the S3 event)

A missing /users/<name> answers 403, not 404 — that's what S3 (behind
CloudFront with Origin Access Control) returns for a key that doesn't exist,
and boot.js needs to tell "no data yet" apart from a real network failure.

Usage:
    python tools/serve_site.py
    python tools/serve_site.py --port 8080
"""

import email.parser
import json
import sys
import threading
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

# Raw keys handed out by /api/ingest and not yet used: what the presigned
# POST's signature pins down on real S3.
_issued_keys: set[str] = set()
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

        def presign(key, max_bytes, expires):
            with _issued_lock:
                _issued_keys.add(key)
            return {"url": "/api/raw-upload", "fields": {"key": key, "Content-Type": "application/gzip"}}
        try:
            result = ingest_handler.authorize(params, self.client_address[0], ingest_handler.DirStore(_DATA_DIR),
                                              allowed, presign)
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
            issued = key in _issued_keys
            _issued_keys.discard(key)
        if not issued or data is None:
            self.send_error(403, "AccessDenied")
            return
        if len(data) > ingest_handler.UPLOAD_MAX_BYTES:
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
