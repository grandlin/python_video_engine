from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

from .material_fetcher import MaterialFileMeta

logger = logging.getLogger("python_video_engine.assembly_engine")

CATEGORY_TARGET_RATIOS = {
    "panorama": 0.2,
    "machine": 0.6,
    "shipping": 0.2,
}
FALLBACK_CATEGORY = "machine"
MIN_CLIP_SECONDS = 3.0
MAX_CLIP_SECONDS = 4.0
AVOID_HEAD_SECONDS = 1.0


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

    def assemble(self, base_path: str | Path, client_name: str, audio_duration_seconds: float, materials: list[MaterialFileMeta]) -> AssemblyPlan:
        resolved_base_path = Path(base_path).expanduser().resolve(strict=False)
        total_audio_duration_seconds = round(max(audio_duration_seconds, 0.0), 3)
        logger.info("[Assembly] 开始组装片段: client=%s audio_duration=%.3fs", client_name, total_audio_duration_seconds)

        materials_by_category = self._group_materials_by_category(materials)
        target_seconds_by_category = self._build_targets(total_audio_duration_seconds)
        fulfilled_seconds_by_category = {key: 0.0 for key in CATEGORY_TARGET_RATIOS}
        borrowed_seconds_by_category = {key: 0.0 for key in CATEGORY_TARGET_RATIOS}
        clips: list[AssemblyClip] = []

        for category in ["panorama", "machine", "shipping"]:
            target_seconds = target_seconds_by_category[category]
            logger.info("[Assembly] 分类目标时长: category=%s target=%.3fs", category, target_seconds)
            generated_clips, fulfilled_seconds, borrowed_seconds = self._allocate_for_category(
                requested_category=category,
                target_seconds=target_seconds,
                materials_by_category=materials_by_category,
                order_start=len(clips),
            )
            clips.extend(generated_clips)
            fulfilled_seconds_by_category[category] = round(fulfilled_seconds, 3)
            borrowed_seconds_by_category[category] = round(borrowed_seconds, 3)

        actual_total = round(sum(item.clip_duration_seconds for item in clips), 3)
        if actual_total < total_audio_duration_seconds:
            gap = round(total_audio_duration_seconds - actual_total, 3)
            logger.info("[Assembly] 总时长仍有缺口，继续向 02 借用: gap=%.3fs", gap)
            extra_clips, extra_seconds, _ = self._allocate_from_pool(
                source_category=FALLBACK_CATEGORY,
                requested_category=FALLBACK_CATEGORY,
                target_seconds=gap,
                pool=materials_by_category.get(FALLBACK_CATEGORY, []),
                order_start=len(clips),
            )
            clips.extend(extra_clips)
            fulfilled_seconds_by_category[FALLBACK_CATEGORY] = round(fulfilled_seconds_by_category[FALLBACK_CATEGORY] + extra_seconds, 3)

        logger.info("[Assembly] 组装完成: clips=%s total_allocated=%.3fs", len(clips), sum(item.clip_duration_seconds for item in clips))
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
            clips, fulfilled_seconds, _ = self._allocate_from_pool(FALLBACK_CATEGORY, requested_category, target_seconds, primary_pool, order_start)
            return clips, fulfilled_seconds, 0.0
        if not primary_pool:
            logger.info("[Assembly] %s 目录为空，触发兜底，向 02 借用 %.3f 秒素材", requested_category, target_seconds)
            fallback_clips, fallback_seconds, _ = self._allocate_from_pool(FALLBACK_CATEGORY, requested_category, target_seconds, materials_by_category.get(FALLBACK_CATEGORY, []), order_start)
            return fallback_clips, fallback_seconds, fallback_seconds

        primary_clips, primary_seconds, _ = self._allocate_from_pool(requested_category, requested_category, target_seconds, primary_pool, order_start)
        remaining_gap = round(max(target_seconds - primary_seconds, 0.0), 3)
        borrowed_seconds = 0.0
        if remaining_gap > 0:
            logger.info("[Assembly] %s 素材时长不足，需向 02 借用 %.3f 秒素材", requested_category, remaining_gap)
            fallback_clips, fallback_seconds, _ = self._allocate_from_pool(FALLBACK_CATEGORY, requested_category, remaining_gap, materials_by_category.get(FALLBACK_CATEGORY, []), order_start + len(primary_clips))
            primary_clips.extend(fallback_clips)
            primary_seconds = round(primary_seconds + fallback_seconds, 3)
            borrowed_seconds = fallback_seconds
        return primary_clips, primary_seconds, borrowed_seconds

    def _allocate_from_pool(self, source_category: str, requested_category: str, target_seconds: float, pool: list[MaterialFileMeta], order_start: int) -> tuple[list[AssemblyClip], float, float]:
        if target_seconds <= 0 or not pool:
            if target_seconds > 0 and not pool:
                logger.info("[Assembly] 无可用素材可供分配: source=%s requested=%s", source_category, requested_category)
            return [], 0.0, target_seconds

        remaining = round(target_seconds, 3)
        fulfilled_seconds = 0.0
        clips: list[AssemblyClip] = []
        shuffled_pool = pool.copy()
        self._random.shuffle(shuffled_pool)
        logger.info("[Assembly] 开始碎剪抽取: source=%s requested=%s target=%.3fs pool=%s", source_category, requested_category, target_seconds, len(shuffled_pool))

        while remaining > 0 and shuffled_pool:
            material = shuffled_pool.pop(0)
            desired_duration = self._pick_fragment_duration(remaining=remaining, material_duration=material.duration_seconds)
            clip = self._build_clip(material=material, requested_category=requested_category, order_index=order_start + len(clips), desired_duration=desired_duration)
            if clip is None:
                continue
            clips.append(clip)
            fulfilled_seconds = round(fulfilled_seconds + clip.clip_duration_seconds, 3)
            remaining = round(max(target_seconds - fulfilled_seconds, 0.0), 3)
            logger.info("[Assembly] 片段分配: requested=%s source=%s file=%s start=%.3f end=%.3f duration=%.3f remaining=%.3f", requested_category, source_category, clip.file_name, clip.clip_start_seconds, clip.clip_end_seconds, clip.clip_duration_seconds, remaining)
        return clips, fulfilled_seconds, remaining

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
        grouped = {key: [] for key in CATEGORY_TARGET_RATIOS}
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
