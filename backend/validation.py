"""Shared SSRF-prevention validators for user-supplied network targets (IMAP
host, Immich URL, ...). Raises plain ValueError — callers translate that into
their own feature-specific error type."""

import ipaddress
import socket
from urllib.parse import urlparse


def validate_external_host(host: str, field_name: str = "Host") -> None:
    """Reject empty, localhost, or private/loopback/link-local/multicast hosts."""
    host = host.strip().lower()
    if not host:
        raise ValueError(f"{field_name} cannot be empty")
    if host in ("localhost", "localhost.localdomain"):
        raise ValueError(f"{field_name} cannot be a local address")
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
                raise ValueError(f"{field_name} cannot be a private or local address")
    except ValueError:
        raise
    except Exception:
        # DNS resolution failed — still allow it (offline/dev environments)
        pass


def validate_external_url(url: str, field_name: str = "URL") -> str:
    """Validate a user-supplied HTTP/HTTPS URL and reject private/loopback targets."""
    url = url.strip()
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{field_name} must use http or https")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{field_name} is missing a hostname")
    if hostname in ("localhost", "localhost.localdomain"):
        raise ValueError(f"{field_name} cannot point to a local address")
    try:
        infos = socket.getaddrinfo(hostname, None)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast:
                raise ValueError(f"{field_name} cannot point to a private or local address")
    except ValueError:
        raise
    except Exception:
        # DNS resolution failed at validation time — allow it; connection attempt will fail naturally
        pass
    return url
