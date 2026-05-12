#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速测试混剪模式"""

from pathlib import Path
from src.python_video_engine import MaterialFetcher, AssemblyEngine, VideoExporter

# 配置
BASE_PATH = r"Z:\00_客户06105名点工贸_测试"  # 改成你的素材路径
CLIENT_NAME = "测试客户"
TARGET_DURATION = 30  # 目标时长（秒）
OUTPUT_DIR = "output_videos"

print("=" * 60)
print("混剪模式快速测试")
print("=" * 60)

# 步骤1：扫描素材
print("\n[1/3] 扫描素材...")
fetcher = MaterialFetcher()
fetch_result = fetcher.fetch(base_path=BASE_PATH, client_name=CLIENT_NAME)
print(f"✓ 扫描完成：共 {len(fetch_result.materials)} 个素材")

# 步骤2：组装片段
print("\n[2/3] 组装视频片段...")
engine = AssemblyEngine(random_seed=0)
plan = engine.assemble(
    base_path=BASE_PATH,
    client_name=CLIENT_NAME,
    audio_duration_seconds=TARGET_DURATION,
    materials=fetch_result.materials
)
print(f"✓ 组装完成：共 {len(plan.clips)} 个片段")

# 步骤3：导出MP4
print("\n[3/3] 导出 MP4 视频...")
exporter = VideoExporter(output_dir=OUTPUT_DIR)
result = exporter.export(assembly_plan=plan, video_index=1)

print("\n" + "=" * 60)
print("✅ 测试完成！")
print("=" * 60)
print(f"输出路径: {result.output_path}")
print(f"视频时长: {result.duration_seconds:.1f} 秒")
print(f"片段数量: {result.clip_count}")
print("\n请用播放器打开视频检查效果。")
