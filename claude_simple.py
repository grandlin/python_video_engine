#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple Claude CLI using requests"""
import os
import sys
import json
import requests

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    # Clean up API key (remove quotes and whitespace)
    api_key = api_key.strip().strip('"').strip("'")

    if len(sys.argv) < 2:
        print("Usage: python claude_simple.py 'your prompt here'")
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
                print(f"[Proxy] Auto-detected: {proxy_url}")
                break
        except:
            continue

    print(f"Asking Claude: {prompt}\n")
    print("-" * 60)

    # Support custom base URL
    base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    api_endpoint = f"{base_url.rstrip('/')}/v1/messages"

    headers = {
        "x-api-key": api_key,
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
            api_endpoint,
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

if __name__ == "__main__":
    main()
