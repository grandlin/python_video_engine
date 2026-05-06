from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path

from .material_fetcher import MaterialFileMeta

logger = logging.getLogger("python_video_engine.assembly_engine")

CATEGORY_TARGET_RATIOS = {"panorama": 0.2, "machine": 0.6, "shipping": 0.2}
FALLBACK_CATEGORY = "machine"
MIN_CLIP_SECONDS = 3.0
MAX_CLIP_SECONDS = 4.0
AVOID_HEAD_SECONDS = 1.0
TAIL_SAFETY_SECONDS = 0.8
USAGE_STATE_FILE = ".python_video_engine_material_usage.json"
MAX_OVERLAP_RATIO = 0.30
OVERLAP_ENFORCE_MIN_POOL = 10


@dataclass(slots=True)
class AssemblyClip:
    order_index: int
    source_category: str
    allocated_category: str
    file_name: str
    absolute_path: str
    clip_start_seconds: float
    clip_end_seconds: float
    clip_duration_seconds: float


@dataclass(slots=True)
class AssemblyPlan:
    client_name: str
    base_path: str
    total_audio_duration_seconds: float
    target_seconds_by_category: dict[str, float]
    fulfilled_seconds_by_category: dict[str, float]
    borrowed_seconds_by_category: dict[str, float]
    clips: list[AssemblyClip]


