"""
tools/system/http.py

Safe HTTP GET tool.
Blocks local/private IPs, limited to 100KB.
"""

import json
import socket
import urllib.request
import urllib.error
from urllib.parse import urlparse
from http.client import HTTPMessage

try:
    import ipaddress
except ImportError:
    ipaddress = None  # Fallback if ipaddress is not available (rare in stdlib)

from tools._base import tool

MAX_RESPONSE_BYTES = 100_000
PROTOCOL_WHITELIST = frozenset(["http", "https"])
BLOCKED_HEADERS = frozenset(["host", "content-length", "transfer-encoding", "connection"])


def _is_safe_hostname(hostname: str) -> str | None:
    """Check if hostname resolves to a blocked local/private/multicast IP.
    
    Blocks IPv4 and IPv6 private, loopback, link-local, multicast, unspecified,
    and reserved addresses. Does NOT prevent DNS rebinding attacks.
    """
    if ipaddress is None:
        # Fallback to basic string check if ipaddress module is missing
        try:
            ip_addr = socket.gethostbyname(hostname)
            if ip_addr.startswith("127.") or ip_addr.startswith("10.") or ip_addr.startswith("192.168.") or ip_addr.startswith("169.254."):
                return f"Error: Blocked access to local/private network."
        except socket.gaierror:
            return None
        return None

    try:
        addrs = socket.getaddrinfo(hostname, None)  # No AF_INET restriction - check IPv4 and IPv6
        for fam, _, _, _, sockaddr in addrs:
            ip_str = sockaddr[0]
            ip_obj = ipaddress.ip_address(ip_str)
            # Block all dangerous address types
            if (
                ip_obj.is_private or
                ip_obj.is_loopback or
                ip_obj.is_link_local or
                ip_obj.is_reserved or
                ip_obj.is_multicast or
                ip_obj.is_unspecified
            ):
                return f"Error: Blocked access to private/local/multicast IP {ip_str}."
    except socket.gaierror:
        return None  # DNS error, will be caught later during fetch
    except ValueError:
        return None

    return None


def _validate_header(name: str, value: str) -> str | None:
    if "\r" in name or "\n" in name or "\r" in value or "\n" in value:
        return "Error: Header names/values must not contain CR or LF characters."
    if name.strip().lower() in BLOCKED_HEADERS:
        return f"Error: Header '{name}' is not allowed."
    return None


def _build_no_redirect_opener() -> urllib.request.OpenerDirector:
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    return urllib.request.build_opener(_NoRedirect)


@tool(
    description=(
        "Fetch a URL via HTTP GET. "
        "Only http/https allowed. Local/private IPs blocked. "
        "Response limited to 100KB."
    ),
    params={
        "url": "The full URL to fetch.",
        "include_body": "Whether to include the response body (default False).",
        "headers": "Optional JSON object of extra headers.",
    },
    requires_state=True,
    example={
        "action": "http_get",
        "input": {"url": "https://example.com", "include_body": True, "headers": "{}"},
    },
)
def http_get(state, url: str, include_body: bool = False, headers: str | dict = "{}") -> str:
    parsed = urlparse(url)
    if parsed.scheme not in PROTOCOL_WHITELIST:
        return "Error: Only http and https protocols are allowed."
    if not parsed.hostname:
        return "Error: URL has no hostname."

    # SSRF check
    error = _is_safe_hostname(parsed.hostname)
    if error:
        return error

    # Build request
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "SimpleAI/1.0")

    # Accept headers as JSON string (backward compatible) or dict
    if isinstance(headers, str):
        try:
            extra = json.loads(headers)
        except json.JSONDecodeError:
            return "Error: 'headers' must be a valid JSON object string or a JSON object."
    elif isinstance(headers, dict):
        extra = headers
    else:
        return "Error: 'headers' must be a JSON object or JSON object string."

    if not isinstance(extra, dict):
        return "Error: 'headers' must decode to a JSON object."

    for k, v in extra.items():
        key = str(k)
        value = str(v)
        header_error = _validate_header(key, value)
        if header_error:
            return header_error
        req.add_header(key, value)

    opener = _build_no_redirect_opener()

    # Fetch (bounded read to enforce 100KB limit during download)
    try:
        with opener.open(req, timeout=15) as resp:
            fetched = resp.read(MAX_RESPONSE_BYTES + 1)
            status_code = resp.getcode()
            content_type = resp.headers.get("Content-Type", "unknown")
    except urllib.error.HTTPError as e:
        if 300 <= int(getattr(e, "code", 0)) < 400:
            location = ""
            hdrs = getattr(e, "headers", None)
            if isinstance(hdrs, HTTPMessage):
                location = hdrs.get("Location", "")
            elif isinstance(hdrs, dict):
                location = hdrs.get("Location", "")
            return f"Error: Redirects are not allowed. HTTP {e.code}. Location: {location}"
        return f"Error: HTTP {e.code} for {url}: {e.reason}"
    except urllib.error.URLError as e:
        return f"Error: URL error fetching {url}: {e.reason}"
    except TimeoutError:
        return f"Error: Request to {url} timed out after 15s."
    except Exception as e:
        return f"Error: Failed to fetch {url}: {e}"

    truncated = len(fetched) > MAX_RESPONSE_BYTES
    returned_bytes = fetched[:MAX_RESPONSE_BYTES] if truncated else fetched
    returned_size = len(returned_bytes)

    # Format
    lines = [
        f"Status: {status_code}",
        f"Content-Type: {content_type}",
        f"Returned size: {returned_size} bytes",
    ]

    if include_body:
        try:
            text = returned_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = "[Response body is not valid UTF-8]"

        if truncated:
            text += "\n...\n[Response truncated: exceeded 100KB limit.]"

        lines.append("Body:")
        lines.append(text)

    return "\n".join(lines)
