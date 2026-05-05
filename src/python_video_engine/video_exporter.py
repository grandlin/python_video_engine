from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from moviepy.editor import VideoFileClip, concatenate_videoclips

from .assembly_engine import AssemblyPlan

logger = logging.getLogger("python_video_engine.video_exporter")


@dataclass(slots=True)
class VideoExportResult:
    client_name: str
    output_path: str
    duration_seconds: float
    clip_count: int
    video_index: int


class VideoExporter:
    def __init__(self, output_dir: str | Path | None = None) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.output_dir = Path(output_dir) if output_dir else Path("output_videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        assembly_plan: AssemblyPlan,
        video_index: int = 1,
    ) -> VideoExportResult:
        logger.info(
            "[VideoExporter] 开始导出视频: client=%s clips=%s index=%s",
            assembly_plan.client_name,
            len(assembly_plan.clips),
            video_index,
        )

        if not assembly_plan.clips:
            raise ValueError("AssemblyPlan 中没有视频片段，无法导出")

        video_clips: list[VideoFileClip] = []
        try:
            for clip in assembly_plan.clips:
                logger.info(
                    "[VideoExporter] 加载片段: file=%s start=%.3f end=%.3f",
                    clip.file_name,
                    clip.clip_start_seconds,
                    clip.clip_end_seconds,
                )

                video_clip = VideoFileClip(clip.absolute_path)
                subclip = video_clip.subclip(clip.clip_start_seconds, clip.clip_end_seconds)
                video_clips.append(subclip)

            logger.info("[VideoExporter] 开始拼接 %s 个片段...", len(video_clips))
            final_video = concatenate_videoclips(video_clips, method="compose")

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{assembly_plan.client_name}_mix_{video_index}_{timestamp}.mp4"
            output_path = self.output_dir / output_filename

            logger.info("[VideoExporter] 开始写入视频文件: %s", output_path)
            final_video.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
                fps=30,
            )

            duration_seconds = round(final_video.duration, 3)
            logger.info("[VideoExporter] 视频导出完成: path=%s duration=%.3fs", output_path, duration_seconds)

            return VideoExportResult(
                client_name=assembly_plan.client_name,
                output_path=str(output_path),
                duration_seconds=duration_seconds,
                clip_count=len(assembly_plan.clips),
                video_index=video_index,
            )

        finally:
            for clip in video_clips:
                try:
                    clip.close()
                except Exception:
                    pass
