#!/usr/bin/env python3
"""Login page and session check for the public MAPLE Harness.

Caddy calls GET /verify (forward_auth) on every request; a valid signed
session cookie answers 200, anything else redirects to the login page.
Runs on the host, outside the sandbox. Standard library only.
"""
import hashlib
import hmac
import html
import os
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

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MAPLE Harness · 登录</title>
<style>
:root{{--bg:#f4f7f6;--card:#fff;--ink:#1f2d33;--muted:#5d6b70;--accent:#2e8b7a;--err:#b3412e;--line:#d8e1df}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;padding:16px}}
.card{{width:100%;max-width:360px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:32px 28px}}
h1{{font-size:22px;margin:0 0 4px}}p{{margin:0 0 24px;color:var(--muted)}}
label{{display:block;font-size:13px;color:var(--muted);margin:14px 0 6px}}
input{{width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:8px;font-size:15px;background:transparent;color:var(--ink)}}
input:focus{{outline:2px solid var(--accent);border-color:transparent}}
button{{margin-top:22px;width:100%;padding:11px;border:0;border-radius:8px;background:var(--accent);color:#fff;font-size:15px;cursor:pointer}}
.err{{color:var(--err);font-size:13px;margin-top:12px;min-height:1em}}
</style></head><body>
<form class="card" method="post" action="/maple-login">
<h1>MAPLE Harness</h1><p>自然语言驱动的运筹优化智能体</p>
<input type="hidden" name="next" value="{next}">
<label for="u">账号</label><input id="u" name="username" autocomplete="username" required autofocus>
<label for="p">密码</label><input id="p" name="password" type="password" autocomplete="current-password" required>
<button type="submit">登录</button>
<div class="err">{error}</div>
</form></body></html>"""


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

    def send(self, status, body=b"", headers=()):
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def page(self, next_path="/", error=""):
        body = PAGE.format(next=html.escape(next_path, quote=True), error=html.escape(error)).encode()
        self.send(200, body, [("Content-Type", "text/html; charset=utf-8")])

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
        next_path = safe_next(parse_qs(path.query).get("next", ["/"])[0])
        return self.page(next_path)

    def do_POST(self):
        if urlsplit(self.path).path != "/maple-login":
            return self.send(404)
        length = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
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
        return self.page(next_path, "账号或密码错误")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("MAPLE_AUTH_PORT", "18991"))), Handler).serve_forever()
