from __future__ import annotations

import json
import os
from typing import Any

import requests

DEFAULT_LLM_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_LLM_MODEL = "qwen-plus"
DEFAULT_TIMEOUT_SECONDS = 120


def _json_response(status_code: int, payload: dict[str, Any]) -> tuple[str, int, dict[str, str]]:
    return json.dumps(payload, ensure_ascii=False), status_code, {"Content-Type": "application/json; charset=utf-8"}


def handler(request):
    if request.method != "POST":
        return _json_response(405, {"error": "Method not allowed"})

    api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    api_url = os.environ.get("LLM_API_URL", "").strip() or DEFAULT_LLM_API_URL
    llm_model = os.environ.get("LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL
    timeout_seconds = int((os.environ.get("API_TIMEOUT", "").strip() or str(DEFAULT_TIMEOUT_SECONDS)))

    if not api_key:
        return _json_response(500, {"error": "Missing SILICONFLOW_API_KEY in Vercel environment"})

    try:
        body = request.get_json()
    except Exception:
        body = None

    if not isinstance(body, dict):
        return _json_response(400, {"error": "Invalid JSON payload"})

    payload = dict(body)
    payload["model"] = str(payload.get("model") or llm_model)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=timeout_seconds)
        return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "application/json; charset=utf-8")}
    except requests.RequestException as exc:
        return _json_response(502, {"error": "Upstream request failed", "detail": str(exc)})
