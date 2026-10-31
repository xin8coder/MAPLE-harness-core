#!/usr/bin/env python3
"""Login page and session check for the public lanchou.

Caddy calls GET /verify (forward_auth) on every request; a valid signed
session cookie answers 200, anything else redirects to the login page.
Runs on the host, outside the sandbox. Standard library only.
"""
import hashlib
import hmac
import html
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

USER = os.environ["MAPLE_FRONT_USER"]
SALT = bytes.fromhex(os.environ["MAPLE_FRONT_SALT"])
PW_HASH = bytes.fromhex(os.environ["MAPLE_FRONT_PBKDF2"])
SECRET = bytes.fromhex(os.environ["MAPLE_SESSION_SECRET"])
COOKIE = "maple_session"
TTL = 7 * 24 * 3600
ITERATIONS = 200_000

_failures = {}
_lock = threading.Lock()

PUBLIC = Path(__file__).resolve().with_name("public")
SOURCE_ASSETS = Path(__file__).resolve().parents[2] / "src/liveopt_dsh/assets"
PUBLIC_TYPES = {
    "login.css": "text/css; charset=utf-8",
    "login.js": "text/javascript; charset=utf-8",
    "case-demo.json": "application/json; charset=utf-8",
    "lanchou-logo.png": "image/png",
    "echarts.min.js": "text/javascript; charset=utf-8",
    "lucide.min.js": "text/javascript; charset=utf-8",
}


def public_asset(name):
    if name not in PUBLIC_TYPES:
        return None
    path = PUBLIC / name
    if not path.is_file() and name == "lanchou-logo.png":
        path = SOURCE_ASSETS / name
    elif not path.is_file() and name in {"echarts.min.js", "lucide.min.js"}:
        path = SOURCE_ASSETS / "explorer" / name
    return path if path.is_file() else None


def sign(expires):
    msg = str(expires).encode()
    return f"{expires}.{hmac.new(SECRET, msg, hashlib.sha256).hexdigest()}"


def valid(token):
    try:
        expires, mac = token.split(".", 1)
        good = hmac.new(SECRET, expires.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(mac, good) and int(expires) > time.time()
    except ValueError:
        return False


def check_password(user, password):
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), SALT, ITERATIONS)
    return hmac.compare_digest(user.encode(), USER.encode()) & hmac.compare_digest(candidate, PW_HASH)


def safe_next(value):
    # Only same-site relative paths, never another host.
    if (not value.startswith("/") or value.startswith("//") or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        return "/"
    if urlsplit(value).path in {"/maple-login", "/maple-logout", "/verify"}:
        return "/"
    return value


class Handler(BaseHTTPRequestHandler):
    server_version = "maple-auth"

    def log_message(self, fmt, *args):
        pass

    def cookie(self):
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return value
        return ""

    def send(self, status, body=b"", headers=(), *, cache="no-store"):
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def page(self, next_path="/", error="", username=""):
        body = (PUBLIC / "index.html").read_text(encoding="utf-8")
        for name, value in {"NEXT": safe_next(next_path), "ERROR": error, "USERNAME": username}.items():
            body = body.replace(f"__LOGIN_{name}__", html.escape(value, quote=True))
        policy = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                  "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
                  "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")
        self.send(200, body.encode(), [("Content-Type", "text/html; charset=utf-8"),
                                       ("Content-Security-Policy", policy)])

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == "/verify":
            if valid(self.cookie()):
                return self.send(204)
            original = self.headers.get("X-Forwarded-Uri", "/")
            return self.send(302, headers=[("Location", "/maple-login?next=" + quote(safe_next(original), safe=""))])
        if path.path == "/maple-logout":
            return self.send(302, headers=[("Location", "/maple-login"),
                                           ("Set-Cookie", f"{COOKIE}=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Lax")])
        prefix = "/maple-login/assets/"
        if path.path.startswith(prefix):
            name = path.path[len(prefix):]
            asset = public_asset(name)
            if asset is None:
                return self.send(404)
            return self.send(200, asset.read_bytes(), [("Content-Type", PUBLIC_TYPES[name])],
                             cache="public, max-age=3600")
        if path.path not in {"/", "/maple-login"}:
            return self.send(404)
        next_path = safe_next(parse_qs(path.query).get("next", ["/"])[0])
        if valid(self.cookie()):
            return self.send(303, headers=[("Location", next_path)])
        return self.page(next_path)

    do_HEAD = do_GET

    def do_POST(self):
        if urlsplit(self.path).path != "/maple-login":
            return self.send(404)
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return self.send(400)
        if not 0 <= length <= 4096:
            return self.send(413)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        user = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        next_path = safe_next(form.get("next", ["/"])[0])
        client = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        with _lock:
            fails = _failures.get(client, 0)
        if fails:
            time.sleep(min(fails, 10))  # slow down repeated guessing
        if check_password(user, password):
            with _lock:
                _failures.pop(client, None)
            cookie = f"{COOKIE}={sign(int(time.time()) + TTL)}; Max-Age={TTL}; Path=/; Secure; HttpOnly; SameSite=Lax"
            return self.send(303, headers=[("Location", next_path), ("Set-Cookie", cookie)])
        with _lock:
            _failures[client] = fails + 1
        return self.page(next_path, "账号或密码错误", user)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("MAPLE_AUTH_PORT", "18991"))), Handler).serve_forever()
