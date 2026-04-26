from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger("python_video_engine.network")


@dataclass(frozen=True, slots=True)
class ProxySettings:
    use_proxy: bool
    custom_proxy_url: str

    @staticmethod
    def from_env() -> "ProxySettings":
        use_proxy = str(os.getenv("USE_PROXY", "False")).strip().lower() in {"1", "true", "yes", "y", "on"}
        custom = str(os.getenv("CUSTOM_PROXY_URL", "")).strip()
        return ProxySettings(use_proxy=use_proxy, custom_proxy_url=custom)

    def to_proxy_url(self) -> str | None:
        if not self.use_proxy:
            return None
        return self.custom_proxy_url or None


def build_httpx_client(timeout_seconds: float = 120.0, proxy_settings: ProxySettings | None = None) -> httpx.Client:
    settings = proxy_settings or ProxySettings.from_env()
    proxy_url = settings.to_proxy_url()
    base_kwargs = {
        "timeout": httpx.Timeout(timeout_seconds),
        "trust_env": True,
        "follow_redirects": True,
    }

    if not proxy_url:
        return httpx.Client(**base_kwargs)

    try:
        return httpx.Client(**base_kwargs, proxies=proxy_url)
    except TypeError as exc:
        if "proxies" not in str(exc):
            raise
        return httpx.Client(**base_kwargs, proxy=proxy_url)


def check_tcp_connectivity(host: str, port: int, timeout_seconds: float = 3.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, "ok"
    except Exception as exc:
        return False, str(exc)
