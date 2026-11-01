from __future__ import annotations

import base64
import gzip
import hashlib
from http.client import HTTPConnection
import importlib.util
import json
import re
from pathlib import Path
import threading
import time
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def gateway(monkeypatch):
    salt = bytes(range(24))
    monkeypatch.setenv("MAPLE_FRONT_USER", "demo-user")
    monkeypatch.setenv("MAPLE_FRONT_SALT", salt.hex())
    monkeypatch.setenv("MAPLE_FRONT_PBKDF2", hashlib.pbkdf2_hmac("sha256", b"local-only-test", salt, 200_000).hex())
    monkeypatch.setenv("MAPLE_SESSION_SECRET", bytes(range(32)).hex())
    spec = importlib.util.spec_from_file_location("login_gateway", ROOT / "deploy/sandbox/auth.py")
    auth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth)
    server = auth.ThreadingHTTPServer(("127.0.0.1", 0), auth.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, method="GET", form=None, cookie=None, extra_headers=None):
        connection = HTTPConnection(*server.server_address, timeout=5)
        headers = dict(extra_headers or {})
        if cookie:
            headers["Cookie"] = cookie
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request(method, path, urlencode(form) if form is not None else None, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    yield auth, request
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_public_root_is_a_complete_login_page_without_account_data(gateway):
    _, request = gateway
    status, headers, body = request("/")
    assert status == 200
    page = body.decode()
    assert "澜筹·通用运筹智能体 · 登录" in page
    assert 'action="/maple-login"' in page
    assert 'name="next" value="/"' in page
    assert "__LOGIN_" not in page
    assert "demo-user" not in page and "local-only-test" not in page
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "script-src 'self' 'sha256-" in headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in headers["Content-Security-Policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert headers["Cache-Control"] == "no-store"


def test_valid_login_issues_a_protected_cookie_and_returns_to_the_workspace(gateway):
    auth, request = gateway
    status, headers, body = request("/maple-login", "POST", {
        "username": "demo-user", "password": "local-only-test", "next": "/?view=solutions",
    })
    assert status == 303 and headers["Location"] == "/?view=solutions"
    cookie = headers["Set-Cookie"]
    assert all(flag in cookie for flag in ("Secure", "HttpOnly", "SameSite=Lax"))
    token = cookie.split(";", 1)[0].split("=", 1)[1]
    assert auth.valid(token)
    assert not body
    assert request("/verify", cookie=cookie.split(";", 1)[0])[0] == 204
    status, headers, _ = request("/maple-login", cookie=cookie.split(";", 1)[0])
    assert status == 303 and headers["Location"] == "/"


def test_invalid_login_preserves_only_the_escaped_username(gateway):
    _, request = gateway
    status, _, body = request("/maple-login", "POST", {
        "username": '<img src=x onerror="alert(1)">', "password": "wrong-secret", "next": "/",
    })
    assert status == 200
    page = body.decode()
    assert "账号或密码错误" in page
    assert "&lt;img" in page and '<img src=x' not in page
    assert "wrong-secret" not in page


@pytest.mark.parametrize("name", ["login.css", "login.js", "case-demo.json", "lanchou-logo.png", "echarts.min.js", "lucide.min.js", "login-logo.png", "login-icons.min.js", "login-charts.min.js", "login.min.js", "login.min.css", "case-demo.min.json"])
def test_only_allowlisted_public_assets_are_served(gateway, name):
    _, request = gateway
    status, headers, body = request("/maple-login/assets/" + name)
    assert status == 200 and body
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Cache-Control"].startswith("public,")
    assert headers["ETag"].startswith('"')
    if name == "case-demo.json":
        data = json.loads(body)
        assert [turn["id"] for turn in data["turns"]] == ["t000", "t001"]
        assert data["turns"][1]["restart"]["reused"] == 50
        assert all(len(turn["history"]) == 11 for turn in data["turns"])


@pytest.mark.parametrize("path", ["/maple-login/assets/../auth.py", "/maple-login/assets/front.env", "/maple-login/assets/%2e%2e/auth.py", "/unknown"])
def test_static_routes_cannot_escape_public_assets(gateway, path):
    _, request = gateway
    assert request(path)[0] == 404


def test_expired_or_invalid_sessions_do_not_authorize_private_routes(gateway):
    auth, request = gateway
    for token in (auth.sign(int(time.time()) - 10), "123.invalid"):
        status, headers, _ = request("/verify", cookie="maple_session=" + token)
        assert status == 302 and headers["Location"].startswith("/maple-login?")


def test_login_redirects_and_template_values_cannot_inject_another_origin(gateway):
    _, request = gateway
    _, _, body = request("/maple-login?" + urlencode({"next": '"><script>alert(1)</script>'}))
    assert b'<script>alert(1)</script>' not in body
    assert b'name="next" value="/"' in body
    for destination in ("//outside.invalid", "/maple-login", "/maple-logout", "/verify"):
        status, headers, _ = request("/maple-login", "POST", {
            "username": "demo-user", "password": "local-only-test", "next": destination,
        })
        assert status == 303 and headers["Location"] == "/"


def test_root_landing_does_not_make_application_or_download_routes_public():
    gateway = (ROOT / "deploy/sandbox/Caddyfile.front").read_text()
    landing = gateway.split("@landing {", 1)[1].split("}", 1)[0]
    assert "path /\n" in landing
    assert "maple_session=" in landing
    assert "path /*" not in landing
    assert gateway.index("reverse_proxy @landing") < gateway.index("forward_auth")
    assert gateway.index("forward_auth") < gateway.index("reverse_proxy @entry")


def test_assets_revalidate_without_retransmission_but_login_is_not_cached(gateway):
    _, request = gateway
    path = "/maple-login/assets/login.js?v=0.2.4-p1"
    _, headers, _ = request(path)
    for value in (headers["ETag"], "W/" + headers["ETag"], '"old", ' + headers["ETag"], "*"):
        status, cached_headers, body = request(path, extra_headers={"If-None-Match": value})
        assert status == 304 and not body
        assert cached_headers["ETag"] == headers["ETag"]
        assert "Content-Length" not in cached_headers
    assert request(path, extra_headers={"If-None-Match": '"different"'})[0] == 200
    status, headers, body = request(path, method="HEAD")
    assert status == 200 and not body and int(headers["Content-Length"]) > 0
    status, headers, _ = request("/", extra_headers={"If-None-Match": "*"})
    assert status == 200 and headers["Cache-Control"] == "no-store"


def test_login_form_does_not_depend_on_chart_download():
    page = (ROOT / "deploy/sandbox/public/index.html").read_text()
    script = (ROOT / "deploy/sandbox/public/login.js").read_text()
    assert '<script>__LOGIN_SCRIPT__</script>' in page
    assert '<style>__LOGIN_STYLE__</style>' in page
    assert '<script defer src=' not in page
    assert '<link rel="stylesheet"' not in page
    assert '<script defer src="/maple-login/assets/echarts.min.js?' not in page
    assert '<script defer src="/maple-login/assets/login-charts.min.js?' not in page
    assert script.index('$("toggle-password").addEventListener') < script.index("function loadCharts()")
    assert 'IntersectionObserver' in script and 'Promise.all' in script
    assert (ROOT / "deploy/sandbox/public/login-logo.png").stat().st_size < 15000
    assert (ROOT / "deploy/sandbox/public/login-icons.min.js").stat().st_size < 20000


def test_first_paint_is_self_contained_and_uses_a_hash_authorized_script(gateway):
    _, request = gateway
    _, headers, body = request("/")
    page = body.decode()
    scripts = re.findall(r"<script>(.*?)</script>", page, flags=re.S)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    assert "'sha256-" + digest + "'" in headers["Content-Security-Policy"]
    assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)="/maple-login/assets/', page)
    assert 'data:image/png;base64,' in page
    _, _, body = request("/maple-login", "POST", {
        "username": '__LOGIN_SCRIPT__"<script>bad()</script>', "password": "wrong", "next": "/",
    })
    page = body.decode()
    assert '__LOGIN_SCRIPT__&quot;&lt;script&gt;bad()&lt;/script&gt;' in page
    assert page.count('<script>') == 1


@pytest.mark.parametrize("accept,expected", [
    ("br, gzip", "br"), ("gzip", "gzip"), ("identity", None),
    ("br;q=0, gzip", "gzip"), ("br;q=0, gzip;q=0", None),
    ("br;q=0.2, gzip;q=1", "gzip"), ("gzip;q=0.5, identity;q=0", "gzip"),
    ("*", "br"), ("br;q=nan, gzip", "gzip"),
])
def test_precompressed_assets_negotiate_without_losing_data(gateway, accept, expected):
    _, request = gateway
    path = "/maple-login/assets/case-demo.min.json?v=0.2.4-p2"
    status, headers, body = request(path, extra_headers={"Accept-Encoding": accept})
    assert status == 200 and headers.get("Content-Encoding") == expected
    assert headers["Vary"] == "Accept-Encoding"
    if expected == "gzip":
        assert json.loads(gzip.decompress(body)) == json.loads(request(path)[2])
    if expected:
        assert len(body) < len(request(path)[2])
    status, _, cached = request(path, extra_headers={"Accept-Encoding": accept, "If-None-Match": headers["ETag"]})
    assert status == 304 and not cached
    if expected:
        assert request(path, extra_headers={"Accept-Encoding": "identity", "If-None-Match": headers["ETag"]})[0] == 200
    status, head, empty = request(path, method="HEAD", extra_headers={"Accept-Encoding": accept})
    assert status == 200 and not empty and int(head["Content-Length"]) == len(body)


def test_identity_exclusion_and_sidecar_paths_do_not_bypass_the_allowlist(gateway):
    _, request = gateway
    assert request("/maple-login/assets/login-logo.png", extra_headers={"Accept-Encoding": "identity;q=0, *;q=0"})[0] == 406
    for path in ("login.js.br", "login.js.gz", "../auth.py.br", "%2e%2e/front.env.gz"):
        assert request("/maple-login/assets/" + path, extra_headers={"Accept-Encoding": "br"})[0] == 404
    original = json.loads(request("/maple-login/assets/case-demo.json")[2])
    assert json.loads(request("/maple-login/assets/case-demo.min.json")[2]) == original


def test_compression_does_not_buffer_streaming_or_search_api_routes():
    gateway = (ROOT / "deploy/sandbox/Caddyfile.front").read_text()
    scope = gateway.split("@page-assets {", 1)[1].split("}", 1)[0]
    assert "path / /maple-login*" in scope
    assert "/api/*" not in scope and "/liveopt-api/*" not in scope
    assert "encode @page-assets zstd gzip" in gateway
    assert "flush_interval -1" in gateway
