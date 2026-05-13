#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试控制台日志输出"""

import logging
import sys
import time

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

print("=" * 60)
print("控制台日志输出测试")
print("=" * 60)
print()

logger.info("测试开始...")
time.sleep(0.5)

logger.info("[MaterialFetcher] 开始扫描客户素材: client=测试客户")
time.sleep(0.5)

logger.info("[MaterialFetcher] 发现 mp4 素材: category=panorama count=15")
time.sleep(0.5)

logger.info("[MaterialFetcher] 发现 mp4 素材: category=machine count=25")
time.sleep(0.5)

logger.info("[MaterialFetcher] 发现 mp4 素材: category=shipping count=10")
time.sleep(0.5)

logger.info("[MaterialFetcher] 扫描完成: total_videos=50")
time.sleep(0.5)

logger.info("[Assembly] 开始组装片段: audio_duration=30.0s")
time.sleep(0.5)

logger.info("[Assembly] 片段分配: category=panorama duration=6.0s")
time.sleep(0.5)

logger.info("[Assembly] 片段分配: category=machine duration=18.0s")
time.sleep(0.5)

logger.info("[Assembly] 片段分配: category=shipping duration=6.0s")
time.sleep(0.5)

logger.info("[Assembly] 组装完成: clips=12 total_allocated=30.5s")
time.sleep(0.5)

logger.info("[VideoExporter] 开始导出视频: clips=12")
time.sleep(1)

logger.info("[VideoExporter] 加载片段: file=factory_01.mp4 start=1.0 end=4.0")
time.sleep(0.3)

logger.info("[VideoExporter] 加载片段: file=machine_05.mp4 start=2.0 end=5.5")
time.sleep(0.3)

logger.info("[VideoExporter] 开始拼接 12 个片段...")
time.sleep(1)

logger.info("[VideoExporter] 开始写入视频文件...")
time.sleep(2)

logger.info("[VideoExporter] 视频导出完成: duration=30.5s")
time.sleep(0.5)

logger.info("✓ 测试完成！")
print()
print("=" * 60)
print("如果你能看到上面的日志输出，说明控制台配置正确")
print("=" * 60)
print()
input("按回车键退出...")
