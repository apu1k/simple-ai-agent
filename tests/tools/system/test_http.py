from tools.system.http import http_get


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
