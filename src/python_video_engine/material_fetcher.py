from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

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
MATERIAL_CATEGORIES = {"panorama": "01_工厂全景与大环境", "machine": "02_机器运转与加工细节", "shipping": "03_成品展示与发货"}
IGNORED_FOLDER_NAME = "04_人物实拍（老板&工人）"
FALLBACK_CATEGORY = "machine"
PROBE_TIMEOUT_SECONDS = 5.0
BAD_MATERIALS_FILE = ".python_video_engine_bad_materials.json"
BLACKLIST_REASONS = {"timeout_error", "nal_error", "aac_decode_error"}
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
    def __init__(self, progress_callback: Callable[[int, int, str], None] | None = None) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self._progress_callback = progress_callback
        self._scan_total = 0
        self._scan_done = 0
        self._bad_materials: dict[str, dict[str, str | int]] = {}
        self._bad_state_path: Path | None = None

    def fetch(self, base_path: str | Path, client_name: str) -> MaterialFetchResult:
        resolved_base_path = Path(base_path).expanduser().resolve(strict=False)
        logger.info("[MaterialFetcher] 开始扫描客户素材: client=%s path=%s", client_name, resolved_base_path)
        self._bad_state_path = resolved_base_path / BAD_MATERIALS_FILE
        self._bad_materials = self._load_bad_materials(self._bad_state_path)

        keywords = self._load_keywords(resolved_base_path)
        materials: list[MaterialFileMeta] = []
        counts_by_category: dict[str, int] = {key: 0 for key in MATERIAL_CATEGORIES}

        has_all_category_dirs = all((resolved_base_path / folder_name).is_dir() for folder_name in MATERIAL_CATEGORIES.values())
        if has_all_category_dirs:
            all_files: list[Path] = []
            for folder_name in MATERIAL_CATEGORIES.values():
                all_files.extend(self._collect_mp4_files_in_dir(resolved_base_path / folder_name))
            self._prepare_scan_progress(all_files)
            for category, folder_name in MATERIAL_CATEGORIES.items():
                category_materials = self._scan_category(category=category, folder_path=resolved_base_path / folder_name)
                materials.extend(category_materials)
                counts_by_category[category] = len(category_materials)
        else:
            logger.info("[MaterialFetcher] 检测到单目录素材模式，按统一素材池扫描 mp4")
            all_files = self._collect_mp4_files_recursive(resolved_base_path)
            self._prepare_scan_progress(all_files)
            pool_materials = self._scan_single_pool(folder_path=resolved_base_path)
            materials.extend(pool_materials)
            counts_by_category[FALLBACK_CATEGORY] = len(pool_materials)

        self._save_bad_materials(self._bad_state_path, self._bad_materials)
        logger.info("[MaterialFetcher] 扫描完成: keywords=%s total_videos=%s", len(keywords), len(materials))

        return MaterialFetchResult(client_name=client_name, base_path=str(resolved_base_path), keywords=keywords, materials=materials, counts_by_category=counts_by_category)

    def _load_keywords(self, base_path: Path) -> list[str]:
        keyword_file = next((base_path / name for name in ["keywords.txt", "keywords"] if (base_path / name).exists()), None)
        if keyword_file is None:
            return DEFAULT_FACTORY_KEYWORDS.copy()
        raw_text = keyword_file.read_text(encoding="utf-8").strip()
        if not raw_text:
            return DEFAULT_FACTORY_KEYWORDS.copy()
        keywords = self._parse_keywords(raw_text)
        return keywords or DEFAULT_FACTORY_KEYWORDS.copy()

    def _parse_keywords(self, raw_text: str) -> list[str]:
        ignored_prefixes = ("一、", "二、", "三、", "四、", "脚本关键词", "您可以", "开头", "中段", "结尾")
        results: list[str] = []
        for raw_line in raw_text.splitlines():
            line = raw_line.strip().strip("-•·")
            if not line or line.startswith(ignored_prefixes) or "例如" in line:
                continue
            normalized = line.replace("：", "-")
            parts = [part.strip() for part in normalized.split("-") if part.strip()]
            candidate = f"{parts[0]} {parts[1]}" if len(parts) >= 2 and len(parts[0]) <= 12 else line
            if candidate not in results:
                results.append(candidate)
        return results

    def _scan_category(self, category: str, folder_path: Path) -> list[MaterialFileMeta]:
        if not folder_path.exists() or not folder_path.is_dir():
            return []
        files = self._collect_mp4_files_in_dir(folder_path)
        random.shuffle(files)
        result: list[MaterialFileMeta] = []
        for file_path in files:
            meta = self._extract_video_metadata(category=category, file_path=file_path)
            if meta is not None:
                result.append(meta)
        return result

    def _scan_single_pool(self, folder_path: Path) -> list[MaterialFileMeta]:
        if not folder_path.exists() or not folder_path.is_dir():
            return []
        files = self._collect_mp4_files_recursive(folder_path)
        random.shuffle(files)
        result: list[MaterialFileMeta] = []
        for file_path in files:
            meta = self._extract_video_metadata(category=FALLBACK_CATEGORY, file_path=file_path)
            if meta is not None:
                result.append(meta)
        return result

    def _collect_mp4_files_in_dir(self, folder_path: Path) -> list[Path]:
        return [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"] if folder_path.exists() and folder_path.is_dir() else []

    def _collect_mp4_files_recursive(self, folder_path: Path) -> list[Path]:
        if not folder_path.exists() or not folder_path.is_dir():
            return []
        return [p for p in folder_path.rglob("*") if p.is_file() and p.suffix.lower() == ".mp4" and IGNORED_FOLDER_NAME not in p.parts]

    def _prepare_scan_progress(self, files: list[Path]) -> None:
        self._scan_total = len(files)
        self._scan_done = 0
        if self._progress_callback and self._scan_total > 0:
            self._progress_callback(self._scan_done, self._scan_total, "准备扫描素材")

    def _notify_scan_progress(self, file_name: str) -> None:
        self._scan_done += 1
        if self._progress_callback and self._scan_total > 0:
            self._progress_callback(self._scan_done, self._scan_total, file_name)

    def _extract_video_metadata(self, category: str, file_path: Path) -> MaterialFileMeta | None:
        self._notify_scan_progress(file_path.name)
        absolute_path = str(file_path.resolve(strict=False))

        bad_record = self._bad_materials.get(absolute_path, {})
        bad_reason = str(bad_record.get("reason", "")).strip().lower()
        if bad_reason in BLACKLIST_REASONS:
            logger.warning("[MaterialFetcher] 命中坏素材黑名单，已剔除: file=%s reason=%s", file_path.name, bad_reason)
            return None

        probe_meta = self._probe_with_ffprobe(file_path)
        if probe_meta is not None:
            duration_seconds, width, height = probe_meta
            return MaterialFileMeta(category=category, folder_name=file_path.parent.name, file_name=file_path.name, absolute_path=absolute_path, duration_seconds=duration_seconds, width=width, height=height)

        clip: VideoFileClip | None = None
        try:
            clip = VideoFileClip(str(file_path))
            width, height = self._safe_resolution(clip.size)
            duration_seconds = round(float(clip.duration or 0.0), 3)
            if duration_seconds <= 0:
                raise ValueError("invalid duration")
            return MaterialFileMeta(category=category, folder_name=file_path.parent.name, file_name=file_path.name, absolute_path=absolute_path, duration_seconds=duration_seconds, width=width, height=height)
        except Exception as err:
            logger.error("[MaterialFetcher] 视频元数据提取失败，已跳过: file=%s err=%s", file_path, err)
            self._mark_bad_material(file_path, reason="metadata_failed", detail=str(err))
            return None
        finally:
            if clip is not None:
                clip.close()

    def _probe_with_ffprobe(self, file_path: Path) -> tuple[float, int, int] | None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration", "-of", "json", str(file_path)]
        try:
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, encoding="utf-8", errors="replace")
            payload = json.loads(completed.stdout or "{}")
            streams = payload.get("streams", []) if isinstance(payload, dict) else []
            if not streams:
                raise ValueError("no video streams")
            stream = streams[0] if isinstance(streams[0], dict) else {}
            width = int(float(stream.get("width", 0) or 0))
            height = int(float(stream.get("height", 0) or 0))
            duration_seconds = round(float(stream.get("duration", 0.0) or 0.0), 3)
            if duration_seconds <= 0:
                raise ValueError("duration is zero")
            return duration_seconds, width, height
        except subprocess.TimeoutExpired:
            logger.error("[MaterialFetcher] ffprobe 超时，已跳过: file=%s timeout=%.1fs", file_path, PROBE_TIMEOUT_SECONDS)
            self._mark_bad_material(file_path, reason="ffprobe_timeout", detail=f"timeout={PROBE_TIMEOUT_SECONDS}")
            return None
        except Exception as err:
            logger.warning("[MaterialFetcher] ffprobe 失败，将尝试 moviepy: file=%s err=%s", file_path, err)
            return None

    def _mark_bad_material(self, file_path: Path, reason: str, detail: str) -> None:
        key = str(file_path.resolve(strict=False))
        now = datetime.now().isoformat(timespec="seconds")
        prev = self._bad_materials.get(key, {})
        self._bad_materials[key] = {
            "reason": reason,
            "detail": detail[:500],
            "first_seen": str(prev.get("first_seen", now)),
            "last_seen": now,
            "failures": int(prev.get("failures", 0) or 0) + 1,
        }

    def _load_bad_materials(self, state_path: Path) -> dict[str, dict[str, str | int]]:
        if not state_path.exists():
            return {}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_bad_materials(self, state_path: Path | None, data: dict[str, dict[str, str | int]]) -> None:
        if state_path is None:
            return
        try:
            state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self._hide_file_if_windows(state_path)
        except Exception as exc:
            logger.warning("[MaterialFetcher] 保存坏素材状态失败: %s", exc)

    def _hide_file_if_windows(self, path: Path) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return
            hidden_attr = 0x2
            if attrs & hidden_attr:
                return
            ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs | hidden_attr)
        except Exception:
            pass

    def _safe_resolution(self, size: Iterable[int | float] | None) -> tuple[int, int]:
        if not size:
            return 0, 0
        values = list(size)
        if len(values) < 2:
            return 0, 0
        return int(values[0]) if values[0] else 0, int(values[1]) if values[1] else 0
