#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试导入是否正常"""

try:
    from src.python_video_engine import VideoExporter, VideoExportResult
    print("✓ VideoExporter 导入成功")
    print(f"✓ VideoExporter 类: {VideoExporter}")
    print(f"✓ VideoExportResult 类: {VideoExportResult}")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
