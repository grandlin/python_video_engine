from __future__ import annotations

import logging
import os
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

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
        if not custom:
            custom = str(os.getenv("HTTPS_PROXY", "")).strip() or str(os.getenv("HTTP_PROXY", "")).strip()
        if custom:
            use_proxy = True
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


def format_proxy_env_summary() -> str:
    keys = ["USE_PROXY", "CUSTOM_PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"]
    parts: list[str] = []
    for k in keys:
        v = str(os.getenv(k, "")).strip()
        if v:
            parts.append(f"{k}={v}")
    return " ; ".join(parts) if parts else "(empty)"


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_default_log_dir(app_name: str = "python_video_engine") -> Path:
    home = Path.home()
    return home / f".{app_name}" / "logs"


def append_log_line(message: str, app_name: str = "python_video_engine", file_name: str = "app.log") -> None:
    try:
        log_dir = get_default_log_dir(app_name=app_name)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / file_name
        line = f"[{_now_ts()}] {message}\n"
        log_path.write_text(log_path.read_text(encoding="utf-8", errors="ignore") + line, encoding="utf-8", errors="ignore") if log_path.exists() else log_path.write_text(line, encoding="utf-8", errors="ignore")
    except Exception:
        return


def diagnose_url_connectivity(url: str, timeout_seconds: float = 6.0, proxy_settings: ProxySettings | None = None) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    scheme = (parsed.scheme or "").lower()
    port = parsed.port or (443 if scheme == "https" else 80)

    lines: list[str] = []
    lines.append("[NetworkDiag] url=" + url)
    lines.append("[NetworkDiag] proxy_env=" + format_proxy_env_summary())

    if not host:
        lines.append("[NetworkDiag] host=INVALID")
        return "\n".join(lines)

    lines.append(f"[NetworkDiag] host={host} port={port}")

    try:
        socket.getaddrinfo(host, port)
        lines.append("[NetworkDiag] dns=ok")
    except Exception as exc:
        lines.append(f"[NetworkDiag] dns=fail err={exc}")

    ok, detail = check_tcp_connectivity(host, int(port), timeout_seconds=min(timeout_seconds, 3.0))
    lines.append(f"[NetworkDiag] tcp={ 'ok' if ok else 'fail' } detail={detail}")

    settings = proxy_settings or ProxySettings.from_env()
    try:
        with build_httpx_client(timeout_seconds=float(timeout_seconds), proxy_settings=settings) as client:
            try:
                resp = client.head(url)
            except httpx.HTTPStatusError as exc:
                resp = exc.response
            except Exception:
                resp = None
            if resp is None:
                resp = client.get(url)
        lines.append(f"[NetworkDiag] http_probe=ok status={resp.status_code}")
    except httpx.ProxyError as exc:
        lines.append(f"[NetworkDiag] http_probe=proxy_error err={exc}")
    except httpx.ConnectError as exc:
        lines.append(f"[NetworkDiag] http_probe=connect_error err={exc}")
    except httpx.ConnectTimeout as exc:
        lines.append(f"[NetworkDiag] http_probe=connect_timeout err={exc}")
    except httpx.ReadTimeout as exc:
        lines.append(f"[NetworkDiag] http_probe=read_timeout err={exc}")
    except httpx.TimeoutException as exc:
        lines.append(f"[NetworkDiag] http_probe=timeout err={exc}")
    except ssl.SSLError as exc:
        lines.append(f"[NetworkDiag] http_probe=tls_error err={exc}")
    except Exception as exc:
        lines.append(f"[NetworkDiag] http_probe=fail err={type(exc).__name__}: {exc}")

    return "\n".join(lines)
