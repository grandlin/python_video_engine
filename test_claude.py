#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Claude with hardcoded key"""
import sys
import json
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Hardcoded for testing
API_KEY = "sk-WRB6dd1c1f568bf137c41183dfc1bc4ed7c34c46b0bzgLX8"

if len(sys.argv) < 2:
    print("Usage: python test_claude.py 'your prompt'")
    sys.exit(1)

prompt = " ".join(sys.argv[1:])

# Auto-detect proxy
proxies = None
for port in [7897, 7890, 10809, 20171]:
    try:
        import socket
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            proxy_url = f"http://127.0.0.1:{port}"
            proxies = {"http": proxy_url, "https": proxy_url}
            print(f"[Proxy] {proxy_url}")
            break
    except:
        continue

print(f"Asking: {prompt}\n")
print("-" * 60)

headers = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

payload = {
    "model": "claude-opus-4-7",
    "max_tokens": 4096,
    "messages": [{"role": "user", "content": prompt}]
}

try:
    response = requests.post(
        "https://aicoding.2233.ai/v1/messages",
        headers=headers,
        json=payload,
        proxies=proxies,
        timeout=30
    )
    response.raise_for_status()

    data = response.json()
    print(data["content"][0]["text"])
    print("-" * 60)
    print(f"\nTokens: {data['usage']['input_tokens']} in, {data['usage']['output_tokens']} out")

except requests.exceptions.RequestException as e:
    print(f"Error: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"Response: {e.response.text}")
    sys.exit(1)
