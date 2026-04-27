from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from moviepy.editor import VideoFileClip

DEFAULT_FACTORY_KEYWORDS = [
    "factory direct",
    "industrial manufacturing",
    "OEM ODM service",
    "strict quality control",
    "stable production capacity",
    "fast delivery",
    "export experience",
    "custom processing",
]

MATERIAL_CATEGORIES = {
    "panorama": "01_工厂全景与大环境",
    "machine": "02_机器运转与加工细节",
    "shipping": "03_成品展示与发货",
}

IGNORED_FOLDER_NAME = "04_人物实拍（老板&工人）"

logger = logging.getLogger("python_video_engine.material_fetcher")


@dataclass(slots=True)
class MaterialFileMeta:
    category: str
    folder_name: str
    file_name: str
    absolute_path: str
    duration_seconds: float
    width: int
    height: int


@dataclass(slots=True)
class MaterialFetchResult:
    client_name: str
    base_path: str
    keywords: list[str]
    materials: list[MaterialFileMeta]
    counts_by_category: dict[str, int]


class MaterialFetcher:
    def __init__(self) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")

    def fetch(self, base_path: str | Path, client_name: str) -> MaterialFetchResult:
        resolved_base_path = Path(base_path).expanduser().resolve(strict=False)
        logger.info("[MaterialFetcher] 开始扫描客户素材: client=%s path=%s", client_name, resolved_base_path)

        keywords = self._load_keywords(resolved_base_path)
        materials: list[MaterialFileMeta] = []
        counts_by_category: dict[str, int] = {key: 0 for key in MATERIAL_CATEGORIES}

        ignored_folder_path = resolved_base_path / IGNORED_FOLDER_NAME
        if ignored_folder_path.exists():
            logger.info("[MaterialFetcher] 主动忽略人物文件夹: %s", ignored_folder_path)

        for category, folder_name in MATERIAL_CATEGORIES.items():
            folder_path = resolved_base_path / folder_name
            category_materials = self._scan_category(category=category, folder_path=folder_path)
            materials.extend(category_materials)
            counts_by_category[category] = len(category_materials)
            logger.info(
                "[MaterialFetcher] 分类扫描完成: category=%s folder=%s count=%s",
                category,
                folder_name,
                len(category_materials),
            )

        logger.info(
            "[MaterialFetcher] 扫描完成: keywords=%s total_videos=%s",
            len(keywords),
            len(materials),
        )

        return MaterialFetchResult(
            client_name=client_name,
            base_path=str(resolved_base_path),
            keywords=keywords,
            materials=materials,
            counts_by_category=counts_by_category,
        )

    def _load_keywords(self, base_path: Path) -> list[str]:
        keyword_file = next((base_path / name for name in ["keywords.txt", "keywords"] if (base_path / name).exists()), None)
        if keyword_file is None:
            logger.info("[MaterialFetcher] 未找到关键词文件，使用默认工厂关键词")
            return DEFAULT_FACTORY_KEYWORDS.copy()

        raw_text = keyword_file.read_text(encoding="utf-8").strip()
        if not raw_text:
            logger.info("[MaterialFetcher] 关键词文件为空，使用默认工厂关键词")
            return DEFAULT_FACTORY_KEYWORDS.copy()

        keywords = self._parse_keywords(raw_text)
        if not keywords:
            logger.info("[MaterialFetcher] 未解析出有效关键词，使用默认工厂关键词")
            return DEFAULT_FACTORY_KEYWORDS.copy()

        logger.info("[MaterialFetcher] 已加载关键词: count=%s file=%s", len(keywords), keyword_file)
        return keywords

    def _parse_keywords(self, raw_text: str) -> list[str]:
        ignored_prefixes = ("一、", "二、", "三、", "四、", "脚本关键词", "您可以", "开头", "中段", "结尾")
        results: list[str] = []
        for raw_line in raw_text.splitlines():
            line = raw_line.strip().strip("-•·")
            if not line or line.startswith(ignored_prefixes) or "例如" in line:
                continue
            normalized = line.replace("：", "-")
            parts = [part.strip() for part in normalized.split("-") if part.strip()]
            if len(parts) >= 2 and len(parts[0]) <= 12:
                candidate = f"{parts[0]} {parts[1]}"
            else:
                candidate = line
            if candidate not in results:
                results.append(candidate)
        return results

    def _scan_category(self, category: str, folder_path: Path) -> list[MaterialFileMeta]:
        if not folder_path.exists():
            logger.info("[MaterialFetcher] 目标目录不存在，跳过: category=%s path=%s", category, folder_path)
            return []

        if not folder_path.is_dir():
            logger.info("[MaterialFetcher] 目标路径不是目录，跳过: category=%s path=%s", category, folder_path)
            return []

        mp4_files = [path for path in folder_path.iterdir() if path.is_file() and path.suffix.lower() == ".mp4"]
        random.shuffle(mp4_files)
        if not mp4_files:
            logger.info("[MaterialFetcher] 目录中无 mp4 素材: category=%s path=%s", category, folder_path)
            return []

        logger.info("[MaterialFetcher] 发现 mp4 素材: category=%s count=%s", category, len(mp4_files))
        return [self._extract_video_metadata(category=category, file_path=file_path) for file_path in mp4_files]

    def _extract_video_metadata(self, category: str, file_path: Path) -> MaterialFileMeta:
        logger.info("[MaterialFetcher] 提取视频元数据: %s", file_path)
        clip: VideoFileClip | None = None
        try:
            clip = VideoFileClip(str(file_path))
            width, height = self._safe_resolution(clip.size)
            duration_seconds = round(float(clip.duration or 0.0), 3)
            return MaterialFileMeta(
                category=category,
                folder_name=file_path.parent.name,
                file_name=file_path.name,
                absolute_path=str(file_path.resolve(strict=False)),
                duration_seconds=duration_seconds,
                width=width,
                height=height,
            )
        except Exception as err:
            logger.error("[MaterialFetcher] 视频元数据提取失败: file=%s err=%s", file_path, err)
            return MaterialFileMeta(
                category=category,
                folder_name=file_path.parent.name,
                file_name=file_path.name,
                absolute_path=str(file_path.resolve(strict=False)),
                duration_seconds=0.0,
                width=0,
                height=0,
            )
        finally:
            if clip is not None:
                clip.close()

    def _safe_resolution(self, size: Iterable[int | float] | None) -> tuple[int, int]:
        if not size:
            return 0, 0

        values = list(size)
        if len(values) < 2:
            return 0, 0

        width = int(values[0]) if values[0] else 0
        height = int(values[1]) if values[1] else 0
        return width, height
