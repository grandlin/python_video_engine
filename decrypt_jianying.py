#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, base64, zlib, gzip, sys
from pathlib import Path

def decrypt_jianying_draft(file_path):
    with open(file_path, 'rb') as f:
        data = f.read()

    methods = [
        ("Direct JSON", lambda d: json.loads(d)),
        ("Base64+zlib", lambda d: json.loads(zlib.decompress(base64.b64decode(d)))),
        ("Base64+gzip", lambda d: json.loads(gzip.decompress(base64.b64decode(d)))),
        ("Pure zlib", lambda d: json.loads(zlib.decompress(d))),
        ("Pure gzip", lambda d: json.loads(gzip.decompress(d))),
        ("Base64+zlib(raw)", lambda d: json.loads(zlib.decompress(base64.b64decode(d), -zlib.MAX_WBITS))),
    ]

    for name, method in methods:
        try:
            obj = method(data)
            print(f"[OK] Method: {name}")
            return obj
        except:
            pass

    print("[FAIL] All methods failed")
    print(f"File size: {len(data)} bytes")
    return None

def analyze_timeline_structure(obj):
    print("\n" + "="*60)
    print("Draft Structure Analysis")
    print("="*60)

    print("\n[Top-level keys]")
    for key in obj.keys():
        value = obj[key]
        if isinstance(value, list):
            print(f"  {key}: array (len={len(value)})")
        elif isinstance(value, dict):
            print(f"  {key}: object (keys={len(value)})")
        else:
            print(f"  {key}: {type(value).__name__}")

    print("\n[Timeline-related keys]")
    for key in obj.keys():
        if any(x in key.lower() for x in ['timeline', 'sequence', 'track']):
            print(f"  Found: {key}")

    if 'tracks' in obj:
        print(f"\n[tracks array]")
        tracks = obj['tracks']
        print(f"  Count: {len(tracks)}")
        if tracks:
            print(f"  First track keys: {list(tracks[0].keys())}")
            for i, track in enumerate(tracks[:5]):
                print(f"  Track {i}: type={track.get('type')}, name={track.get('name')}, render_index={track.get('render_index')}")

    if 'sequences' in obj:
        print(f"\n[sequences array]")
        sequences = obj['sequences']
        print(f"  Count: {len(sequences)}")
        if sequences:
            print(f"  First sequence keys: {list(sequences[0].keys())}")
            for i, seq in enumerate(sequences):
                print(f"  Sequence {i}: id={seq.get('id')}, name={seq.get('name')}")

    output_path = Path(__file__).parent / "template_decrypted.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Saved to: {output_path}")

    return obj

if __name__ == "__main__":
    template_path = Path(__file__).parent / "template_multi_timeline.json"
    print(f"Decrypting: {template_path}")
    obj = decrypt_jianying_draft(template_path)
    if obj:
        analyze_timeline_structure(obj)
