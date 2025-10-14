from __future__ import annotations

from typing import Optional, Tuple

from django.http import HttpRequest


def client_ip(request: HttpRequest) -> Optional[str]:
    try:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            # take the first non-empty ip
            parts = [p.strip() for p in xff.split(',') if p.strip()]
            if parts:
                return parts[0]
        ip = request.META.get("REMOTE_ADDR")
        return ip
    except Exception:
        return None


def lookup_asn(ip: str) -> Tuple[Optional[str], bool]:
    """
    Lightweight ASN/VPN heuristic.
    Returns (asn_string, vpn_suspected).
    This is a stub that can be upgraded to use MaxMind or ipinfo when configured.
    """
    if not ip:
        return None, False
    # Private/local ranges → never mark as VPN
    private_prefixes = ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "127.")
    if ip.startswith(private_prefixes):
        return None, False
    # Without a provider configured, we cannot reliably detect VPN; return unknown
    return None, False

