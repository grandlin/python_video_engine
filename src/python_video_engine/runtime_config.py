from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("python_video_engine.runtime_config")

DEFAULT_REMOTE_CONFIG_URL = ""
REMOTE_CONFIG_URL = os.getenv("VIDEO_ENGINE_REMOTE_CONFIG_URL", DEFAULT_REMOTE_CONFIG_URL).strip()
LOCAL_CONFIG_PATH = Path.home() / ".python_video_engine_runtime_config.json"
PROJECT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "remote-config" / "video-engine-config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "local-default",
    "llm": {
        "api_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "timeout_seconds": 120,
        "api_key_env": "SILICONFLOW_API_KEY",
        "requires_api_key": True,
        "system_prompt": "你擅长撰写中文外贸工厂短视频口播文案。",
        "script_language": "zh-CN",
        "translation_enabled": False,
    },
    "tts": {
        "api_url": "https://tts.zunqianlin.workers.dev/v1/audio/speech",
        "timeout_seconds": 120,
        "retry_count": 3,
        "model": "tts-1",
    },
    "voices": {
        "default_label": "温柔女声",
        "items": [
            {"label": "温柔女声", "key": "female_standard", "provider_voice": "zh-CN-XiaoxiaoNeural", "enabled": True},
            {"label": "活力男声", "key": "male_dynamic", "provider_voice": "zh-CN-YunxiNeural", "enabled": True},
            {"label": "成熟男声", "key": "male_mature", "provider_voice": "zh-CN-YunjianNeural", "enabled": True},
            {"label": "童声", "key": "child_cute", "provider_voice": "zh-CN-XiaoyiNeural", "enabled": True},
        ],
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


def get_enabled_voices() -> list[dict[str, Any]]:
    items = get_config_value("voices", "items", default=[]) or []
    enabled: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("enabled", True):
            continue
        label = str(item.get("label", "")).strip()
        key = str(item.get("key", "")).strip()
        provider_voice = str(item.get("provider_voice", "")).strip()
        if label and key and provider_voice:
            enabled.append({"label": label, "key": key, "provider_voice": provider_voice})
    return enabled


def get_default_voice_label() -> str:
    configured = str(get_config_value("voices", "default_label", default="")).strip()
    labels = [item["label"] for item in get_enabled_voices()]
    if configured and configured in labels:
        return configured
    return labels[0] if labels else "温柔女声"
