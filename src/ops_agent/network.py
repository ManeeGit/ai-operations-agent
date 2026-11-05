"""Bounded loopback HTTP, with a wall-clock deadline rather than idle timeout.

A timer shuts down the connected socket at the deadline. Capturing the socket
also covers HTTP/1.0 responses, for which HTTPConnection releases its reference
while HTTPResponse still owns the underlying stream. No proxies or redirects.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import threading
import time
from urllib.parse import urlsplit


def request_bytes(url: str, *, timeout: float, limit: int, body: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("only credential-free loopback HTTP is supported")
    if not ipaddress.ip_address(parsed.hostname or "").is_loopback or not parsed.port:
        raise ValueError("numeric loopback address and explicit port required")
    if not 0 < timeout <= 30 or not 1 <= limit <= 65536:
        raise ValueError("invalid network bounds")
    deadline = time.monotonic() + timeout
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    timer, response = None, None
    try:
        connection.connect()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("total HTTP deadline exceeded during connect")
        connected_socket = connection.sock
        def expire():
            try:
                connected_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        timer.start()
        connection.request("POST" if body is not None else "GET", parsed.path or "/", body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read(limit + 1)
        if time.monotonic() >= deadline:
            raise TimeoutError("total HTTP deadline exceeded")
        if response.length is not None and response.length > 0 and len(data) <= limit:
            raise http.client.IncompleteRead(data, response.length)
        if len(data) > limit:
            raise ValueError("HTTP response body exceeds configured limit")
        return response.status, data
    finally:
        if timer:
            timer.cancel()
        if response:
            response.close()
        connection.close()
