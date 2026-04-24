from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("python_video_engine.runtime_config")

DEFAULT_REMOTE_CONFIG_URL = (
    "https://python-video-engine-57pd-k5waf6gmn-grand1.vercel.app/remote-config/video-engine-config.json"
)
REMOTE_CONFIG_URL = os.getenv("VIDEO_ENGINE_REMOTE_CONFIG_URL", DEFAULT_REMOTE_CONFIG_URL).strip()
LOCAL_CONFIG_PATH = Path.home() / ".python_video_engine_runtime_config.json"
PROJECT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "remote-config" / "video-engine-config.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "version": "local-default",
    "llm": {
        "api_url": "https://api.siliconflow.cn/v1/chat/completions",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "timeout_seconds": 90,
    },
    "tts": {
        "api_url": "https://tts.zunqianlin.workers.dev/v1/audio/speech",
        "timeout_seconds": 90,
        "retry_count": 3,
    },
    "subtitle": {
        "font_size": 11,
        "min_chars": 8,
        "max_chars": 14,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[RuntimeConfig] 读取本地配置失败: %s path=%s", exc, path)
    return None


def _write_cache(config: dict[str, Any]) -> None:
    try:
        LOCAL_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("[RuntimeConfig] 写入本地缓存失败: %s path=%s", exc, LOCAL_CONFIG_PATH)


@lru_cache(maxsize=1)
def get_runtime_config() -> dict[str, Any]:
    config = _deep_merge(DEFAULT_CONFIG, _read_json_file(PROJECT_CONFIG_PATH) or {})

    if REMOTE_CONFIG_URL:
        try:
            response = requests.get(REMOTE_CONFIG_URL, timeout=10)
            response.raise_for_status()
            remote_config = response.json()
            config = _deep_merge(config, remote_config)
            _write_cache(remote_config)
            logger.info("[RuntimeConfig] 已加载远程配置: version=%s", config.get("version", "unknown"))
            return config
        except Exception as exc:
            logger.warning("[RuntimeConfig] 远程配置加载失败，尝试使用缓存: %s", exc)

    cached_config = _read_json_file(LOCAL_CONFIG_PATH)
    if cached_config:
        config = _deep_merge(config, cached_config)
        logger.info("[RuntimeConfig] 已加载本地缓存配置: version=%s", config.get("version", "unknown"))
        return config

    logger.info("[RuntimeConfig] 使用项目内置配置: version=%s", config.get("version", "unknown"))
    return config


def get_config_value(*keys: str, default: Any = None) -> Any:
    data: Any = get_runtime_config()
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data
