#!/usr/bin/env python3
"""
Tiny webhook listener that triggers the daily Tour de France publish on demand.

Designed to be driven by an n8n cron (fire once a day at 10:00 NZ) so the schedule
lives somewhere visible, instead of an opaque local launchd timer. n8n POSTs a small
JSON body carrying a `type`; on a matching type we run publish.sh (which regenerates
stage-today.js and pushes so Vercel redeploys) and return immediately.

  POST /  {"type": "tdf_daily"}          -> 202, kicks off publish.sh in the background
  GET  /health                            -> 200 "ok"   (for uptime checks)

Security: binds to 127.0.0.1 by default (expose it through whatever tunnel you already
use to reach the Mac). If TDF_WEBHOOK_SECRET is set, the request must present it either
as the `X-TDF-Secret` header or a `"secret"` field in the JSON body, or it's rejected.

Config via env:
  TDF_WEBHOOK_HOST    bind host   (default 127.0.0.1)
  TDF_WEBHOOK_PORT    bind port   (default 8787)
  TDF_WEBHOOK_SECRET  shared token (strongly recommended; if unset, no auth is enforced)
  TDF_WEBHOOK_TYPES   comma-separated accepted types (default "tdf_daily")

Python 3.9 compatible. No third-party dependencies.
"""
import hmac
import json
import os
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PUBLISH = os.path.join(HERE, "publish.sh")
LOG = os.path.join(ROOT, "logs", "webhook.log")

HOST = os.environ.get("TDF_WEBHOOK_HOST", "127.0.0.1")
PORT = int(os.environ.get("TDF_WEBHOOK_PORT", "8787"))
SECRET = os.environ.get("TDF_WEBHOOK_SECRET", "")
ACCEPTED = {t.strip() for t in os.environ.get("TDF_WEBHOOK_TYPES", "tdf_daily").split(",") if t.strip()}


def log(msg):
    line = "[%s] %s" % (datetime.now().astimezone().isoformat(timespec="seconds"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def secret_ok(headers, body):
    if not SECRET:
        return True  # no secret configured -> auth disabled (dev only)
    presented = headers.get("X-TDF-Secret") or (body.get("secret") if isinstance(body, dict) else None) or ""
    # constant-time compare to avoid timing leaks
    return hmac.compare_digest(str(presented), SECRET)


def run_publish():
    """Kick off publish.sh detached so the HTTP response returns fast (claude -p is slow)."""
    out = open(os.path.join(ROOT, "logs", "tdf-daily.log"), "a", encoding="utf-8")
    err = open(os.path.join(ROOT, "logs", "tdf-daily.err"), "a", encoding="utf-8")
    subprocess.Popen(["/bin/bash", PUBLISH], cwd=ROOT, stdout=out, stderr=err,
                     start_new_session=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, msg):
        payload = json.dumps({"ok": 200 <= code < 300, "message": msg}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):  # silence default stderr access logging
        pass

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send(200, "ok")
        else:
            self._send(404, "not found")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, "invalid JSON body")
            return

        if not secret_ok(self.headers, body):
            log("rejected: bad/missing secret from %s" % self.client_address[0])
            self._send(401, "unauthorized")
            return

        wtype = (body or {}).get("type")
        if wtype not in ACCEPTED:
            log("ignored: type=%r (accepted: %s)" % (wtype, sorted(ACCEPTED)))
            self._send(400, "unknown or missing type")
            return

        log("trigger: type=%s -> publish.sh" % wtype)
        try:
            run_publish()
        except Exception as e:  # noqa
            log("publish failed to start: %s" % e)
            self._send(500, "failed to start publish")
            return
        self._send(202, "publish started")


def main():
    if not SECRET:
        log("WARNING: TDF_WEBHOOK_SECRET is not set — auth is DISABLED. Set it before exposing this port.")
    log("listening on %s:%d (accepted types: %s)" % (HOST, PORT, sorted(ACCEPTED)))
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
