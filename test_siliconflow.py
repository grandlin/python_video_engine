from __future__ import annotations

import json
import sys

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

url = "https://api.siliconflow.cn/v1/chat/completions"
api_key = "sk-pgrghpkmgxcrjnxevxhlfwgcrhnfofayxcwydpcilmwwwomi"

payload = {
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [
        {
            "role": "system",
            "content": "你是一个资深的工业制造类短视频导演。你需要根据用户给的提示词，写出干脆利落、充满工厂真实感的旁白解说文案。不要有多余的废话，直接输出文案内容。",
        },
        {
            "role": "user",
            "content": "请根据以下关键词，为客户名点工贸写一段110到150字的中文短视频口播稿。要求：口语化自然，不要标题，不要分点，不要引号，突出工厂实力、产品工艺、品质控制和交付能力。关键词：电源连接器、金属车床件、精密冲压件、RoHS/REACH、来样定制、一站式服务。",
        },
    ],
    "temperature": 0.7,
    "max_tokens": 512,
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}",
}

resp = requests.post(url, json=payload, headers=headers, timeout=90)
print("status:", resp.status_code)

try:
    data = resp.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if content:
        print("\nscript:\n")
        print(content)
except Exception:
    print(resp.text)
