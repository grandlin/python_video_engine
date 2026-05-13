#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple Claude CLI for PowerShell"""
import os
import sys
import httpx
from anthropic import Anthropic

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Please set it in PowerShell: $env:ANTHROPIC_API_KEY='your-key-here'")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python claude_cli.py 'your prompt here'")
        print("Example: python claude_cli.py 'explain Python decorators'")
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])

    # Check for proxy override
    use_proxy = os.getenv("CLAUDE_USE_PROXY", "auto").lower()
    proxy_url = None

    if use_proxy == "false" or use_proxy == "no":
        print("[Proxy] Disabled by CLAUDE_USE_PROXY")
    elif use_proxy == "auto" or use_proxy == "true":
        for port in [7897, 7890, 10809, 20171]:
            try:
                import socket
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    proxy_url = f"http://127.0.0.1:{port}"
                    print(f"[Proxy] Auto-detected: {proxy_url}")
                    break
            except:
                continue

    # Create httpx client with proxy if detected
    try:
        if proxy_url:
            http_client = httpx.Client(proxy=proxy_url, timeout=30.0)
        else:
            http_client = httpx.Client(timeout=30.0)
        client = Anthropic(api_key=api_key, http_client=http_client)
    except Exception as e:
        print(f"[Error] Failed to create client: {e}")
        sys.exit(1)

    print(f"Asking Claude: {prompt}\n")
    print("-" * 60)

    try:
        message = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )

        print(message.content[0].text)
        print("-" * 60)
        print(f"\nTokens used: {message.usage.input_tokens} in, {message.usage.output_tokens} out")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
