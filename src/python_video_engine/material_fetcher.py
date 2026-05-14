from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import shutil
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from moviepy.editor import VideoFileClip
from .ffmpeg_runtime import get_ffprobe_path

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
BACKGROUND_RETRY_TIMEOUT_SECONDS = 8.0
PROBE_CACHE_FILE = ".python_video_engine_probe_cache.json"
BAD_MATERIALS_FILE = ".python_video_engine_bad_materials.json"
BLACKLIST_REASONS = {"timeout_error", "nal_error", "aac_decode_error"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
CACHE_ROOT_DIR = Path(os.path.expanduser('~/.jianying_auto_editor_cache'))
CACHE_ROOT_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("python_video_engine.material_fetcher")


def _subprocess_no_window_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


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


def _cache_state_paths(base_path: Path) -> tuple[Path, Path]:
    key = hashlib.sha1(str(base_path).encode("utf-8", errors="ignore")).hexdigest()[:12]
    base_name = base_path.name.strip() or "materials"
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in base_name)
    bucket = CACHE_ROOT_DIR / f"{safe_name}_{key}"
    bucket.mkdir(parents=True, exist_ok=True)
    return bucket / BAD_MATERIALS_FILE, bucket / PROBE_CACHE_FILE


class MaterialFetcher:
    def __init__(self, progress_callback: Callable[[int, int, str], None] | None = None) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self._progress_callback = progress_callback
        self._scan_total = 0
        self._scan_done = 0
        self._bad_materials: dict[str, dict[str, str | int]] = {}
        self._bad_state_path: Path | None = None
        self._probe_cache: dict[str, dict[str, int | float | str]] = {}
        self._probe_cache_path: Path | None = None
        self._probe_cache_dirty_count = 0

    def fetch(self, base_path: str | Path, client_name: str) -> MaterialFetchResult:
        resolved_base_path = Path(os.path.normpath(str(base_path).strip())).expanduser().resolve(strict=False)
        logger.info("[MaterialFetcher] 开始扫描客户素材: client=%s path=%s", client_name, resolved_base_path)
        self._bad_state_path, self._probe_cache_path = _cache_state_paths(resolved_base_path)
        self._bad_materials = self._load_bad_materials(self._bad_state_path)
        self._probe_cache = self._load_probe_cache(self._probe_cache_path)

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
            logger.info("[MaterialFetcher] 检测到单目录素材模式，按统一素材池扫描支持格式视频")
            all_files = self._collect_mp4_files_recursive(resolved_base_path)
            self._prepare_scan_progress(all_files)
            pool_materials = self._scan_single_pool(folder_path=resolved_base_path)
            materials.extend(pool_materials)
            counts_by_category[FALLBACK_CATEGORY] = len(pool_materials)

        self._save_bad_materials(self._bad_state_path, self._bad_materials)
        self._save_probe_cache(self._probe_cache_path)
        logger.info("[MaterialFetcher] 扫描完成: keywords=%s total_videos=%s", len(keywords), len(materials))

        return MaterialFetchResult(client_name=client_name, base_path=str(resolved_base_path), keywords=keywords, materials=materials, counts_by_category=counts_by_category)

    def fetch_ready_then_background(self, base_path: str | Path, client_name: str, min_ready_materials: int = 1) -> MaterialFetchResult:
        resolved_base_path = Path(os.path.normpath(str(base_path).strip())).expanduser().resolve(strict=False)
        logger.info("[MaterialFetcher] 启动快速扫描: client=%s path=%s min_ready=%s", client_name, resolved_base_path, min_ready_materials)
        self._bad_state_path, self._probe_cache_path = _cache_state_paths(resolved_base_path)
        self._bad_materials = self._load_bad_materials(self._bad_state_path)
        self._probe_cache = self._load_probe_cache(self._probe_cache_path)

        keywords = self._load_keywords(resolved_base_path)
        candidates = self._collect_candidates(resolved_base_path)
        self._prepare_scan_progress([p for _, p in candidates])

        counts_by_category: dict[str, int] = {key: 0 for key in MATERIAL_CATEGORIES}
        ready_materials: list[MaterialFileMeta] = []
        delayed_queue: list[tuple[str, Path]] = []
        ready_target = max(1, int(min_ready_materials))

        for category, file_path in candidates:
            meta, is_timeout = self._extract_fast_metadata(category, file_path)
            if meta is not None:
                ready_materials.append(meta)
                counts_by_category[category] = counts_by_category.get(category, 0) + 1
            elif is_timeout:
                delayed_queue.append((category, file_path))
            if len(ready_materials) >= ready_target:
                break

        scanned_count = self._scan_done
        remaining_candidates = candidates[scanned_count:]
        logger.info("[MaterialFetcher] 快速扫描完成: ready=%s scanned=%s total=%s delayed=%s", len(ready_materials), scanned_count, len(candidates), len(delayed_queue))

        threading.Thread(target=self._background_scan_worker, args=(remaining_candidates, delayed_queue), daemon=True).start()

        return MaterialFetchResult(client_name=client_name, base_path=str(resolved_base_path), keywords=keywords, materials=ready_materials, counts_by_category=counts_by_category)

    def _background_scan_worker(self, remaining_candidates: list[tuple[str, Path]], delayed_queue: list[tuple[str, Path]]) -> None:
        if not remaining_candidates and not delayed_queue:
            return
        logger.info("[MaterialFetcher] 后台扫描开始: remaining=%s delayed=%s", len(remaining_candidates), len(delayed_queue))

        for category, file_path in remaining_candidates:
            self._extract_video_metadata(category=category, file_path=file_path)

        for _, file_path in delayed_queue:
            self._retry_timeout_probe(file_path)

        self._save_bad_materials(self._bad_state_path, self._bad_materials)
        self._save_probe_cache(self._probe_cache_path)
        logger.info("[MaterialFetcher] 后台扫描结束")

    def _retry_timeout_probe(self, file_path: Path) -> None:
        self._notify_scan_progress(file_path.name)
        absolute_path = str(file_path.resolve(strict=False))
        bad_record = self._bad_materials.get(absolute_path, {})
        bad_reason = str(bad_record.get("reason", "")).strip().lower()
        if bad_reason in BLACKLIST_REASONS:
            return

        probe_meta = self._probe_with_ffprobe(file_path, timeout_seconds=BACKGROUND_RETRY_TIMEOUT_SECONDS, mark_timeout_bad=True)
        if probe_meta is not None:
            return

        self._mark_bad_material(file_path, reason="ffprobe_timeout", detail=f"retry_timeout={BACKGROUND_RETRY_TIMEOUT_SECONDS}")

    def _collect_candidates(self, base_path: Path) -> list[tuple[str, Path]]:
        has_all_category_dirs = all((base_path / folder_name).is_dir() for folder_name in MATERIAL_CATEGORIES.values())
        candidates: list[tuple[str, Path]] = []
        if has_all_category_dirs:
            for category, folder_name in MATERIAL_CATEGORIES.items():
                files = self._collect_mp4_files_in_dir(base_path / folder_name)
                random.shuffle(files)
                candidates.extend((category, p) for p in files)
        else:
            logger.info("[MaterialFetcher] 检测到单目录素材模式，按统一素材池扫描支持格式视频")
            files = self._collect_mp4_files_recursive(base_path)
            random.shuffle(files)
            candidates.extend((FALLBACK_CATEGORY, p) for p in files)
        return candidates

    def _extract_fast_metadata(self, category: str, file_path: Path) -> tuple[MaterialFileMeta | None, bool]:
        self._notify_scan_progress(file_path.name)
        absolute_path = str(file_path.resolve(strict=False))

        bad_record = self._bad_materials.get(absolute_path, {})
        bad_reason = str(bad_record.get("reason", "")).strip().lower()
        if bad_reason in BLACKLIST_REASONS:
            return None, False

        cached = self._read_probe_cache(file_path)
        if cached is not None:
            duration_seconds, width, height = cached
            return MaterialFileMeta(category=category, folder_name=file_path.parent.name, file_name=file_path.name, absolute_path=absolute_path, duration_seconds=duration_seconds, width=width, height=height), False

        probe_meta = self._probe_with_ffprobe(file_path, timeout_seconds=PROBE_TIMEOUT_SECONDS, mark_timeout_bad=False)
        if probe_meta is None:
            return None, True

        duration_seconds, width, height, fps = probe_meta
        self._write_probe_cache(file_path=file_path, duration_seconds=duration_seconds, width=width, height=height, fps=fps)
        return MaterialFileMeta(category=category, folder_name=file_path.parent.name, file_name=file_path.name, absolute_path=absolute_path, duration_seconds=duration_seconds, width=width, height=height), False

    def _build_cache_key(self, file_path: Path) -> str:
        stat = file_path.stat()
        return f"{str(file_path.resolve(strict=False))}|{int(stat.st_size)}|{int(stat.st_mtime)}"

    def _read_probe_cache(self, file_path: Path) -> tuple[float, int, int] | None:
        try:
            key = self._build_cache_key(file_path)
            record = self._probe_cache.get(key)
            if not isinstance(record, dict):
                return None
            duration_seconds = round(float(record.get("duration_seconds", 0.0) or 0.0), 3)
            width = int(float(record.get("width", 0) or 0))
            height = int(float(record.get("height", 0) or 0))
            if duration_seconds <= 0:
                return None
            return duration_seconds, width, height
        except Exception:
            return None

    def _write_probe_cache(self, file_path: Path, duration_seconds: float, width: int, height: int, fps: float) -> None:
        try:
            key = self._build_cache_key(file_path)
            self._probe_cache[key] = {
                "duration_seconds": round(float(duration_seconds or 0.0), 3),
                "width": int(width or 0),
                "height": int(height or 0),
                "fps": round(float(fps or 0.0), 3),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            }
        except Exception:
            return

    def _load_probe_cache(self, state_path: Path | None) -> dict[str, dict[str, int | float | str]]:
        if state_path is None or not state_path.exists():
            return {}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_probe_cache(self, state_path: Path | None) -> None:
        if state_path is None:
            return
        try:
            state_path.write_text(json.dumps(self._probe_cache, ensure_ascii=False, indent=2), encoding="utf-8")
            self._hide_file_if_windows(state_path)
        except Exception as exc:
            logger.warning("[MaterialFetcher] 保存探测缓存失败: %s", exc)

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
        return [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTS] if folder_path.exists() and folder_path.is_dir() else []

    def _collect_mp4_files_recursive(self, folder_path: Path) -> list[Path]:
        if not folder_path.exists() or not folder_path.is_dir():
            return []
        return [p for p in folder_path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTS and IGNORED_FOLDER_NAME not in p.parts]

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
            duration_seconds, width, height, fps = probe_meta
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
            logger.warning("[扫描跳过] 文件: %s, 原因: %s\n%s", file_path, err, traceback.format_exc())
            self._mark_bad_material(file_path, reason="metadata_failed", detail=str(err))
            return None
        finally:
            if clip is not None:
                clip.close()

    def _probe_with_ffprobe(self, file_path: Path, timeout_seconds: float = PROBE_TIMEOUT_SECONDS, mark_timeout_bad: bool = True) -> tuple[float, int, int, float] | None:
        ffprobe = get_ffprobe_path()
        if not ffprobe:
            logger.error("[ERROR] ffprobe 未找到: path=%s file=%s", ffprobe, file_path)
            return None

        cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,duration,r_frame_rate", "-of", "json", str(file_path)]
        last_err: Exception | None = None
        for retry_count in range(1, 4):
            try:
                completed = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                    **_subprocess_no_window_kwargs(),
                )
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
                fps = self._parse_fps(str(stream.get("r_frame_rate", "0/1") or "0/1"))
                return duration_seconds, width, height, fps
            except Exception as err:
                last_err = err
                if retry_count < 3:
                    logger.warning("[网络抖动] 读取失败，等待 1 秒后重试... (%s/3): %s", retry_count, file_path, exc_info=True)
                    time.sleep(1)
                    continue
                if isinstance(err, subprocess.CalledProcessError):
                    stderr = (err.stderr or "").strip()
                    logger.error("[素材扫描失败] ffprobe 失败(已重试3次): path=%s returncode=%s stderr=%s", file_path, err.returncode, stderr, exc_info=True)
                else:
                    logger.error("[素材扫描失败] ffprobe 失败(已重试3次): path=%s err=%s", file_path, err, exc_info=True)
                if mark_timeout_bad and isinstance(err, subprocess.TimeoutExpired):
                    self._mark_bad_material(file_path, reason="ffprobe_timeout", detail=f"timeout={timeout_seconds}")
                logger.warning("[MaterialFetcher] 单条视频扫描失败并跳过: file=%s", file_path, exc_info=True)
                return None

        logger.error("[ERROR] ffprobe 执行失败，已重试 3 次: ffprobe=%s file=%s err=%s", ffprobe, file_path, last_err)
        return None

    def _parse_fps(self, raw_rate: str) -> float:
        try:
            value = str(raw_rate or "0/1").strip()
            if "/" in value:
                a, b = value.split("/", 1)
                num = float(a or 0.0)
                den = float(b or 1.0)
                if den == 0:
                    return 0.0
                return round(num / den, 3)
            return round(float(value), 3)
        except Exception:
            return 0.0
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

