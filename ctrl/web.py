"""Airlock web UI and API on ctrl (standard library only). Service on :8080 behind the Sprite URL.

Every route except /login needs the password cookie. POSTs also need the X-Airlock header (CSRF), and the
cookie is SameSite=Strict. One background thread processes queued documents, one at a time.
"""
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db, pipeline
from .chamber import Chamber

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_SECRET = hashlib.sha256(("airlock-session|" + config.UI_PASSWORD).encode()).digest()
SESSION_HOURS = 12
WAKE = threading.Event()
STARTED = time.time()


def sign(expiry):
    mac = hmac.new(SESSION_SECRET, str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{mac}"


def valid(token):
    try:
        expiry, mac = token.split(".", 1)
        return int(expiry) > time.time() and hmac.compare_digest(sign(int(expiry)), token)
    except (ValueError, AttributeError):
        return False


def worker_loop():
    while True:
        if pipeline.HALT["halted"]:          # fail closed: wait, then let process() re-check the chamber
            time.sleep(20)
        doc_id = db.next_queued()
        if doc_id is None:
            WAKE.wait(timeout=30)
            WAKE.clear()
            continue
        try:
            pipeline.process(doc_id)
        except Exception as e:  # noqa: BLE001 — never kill the loop
            db.event(doc_id, "error", error=f"{type(e).__name__}: {e}"[:300])
            db.update(doc_id, status="quarantined")


def summary(d):
    return {k: d[k] for k in ("id", "name", "status", "source", "created", "updated")} | {
        "action": (d["decision"] or {}).get("action"),
        "doc_type": (d["proposal"] or {}).get("doc_type") if isinstance(d["proposal"], dict) else None,
        "red": any(r.startswith("RED") for r in (d["decision"] or {}).get("reasons", [])),
    }


def state():
    return {
        "docs": [summary(d) for d in db.documents(60)],
        "phase": pipeline.PHASE,
        "chamber": {"name": urllib.parse.urlparse(config.CHAMBER_URL).hostname.rsplit("-", 1)[0] if config.CHAMBER_URL else "",
                    "baseline": config.CHAMBER_BASELINE, "egress": "deny all", "connectors": 0},
        "ctrl": {"connectors": ["Ollama", "Box", "Pinecone"], "model": config.MODEL},
        "budget": {"llm_calls": db.today_llm_calls(), "cap": config.DAILY_LLM_CALLS},
        "halt": pipeline.HALT,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "airlock"

    # --- helpers ---
    def _send(self, code, body, ctype="application/json", extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                         "font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
        return valid(cookies.get("airlock", ""))

    def _body(self, limit=9 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("request too large")
        return self.rfile.read(n)

    def _page(self, name):
        with open(os.path.join(HERE, "static", name), "rb") as f:
            return f.read()

    # --- routes ---
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            return self._send(200, self._page("login.html"), "text/html; charset=utf-8")
        authed = self._authed()
        if not (authed or config.PUBLIC_READONLY):
            if path.startswith("/api/"):
                return self._send(401, {"error": "login required"})
            return self._send(302, b"", extra={"Location": "/login"})
        if path == "/":
            return self._send(200, self._page("index.html"), "text/html; charset=utf-8")
        if path == "/api/state":
            return self._send(200, {**state(), "viewer": {"signed_in": authed, "public": config.PUBLIC_READONLY}})
        if path.startswith("/api/doc/"):
            tail = path.rsplit("/", 1)[1]
            d = db.get(int(tail)) if tail.isdigit() else None
            if not d:
                return self._send(404, {"error": "not found"})
            return self._send(200, {**d, "events": db.events(d["id"])})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            form = urllib.parse.parse_qs(self._body(4096).decode())
            if config.UI_PASSWORD and hmac.compare_digest(form.get("password", [""])[0], config.UI_PASSWORD):
                cookie = f"airlock={sign(int(time.time()) + SESSION_HOURS * 3600)}; HttpOnly; Secure; SameSite=Strict; Path=/"
                return self._send(303, b"", extra={"Location": "/", "Set-Cookie": cookie})
            time.sleep(1.5)
            return self._send(303, b"", extra={"Location": "/login?bad=1"})
        if not self._authed() or self.headers.get("X-Airlock") != "1":
            return self._send(401, {"error": "login required"})
        try:
            if path == "/api/upload":
                name = urllib.parse.unquote(self.headers.get("X-Filename") or "upload")
                doc_id = pipeline.intake(os.path.basename(name), self._body())
                WAKE.set()
                return self._send(200, {"id": doc_id})
            if path == "/api/sync":
                ids = pipeline.sync_box()
                WAKE.set()
                return self._send(200, {"queued": ids})
            if path == "/api/redteam":
                with open(os.path.join(HERE, "..", "samples", "electric-bill-oct.pdf"), "rb") as f:
                    doc_id = pipeline.intake("red-team-drill.pdf", f.read(), source="redteam")
                WAKE.set()
                return self._send(200, {"id": doc_id})
            if path.startswith("/api/doc/") and path.endswith(("/approve", "/reject")):
                part = path.split("/")[3]
                if not part.isdigit():
                    return self._send(404, {"error": "not found"})
                doc_id = int(part)
                req = json.loads(self._body(64 * 1024) or b"{}")
                action = "approve" if path.endswith("/approve") else "reject"
                # an emptied field is a real edit (e.g. remove a date the model made up)
                edits = {k: ("" if v is None else v) for k, v in (req.get("edits") or {}).items()}
                if "total" in edits:
                    raw = str(edits["total"]).replace(",", "").replace("$", "").strip()
                    edits["total"] = float(raw) if raw else None
                d = pipeline.review(doc_id, action, edits, str(req.get("note", ""))[:1000], background=True)
                return self._send(200, {"status": d["status"]})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001 — Box/Pinecone errors: report, don't drop the connection
            return self._send(502, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass


def main():
    if not config.UI_PASSWORD:
        raise SystemExit("AIRLOCK_PASSWORD is not set")
    Chamber()  # fail fast if the chamber is not configured
    for d in db.documents(500):  # documents interrupted by a restart go back to the queue
        if d["status"] == "processing":
            db.update(d["id"], status="queued")
        elif d["status"] == "filing":  # a review interrupted mid-upload: let the person review it again
            db.event(d["id"], "error", error="filing was interrupted by a restart; please review again")
            db.update(d["id"], status="awaiting_approval")
    threading.Thread(target=worker_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
