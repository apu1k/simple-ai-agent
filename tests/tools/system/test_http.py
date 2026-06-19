import socket
import urllib.error

from tools.system.http import _is_safe_hostname, http_get


class _State:
    def __init__(self):
        self.cwd = "."


def test_http_get_rejects_non_http_scheme():
    state = _State()
    out = http_get(state, "ftp://example.com")
    assert out.startswith("Error: Only http and https protocols are allowed.")


def test_http_get_requires_hostname():
    state = _State()
    out = http_get(state, "https:///path-only")
    assert out == "Error: URL has no hostname."


def test_http_get_rejects_invalid_headers_json():
    state = _State()
    out = http_get(state, "https://example.com", headers="{bad json")
    assert "Error: 'headers'" in out


def test_http_get_rejects_non_object_headers_string():
    state = _State()
    out = http_get(state, "https://example.com", headers='["x"]')
    assert out == "Error: 'headers' must decode to a JSON object."


def test_http_get_rejects_invalid_headers_type():
    state = _State()
    out = http_get(state, "https://example.com", headers=123)
    assert out == "Error: 'headers' must be a JSON object or JSON object string."


def test_http_get_accepts_headers_as_json_object_string(monkeypatch):
    state = _State()

    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, n=None):
            return b"ok"

        def getcode(self):
            return 200

        @property
        def headers(self):
            return {"Content-Type": "text/plain"}

    class _Opener:
        def open(self, req, timeout=0):
            captured["x-test"] = req.headers.get("X-test")
            return _Resp()

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com", include_body=True, headers='{"X-test":"1"}')
    assert "Status: 200" in out
    assert "Body:" in out
    assert captured["x-test"] == "1"


def test_http_get_rejects_header_crlf(monkeypatch):
    state = _State()
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com", headers={"X-Test": "a\r\nb"})
    assert out == "Error: Header names/values must not contain CR or LF characters."


def test_http_get_rejects_blocked_header(monkeypatch):
    state = _State()
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com", headers={"Host": "evil.example"})
    assert out == "Error: Header 'Host' is not allowed."


def test_http_get_truncates_body(monkeypatch):
    state = _State()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, n=None):
            # Return >100KB marker by one byte to trigger truncation path
            return b"a" * (100_000 + 1)

        def getcode(self):
            return 200

        @property
        def headers(self):
            return {"Content-Type": "text/plain"}

    class _Opener:
        def open(self, req, timeout=0):
            return _Resp()

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com", include_body=True)
    assert "Returned size: 100000 bytes" in out
    assert "[Response truncated: exceeded 100KB limit.]" in out


def test_http_get_non_utf8_body_message(monkeypatch):
    state = _State()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, n=None):
            return b"\xff\xfe\xfa"

        def getcode(self):
            return 200

        @property
        def headers(self):
            return {"Content-Type": "application/octet-stream"}

    class _Opener:
        def open(self, req, timeout=0):
            return _Resp()

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com", include_body=True)
    assert "[Response body is not valid UTF-8]" in out


def test_http_get_default_no_body(monkeypatch):
    state = _State()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, n=None):
            return b"secret-body"

        def getcode(self):
            return 200

        @property
        def headers(self):
            return {"Content-Type": "text/plain"}

    class _Opener:
        def open(self, req, timeout=0):
            return _Resp()

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com")
    assert "Status: 200" in out
    assert "Body:" not in out
    assert "secret-body" not in out


def test_http_get_redirect_blocked(monkeypatch):
    state = _State()

    class _Opener:
        def open(self, req, timeout=0):
            raise urllib.error.HTTPError(
                req.full_url,
                302,
                "Found",
                {"Location": "https://redirected.example"},
                None,
            )

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com")
    assert "Error: Redirects are not allowed. HTTP 302." in out


def test_http_get_http_error_message(monkeypatch):
    state = _State()

    class _Opener:
        def open(self, req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com/missing")
    assert "Error: HTTP 404" in out
    assert "Not Found" in out


def test_http_get_urlerror_message(monkeypatch):
    state = _State()

    class _Opener:
        def open(self, req, timeout=0):
            raise urllib.error.URLError("network down")

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com")
    assert "Error: URL error fetching https://example.com:" in out


def test_http_get_timeout_message(monkeypatch):
    state = _State()

    class _Opener:
        def open(self, req, timeout=0):
            raise TimeoutError()

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com")
    assert out == "Error: Request to https://example.com timed out after 15s."


def test_http_get_ssrf_block_short_circuit(monkeypatch):
    state = _State()
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: "Error: Blocked access to private/local/multicast IP 127.0.0.1.")

    called = {"open": False}

    class _Opener:
        def open(self, req, timeout=0):
            called["open"] = True
            raise AssertionError("open() should not be called when SSRF check fails")

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())

    out = http_get(state, "https://example.com")
    assert out.startswith("Error: Blocked access")
    assert called["open"] is False


def test_http_get_rejects_blocked_header_case_insensitive(monkeypatch):
    state = _State()
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    for header_name in ("Host", "HOST", "host"):
        out = http_get(state, "https://example.com", headers={header_name: "evil.example"})
        assert out == f"Error: Header '{header_name}' is not allowed."


def test_http_get_truncates_without_body_when_include_body_false(monkeypatch):
    state = _State()

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, n=None):
            return b"a" * (100_000 + 1)

        def getcode(self):
            return 200

        @property
        def headers(self):
            return {"Content-Type": "text/plain"}

    class _Opener:
        def open(self, req, timeout=0):
            return _Resp()

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com", include_body=False)
    assert "Returned size: 100000 bytes" in out
    assert "Body:" not in out
    assert "[Response truncated: exceeded 100KB limit.]" not in out


def test_http_get_redirect_blocked_includes_location(monkeypatch):
    state = _State()

    class _Opener:
        def open(self, req, timeout=0):
            raise urllib.error.HTTPError(
                req.full_url,
                301,
                "Moved Permanently",
                {"Location": "https://redirected.example/new"},
                None,
            )

    monkeypatch.setattr("tools.system.http._build_no_redirect_opener", lambda: _Opener())
    monkeypatch.setattr("tools.system.http._is_safe_hostname", lambda h: None)

    out = http_get(state, "https://example.com")
    assert "Error: Redirects are not allowed. HTTP 301." in out
    assert "Location: https://redirected.example/new" in out


def test_is_safe_hostname_blocks_private_ipv4(monkeypatch):
    monkeypatch.setattr(
        "tools.system.http.socket.getaddrinfo",
        lambda hostname, port: [(socket.AF_INET, None, None, None, ("10.0.0.1", 0))],
    )

    out = _is_safe_hostname("example.com")
    assert out is not None
    assert "Blocked access" in out


def test_is_safe_hostname_blocks_loopback_ipv6(monkeypatch):
    monkeypatch.setattr(
        "tools.system.http.socket.getaddrinfo",
        lambda hostname, port: [(socket.AF_INET6, None, None, None, ("::1", 0, 0, 0))],
    )

    out = _is_safe_hostname("example.com")
    assert out is not None
    assert "Blocked access" in out


def test_is_safe_hostname_allows_public_ipv4(monkeypatch):
    monkeypatch.setattr(
        "tools.system.http.socket.getaddrinfo",
        lambda hostname, port: [(socket.AF_INET, None, None, None, ("93.184.216.34", 0))],
    )

    out = _is_safe_hostname("example.com")
    assert out is None
