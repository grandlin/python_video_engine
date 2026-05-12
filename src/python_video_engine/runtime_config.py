from __future__ import annotations

import json
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("python_video_engine.runtime_config")

DEFAULT_REMOTE_CONFIG_URL = "https://video-bot-config.vercel.app/config.json"
REMOTE_CONFIG_URL = DEFAULT_REMOTE_CONFIG_URL

_APP_BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
LEGACY_RUNTIME_CACHE_PATH = _APP_BASE_DIR / "runtime_config.local.json"
PROJECT_CONFIG_PATH = _APP_BASE_DIR / "remote-config" / "video-engine-config.json"
USER_SETTINGS_PATH = _APP_BASE_DIR / "user_settings.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "version": "local-default",
    "llm": {
        "api_url": "https://python-video-engine-57pd.vercel.app/api/chat",
        "model": "qwen-plus",
        "timeout_seconds": 120,
        "api_key_env": "",
        "requires_api_key": False,
        "system_prompt": "你擅长撰写中文外贸工厂短视频口播文案。",
        "script_language": "zh-CN",
        "translation_enabled": False,
    },
    "tts": {
        "api_url": "https://tts.zunqianlin.workers.dev/v1/audio/speech",
        "timeout_seconds": 180,
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
    "scan": {
        "min_ready_materials": 30,
    },
    "draft": {
        "audio_buffer_start": 0.1,
        "audio_buffer_end": 0.1,
    },
}


def cleanup_legacy_secret_cache() -> None:
    try:
        if LEGACY_RUNTIME_CACHE_PATH.exists() and LEGACY_RUNTIME_CACHE_PATH.is_file():
            os.remove(LEGACY_RUNTIME_CACHE_PATH)
            logger.info("[RuntimeConfig] 已清理历史敏感缓存文件: %s", LEGACY_RUNTIME_CACHE_PATH)
    except Exception:
        pass


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
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("[RuntimeConfig] 读取本地配置失败: %s path=%s", exc, path)
    return None


def _load_user_settings_patch() -> dict[str, Any]:
    payload = _read_json_file(USER_SETTINGS_PATH)
    if not payload:
        return {}
    draft = payload.get("draft")
    if not isinstance(draft, dict):
        return {}

    patch_draft: dict[str, Any] = {}
    for key in ("audio_buffer_start", "audio_buffer_end"):
        if key in draft:
            try:
                value = float(draft[key])
            except Exception:
                continue
            patch_draft[key] = max(0.0, min(1.0, value))

    return {"draft": patch_draft} if patch_draft else {}


def get_remote_config() -> dict[str, Any]:
    response = requests.get(REMOTE_CONFIG_URL, timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("remote config must be a JSON object")

    dashscope_key = str(payload.get("dashscope_key", "") or "").strip()
    llm_api_url = str(payload.get("llm_api_url", "") or "").strip()
    llm_model = str(payload.get("llm_model", "") or "").strip()

    llm_patch: dict[str, Any] = {}
    if llm_api_url:
        llm_patch["api_url"] = llm_api_url
    if llm_model:
        llm_patch["model"] = llm_model
    if dashscope_key:
        llm_patch["api_key"] = dashscope_key

    return {"llm": llm_patch} if llm_patch else {}


@lru_cache(maxsize=1)
def get_runtime_config() -> dict[str, Any]:
    config = _deep_merge(DEFAULT_CONFIG, _read_json_file(PROJECT_CONFIG_PATH) or {})

    try:
        remote_patch = get_remote_config()
        config = _deep_merge(config, remote_patch)
        logger.info("[RuntimeConfig] 已加载远程配置: %s", REMOTE_CONFIG_URL)
    except Exception as exc:
        logger.warning("[RuntimeConfig] 远程配置加载失败，继续使用本地内置配置: %s", exc)

    user_settings_patch = _load_user_settings_patch()
    if user_settings_patch:
        config = _deep_merge(config, user_settings_patch)

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