class AssemblyEngine:
    def __init__(self, random_seed: int | None = None) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self._random = random.Random(random_seed)
        self._remaining_by_source: dict[str, list[MaterialFileMeta]] = {}
        self._used_by_source: dict[str, set[str]] = {}
        self._usage_counts: dict[str, int] = {}
        self._last_video_paths: set[str] = set()
        self._last_start_by_file: dict[str, float] = {}
        self._video_unique_paths: set[str] = set()
        self._video_overlap_paths: set[str] = set()

    def assemble(self, base_path: str | Path, client_name: str, audio_duration_seconds: float, materials: list[MaterialFileMeta]) -> AssemblyPlan:
        resolved_base_path = Path(base_path).expanduser().resolve(strict=False)
        self._load_usage_state(self._usage_state_path(resolved_base_path))
        total_audio_duration_seconds = round(max(audio_duration_seconds, 0.0), 3)
        logger.info("[Assembly] 开始组装片段: client=%s audio_duration=%.3fs", client_name, total_audio_duration_seconds)

        materials_by_category = self._group_materials_by_category(materials)
        self._remaining_by_source = {k: [] for k in CATEGORY_TARGET_RATIOS}
        self._used_by_source = {k: set() for k in CATEGORY_TARGET_RATIOS}
        self._video_unique_paths = set()
        self._video_overlap_paths = set()

        target_seconds_by_category = self._build_targets(total_audio_duration_seconds)
        fulfilled_seconds_by_category = {k: 0.0 for k in CATEGORY_TARGET_RATIOS}
        borrowed_seconds_by_category = {k: 0.0 for k in CATEGORY_TARGET_RATIOS}
        clips: list[AssemblyClip] = []

        for category in ["panorama", "machine", "shipping"]:
            target_seconds = target_seconds_by_category[category]
            logger.info("[Assembly] 分类目标时长: category=%s target=%.3fs", category, target_seconds)
            generated, fulfilled, borrowed = self._allocate_for_category(
                requested_category=category,
                target_seconds=target_seconds,
                materials_by_category=materials_by_category,
                order_start=len(clips),
            )
            clips.extend(generated)
            fulfilled_seconds_by_category[category] = round(fulfilled, 3)
            borrowed_seconds_by_category[category] = round(borrowed, 3)

        required_video_total = round(total_audio_duration_seconds + TAIL_SAFETY_SECONDS, 3)
        actual_total = round(sum(x.clip_duration_seconds for x in clips), 3)

        if actual_total < required_video_total:
            gap = round(required_video_total - actual_total, 3)
            logger.info("[Assembly] 总时长仍有缺口，向 02 借用并末尾补齐: gap=%.3fs", gap)
            extra_clips, extra_seconds, remaining = self._allocate_from_pool(
                source_category=FALLBACK_CATEGORY,
                requested_category=FALLBACK_CATEGORY,
                target_seconds=gap,
                pool=materials_by_category.get(FALLBACK_CATEGORY, []),
                order_start=len(clips),
            )
            clips.extend(extra_clips)
            fulfilled_seconds_by_category[FALLBACK_CATEGORY] = round(fulfilled_seconds_by_category[FALLBACK_CATEGORY] + extra_seconds, 3)
            if remaining > 0 and clips:
                logger.info("[Assembly] 素材不足，使用最后片段循环填充: remaining=%.3fs", remaining)
                clips = self._pad_with_last_clip(clips, remaining)

        actual_total = round(sum(x.clip_duration_seconds for x in clips), 3)
        if actual_total < required_video_total:
            logger.warning("[Assembly] 视频时长仍短于目标（含安全余量）: video=%.3fs required=%.3fs", actual_total, required_video_total)

        logger.info("[Assembly] 组装完成: clips=%s total_allocated=%.3fs", len(clips), actual_total)
        overlap_ratio = self._compute_last_video_overlap_ratio()
        logger.info("[Assembly] 与上一条视频素材重合率: %.1f%%", overlap_ratio * 100.0)
        self._last_video_paths = set(self._video_unique_paths)
        self._save_usage_state(self._usage_state_path(resolved_base_path))
        return AssemblyPlan(
            client_name=client_name,
            base_path=str(resolved_base_path),
            total_audio_duration_seconds=total_audio_duration_seconds,
            target_seconds_by_category=target_seconds_by_category,
            fulfilled_seconds_by_category=fulfilled_seconds_by_category,
            borrowed_seconds_by_category=borrowed_seconds_by_category,
            clips=clips,
        )

    def _allocate_for_category(self, requested_category: str, target_seconds: float, materials_by_category: dict[str, list[MaterialFileMeta]], order_start: int) -> tuple[list[AssemblyClip], float, float]:
        if target_seconds <= 0:
            return [], 0.0, 0.0

        primary_pool = list(materials_by_category.get(requested_category, []))
        if requested_category == FALLBACK_CATEGORY:
            clips, fulfilled, _ = self._allocate_from_pool(FALLBACK_CATEGORY, requested_category, target_seconds, primary_pool, order_start)
            return clips, fulfilled, 0.0

        if not primary_pool:
            logger.info("[Assembly] %s 目录为空，触发兜底，向 02 借用 %.3f 秒素材", requested_category, target_seconds)
            clips, fulfilled, _ = self._allocate_from_pool(FALLBACK_CATEGORY, requested_category, target_seconds, materials_by_category.get(FALLBACK_CATEGORY, []), order_start)
            return clips, fulfilled, fulfilled

        clips, fulfilled, _ = self._allocate_from_pool(requested_category, requested_category, target_seconds, primary_pool, order_start)
        gap = round(max(target_seconds - fulfilled, 0.0), 3)
        borrowed = 0.0
        if gap > 0:
            logger.info("[Assembly] %s 素材时长不足，需向 02 借用 %.3f 秒素材", requested_category, gap)
            more, borrowed, _ = self._allocate_from_pool(FALLBACK_CATEGORY, requested_category, gap, materials_by_category.get(FALLBACK_CATEGORY, []), order_start + len(clips))
            clips.extend(more)
            fulfilled = round(fulfilled + borrowed, 3)
        return clips, fulfilled, borrowed

    def _allocate_from_pool(self, source_category: str, requested_category: str, target_seconds: float, pool: list[MaterialFileMeta], order_start: int) -> tuple[list[AssemblyClip], float, float]:
        if target_seconds <= 0 or not pool:
            if target_seconds > 0 and not pool:
                logger.info("[Assembly] 无可用素材可供分配: source=%s requested=%s", source_category, requested_category)
            return [], 0.0, target_seconds

        remaining = round(target_seconds, 3)
        fulfilled = 0.0
        clips: list[AssemblyClip] = []
        attempts = 0
        max_attempts = max(len(pool) * 4, 10)

        logger.info("[Assembly] 开始碎剪抽取: source=%s requested=%s target=%.3fs pool=%s", source_category, requested_category, target_seconds, len(pool))
        while remaining > 0 and attempts < max_attempts:
            material = self._pick_next_material(source_category, pool)
            if material is None:
                break
            attempts += 1

            desired = self._pick_fragment_duration(remaining, material.duration_seconds)
            clip = self._build_clip(material, requested_category, order_start + len(clips), desired)
            if clip is None:
                continue

            clips.append(clip)
            fulfilled = round(fulfilled + clip.clip_duration_seconds, 3)
            remaining = round(max(target_seconds - fulfilled, 0.0), 3)
            logger.info("[Assembly] 片段分配: requested=%s source=%s file=%s start=%.3f end=%.3f duration=%.3f remaining=%.3f", requested_category, source_category, clip.file_name, clip.clip_start_seconds, clip.clip_end_seconds, clip.clip_duration_seconds, remaining)

        return clips, fulfilled, remaining

    def _pick_next_material(self, source_category: str, pool: list[MaterialFileMeta]) -> MaterialFileMeta | None:
        if not pool:
            return None

        remaining = self._remaining_by_source.setdefault(source_category, [])
        used = self._used_by_source.setdefault(source_category, set())

        if not remaining:
            cycle = [m for m in pool if m.absolute_path not in used]
            if not cycle:
                used.clear()
                cycle = list(pool)

            if cycle:
                min_used = min(self._usage_counts.get(m.absolute_path, 0) for m in cycle)
                low_usage = [m for m in cycle if self._usage_counts.get(m.absolute_path, 0) == min_used]
                other_usage = [m for m in cycle if self._usage_counts.get(m.absolute_path, 0) != min_used]
                self._random.shuffle(low_usage)
                self._random.shuffle(other_usage)
                cycle = low_usage + other_usage

                # 尽量避免每条视频开头重复用上一次视频的素材
                if len(self._video_unique_paths) < 2:
                    non_overlap = [m for m in cycle if m.absolute_path not in self._last_video_paths]
                    overlap = [m for m in cycle if m.absolute_path in self._last_video_paths]
                    if non_overlap:
                        cycle = non_overlap + overlap

            remaining.extend(cycle)

        if not remaining:
            return None

        chosen = remaining.pop(0)
        used.add(chosen.absolute_path)
        return chosen

    def _pad_with_last_clip(self, clips: list[AssemblyClip], pad_seconds: float) -> list[AssemblyClip]:
        remaining = round(max(pad_seconds, 0.0), 3)
        if remaining <= 0 or not clips:
            return clips

        last = clips[-1]
        loop_unit = round(max(last.clip_duration_seconds, 0.1), 3)
        while remaining > 0:
            piece = round(min(loop_unit, remaining), 3)
            clips.append(
                AssemblyClip(
                    order_index=len(clips),
                    source_category=last.source_category,
                    allocated_category=last.allocated_category,
                    file_name=last.file_name,
                    absolute_path=last.absolute_path,
                    clip_start_seconds=last.clip_start_seconds,
                    clip_end_seconds=round(last.clip_start_seconds + piece, 3),
                    clip_duration_seconds=piece,
                )
            )
            remaining = round(max(remaining - piece, 0.0), 3)
        return clips

    def _pick_fragment_duration(self, remaining: float, material_duration: float) -> float:
        safe_remaining = round(max(remaining, 0.0), 3)
        safe_material_duration = round(max(material_duration, 0.0), 3)
        if safe_material_duration <= 0:
            return 0.0
        if safe_material_duration < MIN_CLIP_SECONDS:
            return safe_material_duration
        if safe_remaining <= MAX_CLIP_SECONDS:
            return min(safe_remaining, safe_material_duration)
        random_duration = round(self._random.uniform(MIN_CLIP_SECONDS, MAX_CLIP_SECONDS), 3)
        return min(random_duration, safe_remaining, safe_material_duration)

    def _build_clip(self, material: MaterialFileMeta, requested_category: str, order_index: int, desired_duration: float) -> AssemblyClip | None:
        available_duration = round(max(material.duration_seconds, 0.0), 3)
        if available_duration <= 0 or desired_duration <= 0:
            return None

        if available_duration <= desired_duration:
            clip_start_seconds = 0.0
            clip_end_seconds = available_duration
        else:
            max_start = max(available_duration - desired_duration, 0.0)
            min_start = min(AVOID_HEAD_SECONDS, max_start)
            clip_start_seconds = round(min_start if max_start <= min_start else self._random.uniform(min_start, max_start), 3)
            clip_end_seconds = round(min(clip_start_seconds + desired_duration, available_duration), 3)

        clip_duration_seconds = round(max(clip_end_seconds - clip_start_seconds, 0.0), 3)
        if clip_duration_seconds <= 0:
            return None

        self._usage_counts[material.absolute_path] = self._usage_counts.get(material.absolute_path, 0) + 1
        self._last_start_by_file[material.absolute_path] = clip_start_seconds
        self._video_unique_paths.add(material.absolute_path)
        if material.absolute_path in self._last_video_paths:
            self._video_overlap_paths.add(material.absolute_path)

        return AssemblyClip(
            order_index=order_index,
            source_category=material.category,
            allocated_category=requested_category,
            file_name=material.file_name,
            absolute_path=material.absolute_path,
            clip_start_seconds=clip_start_seconds,
            clip_end_seconds=clip_end_seconds,
            clip_duration_seconds=clip_duration_seconds,
        )

    def _group_materials_by_category(self, materials: list[MaterialFileMeta]) -> dict[str, list[MaterialFileMeta]]:
        grouped = {k: [] for k in CATEGORY_TARGET_RATIOS}
        for item in materials:
            if item.category in grouped:
                grouped[item.category].append(item)
        for category, group in grouped.items():
            total_duration = round(sum(max(item.duration_seconds, 0.0) for item in group), 3)
            logger.info("[Assembly] 素材池统计: category=%s count=%s duration=%.3fs", category, len(group), total_duration)
        return grouped

    def _build_targets(self, total_audio_duration_seconds: float) -> dict[str, float]:
        panorama = round(total_audio_duration_seconds * CATEGORY_TARGET_RATIOS["panorama"], 3)
        machine = round(total_audio_duration_seconds * CATEGORY_TARGET_RATIOS["machine"], 3)
        shipping = round(max(total_audio_duration_seconds - panorama - machine, 0.0), 3)
        return {"panorama": panorama, "machine": machine, "shipping": shipping}

    def _usage_state_path(self, base_path: Path) -> Path:
        return base_path / USAGE_STATE_FILE

    def _load_usage_state(self, state_path: Path) -> None:
        self._usage_counts = {}
        self._last_video_paths = set()
        self._last_start_by_file = {}
        if not state_path.exists():
            return
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[Assembly] 读取素材使用状态失败，忽略并继续: %s", exc)
            return

        raw_counts = payload.get("usage_counts", {}) if isinstance(payload, dict) else {}
        if isinstance(raw_counts, dict):
            for key, value in raw_counts.items():
                try:
                    self._usage_counts[str(key)] = max(int(value), 0)
                except Exception:
                    continue

        raw_last_paths = payload.get("last_video_paths", []) if isinstance(payload, dict) else []
        if isinstance(raw_last_paths, list):
            self._last_video_paths = {str(x) for x in raw_last_paths if str(x).strip()}

        raw_last_start = payload.get("last_start_by_file", {}) if isinstance(payload, dict) else {}
        if isinstance(raw_last_start, dict):
            for key, value in raw_last_start.items():
                try:
                    self._last_start_by_file[str(key)] = float(value)
                except Exception:
                    continue

    def _save_usage_state(self, state_path: Path) -> None:
        payload = {
            "usage_counts": self._usage_counts,
            "last_video_paths": sorted(self._last_video_paths),
            "last_start_by_file": self._last_start_by_file,
        }
        try:
            state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._hide_file_if_windows(state_path)
        except Exception as exc:
            logger.warning("[Assembly] 保存素材使用状态失败: %s", exc)

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

    def _compute_last_video_overlap_ratio(self) -> float:
        current = len(self._video_unique_paths)
        if current <= 0:
            return 0.0
        overlap = len(self._video_overlap_paths)
        return min(max(overlap / current, 0.0), 1.0)
