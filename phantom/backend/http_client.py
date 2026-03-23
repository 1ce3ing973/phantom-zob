"""Shared HTTP client for the Phantom backend (stdlib only — no pip deps)."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, Mapping, Optional, Union

from config import DEFAULT_HEADERS, HTTP_TIMEOUT_SECONDS
from logger import logger

# ---------------------------------------------------------------------------
# Response types (httpx-compatible subset)
# ---------------------------------------------------------------------------


class HTTPStatusError(Exception):
    """Raised when raise_for_status() sees a 4xx/5xx response."""

    def __init__(self, message: str, response: "PhantomResponse") -> None:
        super().__init__(message)
        self.response = response


class _CIMap:
    """Case-insensitive header map (matches httpx-style .get(\"Content-Length\"))."""

    def __init__(self, raw: Mapping[str, str]) -> None:
        self._raw = {k.lower(): v for k, v in raw.items()}

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._raw.get(key.lower(), default)


class PhantomResponse:
    def __init__(
        self,
        status_code: int,
        headers: Mapping[str, str],
        content: bytes,
    ) -> None:
        self.status_code = int(status_code)
        self.headers = _CIMap(headers)
        self._content = content

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise HTTPStatusError(f"HTTP {self.status_code}", self)


class PhantomStreamResponse:
    """Streaming body for large downloads (urllib file-like)."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw
        code = getattr(raw, "status", None)
        if code is None:
            code = getattr(raw, "code", 0)
        self.status_code = int(code)
        hdrs = getattr(raw, "headers", None)
        self.headers = _CIMap(_header_map(hdrs)) if hdrs is not None else _CIMap({})

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            try:
                body = self._raw.read()
            except Exception:
                body = b""
            hdrs = getattr(self._raw, "headers", None)
            plain = _header_map(hdrs) if hdrs is not None else {}
            raise HTTPStatusError(
                f"HTTP {self.status_code}",
                PhantomResponse(self.status_code, plain, body),
            )

    def iter_bytes(self, chunk_size: int = 65536) -> Iterator[bytes]:
        while True:
            chunk = self._raw.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:
            pass


class _StreamCM:
    def __init__(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]],
        timeout: float,
    ) -> None:
        self._method = method
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._raw: Any = None

    def __enter__(self) -> PhantomStreamResponse:
        merged = _merge_headers(self._headers)
        req = urllib.request.Request(
            self._url,
            method=self._method,
            headers=merged,
        )
        try:
            self._raw = urllib.request.urlopen(req, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            self._raw = exc
        return PhantomStreamResponse(self._raw)

    def __exit__(self, *args: Any) -> None:
        if self._raw is not None:
            try:
                self._raw.close()
            except Exception:
                pass


class PhantomHttpClient:
    """Drop-in subset of httpx.Client used by Phantom."""

    def get(
        self,
        url: str,
        *,
        follow_redirects: bool = True,
        timeout: Optional[float] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> PhantomResponse:
        del follow_redirects  # urllib follows redirects by default
        return _request("GET", url, None, headers, timeout)

    def head(
        self,
        url: str,
        *,
        follow_redirects: bool = True,
        timeout: Optional[float] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> PhantomResponse:
        del follow_redirects
        return _request("HEAD", url, None, headers, timeout)

    def post(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        content: Optional[Union[bytes, str]] = None,
        json: Any = None,
        follow_redirects: bool = True,
        timeout: Optional[float] = None,
    ) -> PhantomResponse:
        del follow_redirects
        body: Optional[bytes]
        if json is not None:
            body = json_dumps_bytes(json)
            merged = _merge_headers(headers)
            merged = dict(merged)
            merged.setdefault("Content-Type", "application/json")
        elif content is not None:
            body = content if isinstance(content, bytes) else content.encode("utf-8")
            merged = _merge_headers(headers)
        else:
            body = None
            merged = _merge_headers(headers)
        return _request("POST", url, body, merged, timeout)

    def stream(
        self,
        method: str,
        url: str,
        *,
        follow_redirects: bool = True,
        timeout: Optional[float] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> _StreamCM:
        del follow_redirects
        to = float(timeout if timeout is not None else HTTP_TIMEOUT_SECONDS)
        return _StreamCM(method.upper(), url, headers=headers, timeout=to)


def json_dumps_bytes(data: Any) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _header_map(msg: Any) -> Dict[str, str]:
    if hasattr(msg, "items"):
        return {k.lower(): v for k, v in msg.items()}
    return {}


def _merge_headers(extra: Optional[Mapping[str, str]]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for k, v in DEFAULT_HEADERS.items():
        merged[k] = v
    if extra:
        merged.update(dict(extra))
    return merged


def _request(
    method: str,
    url: str,
    data: Optional[bytes],
    headers: Optional[Mapping[str, str]],
    timeout: Optional[float],
) -> PhantomResponse:
    merged = _merge_headers(headers)
    to = float(timeout if timeout is not None else HTTP_TIMEOUT_SECONDS)
    req = urllib.request.Request(url, data=data, method=method, headers=merged)
    try:
        with urllib.request.urlopen(req, timeout=to) as resp:
            body = resp.read()
            code = getattr(resp, "status", None) or getattr(resp, "code", 200)
            return PhantomResponse(int(code), _header_map(resp.headers), body)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        return PhantomResponse(int(exc.code), _header_map(exc.headers), body)
    except socket.timeout as exc:
        raise TimeoutError(str(exc)) from exc


_HTTP_CLIENT: Optional[PhantomHttpClient] = None


def ensure_http_client(context: str = "") -> PhantomHttpClient:
    """Return the shared HTTP client (stdlib urllib)."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        prefix = f"{context}: " if context else ""
        logger.log(f"{prefix}Initializing Phantom HTTP client (urllib)...")
        _HTTP_CLIENT = PhantomHttpClient()
        logger.log(f"{prefix}HTTP client ready")
    return _HTTP_CLIENT


def get_http_client() -> PhantomHttpClient:
    """Return the shared HTTP client, creating it if necessary."""
    return ensure_http_client()


def close_http_client(context: str = "") -> None:
    """No persistent connections; reset singleton for unload symmetry."""
    global _HTTP_CLIENT
    _HTTP_CLIENT = None
    prefix = f"{context}: " if context else ""
    logger.log(f"{prefix}HTTP client released")


def is_timeout_error(exc: BaseException) -> bool:
    """True if the exception is likely a network timeout."""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    if isinstance(exc, OSError):
        msg = str(exc).lower()
        return "timed out" in msg or "10060" in msg
    return False


def is_http_status_error(exc: BaseException) -> bool:
    return isinstance(exc, HTTPStatusError)

