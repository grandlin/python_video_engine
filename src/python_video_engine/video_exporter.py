from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .assembly_engine import AssemblyPlan

logger = logging.getLogger("python_video_engine.video_exporter")

CLIP_PROBE_TIMEOUT_SECONDS = 5.0
CLIP_DECODE_TIMEOUT_SECONDS = 4.0
PRECHECK_PER_FILE_TIMEOUT_SECONDS = 15.0
CLIP_EXTRACT_TIMEOUT_SECONDS = 15.0
FINAL_CONCAT_TIMEOUT_SECONDS = 600.0


@dataclass(slots=True)
class VideoExportResult:
    client_name: str
    output_path: str
    duration_seconds: float
    clip_count: int
    video_index: int
    skipped_clip_count: int
    skipped_files: list[str]
    blacklisted_paths: list[str]


class VideoExporter:
    def __init__(self, output_dir: str | Path | None = None) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.output_dir = Path(output_dir) if output_dir else Path("output_videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def precheck_plan_clips(
        self,
        assembly_plan: AssemblyPlan,
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> tuple[AssemblyPlan, list[str]]:
        total = len(assembly_plan.clips)
        for idx, clip in enumerate(assembly_plan.clips, start=1):
            if progress_callback:
                progress_callback(idx, total, clip.file_name)
        return assembly_plan, []

    def export(self, assembly_plan: AssemblyPlan, video_index: int = 1) -> VideoExportResult:
        logger.info("[VideoExporter] 开始导出视频: client=%s clips=%s index=%s", assembly_plan.client_name, len(assembly_plan.clips), video_index)

        if not assembly_plan.clips:
            raise ValueError("AssemblyPlan 中没有视频片段，无法导出")

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("未找到 ffmpeg，可执行导出中止")

        skipped_files: list[str] = []
        blacklisted_paths: set[str] = set()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{assembly_plan.client_name}_mix_{video_index}_{timestamp}.mp4"
        output_path = self.output_dir / output_filename

        with tempfile.TemporaryDirectory(prefix="video_exporter_") as temp_dir:
            temp_root = Path(temp_dir)
            clip_files: list[Path] = []

            for idx, clip in enumerate(assembly_plan.clips, start=1):
                if clip.absolute_path in blacklisted_paths:
                    skipped_files.append(clip.file_name)
                    continue

                clip_path = temp_root / f"clip_{idx:04d}.mp4"
                ok, timed_out = self._extract_clip_with_timeout(
                    ffmpeg=ffmpeg,
                    src=clip.absolute_path,
                    start=clip.clip_start_seconds,
                    end=clip.clip_end_seconds,
                    out=clip_path,
                )
                if not ok:
                    if timed_out:
                        logger.error("[VideoExporter] 片段超时，剔除整文件并跳过: file=%s", clip.absolute_path)
                        blacklisted_paths.add(clip.absolute_path)
                    else:
                        logger.warning("[VideoExporter] 片段切出失败（非超时），仅跳过本片段: file=%s", clip.absolute_path)
                    skipped_files.append(clip.file_name)
                    continue

                clip_files.append(clip_path)

            if not clip_files:
                raise RuntimeError("所有片段均不可用，导出中止。请检查素材是否损坏。")

            concat_list = temp_root / "concat_list.txt"
            concat_list.write_text("\n".join([f"file '{str(p).replace("'", "''")}'" for p in clip_files]), encoding="utf-8")

            concat_cmd = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ]

            logger.info("[VideoExporter] 开始拼接并写出: %s", output_path)
            try:
                subprocess.run(
                    concat_cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=FINAL_CONCAT_TIMEOUT_SECONDS,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"最终拼接超时: {exc}") from exc
            except Exception as exc:
                raise RuntimeError(f"最终拼接失败: {exc}") from exc

        duration_seconds = self._probe_duration_seconds(str(output_path))
        logger.info("[VideoExporter] 视频导出完成: path=%s duration=%.3fs skipped=%s", output_path, duration_seconds, len(skipped_files))

        return VideoExportResult(
            client_name=assembly_plan.client_name,
            output_path=str(output_path),
            duration_seconds=duration_seconds,
            clip_count=max(len(assembly_plan.clips) - len(skipped_files), 0),
            video_index=video_index,
            skipped_clip_count=len(skipped_files),
            skipped_files=sorted(set(skipped_files)),
            blacklisted_paths=sorted(blacklisted_paths),
        )

    def _extract_clip_with_timeout(self, ffmpeg: str, src: str, start: float, end: float, out: Path) -> tuple[bool, bool]:
        duration = max(float(end) - float(start), 0.1)
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            f"{max(float(start), 0.0):.3f}",
            "-i",
            src,
            "-t",
            f"{duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=CLIP_EXTRACT_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
            )
            return (out.exists() and out.stat().st_size > 0), False
        except subprocess.TimeoutExpired:
            logger.error("[VideoExporter] 片段切出超时: file=%s start=%.3f end=%.3f timeout=%.1fs", src, start, end, CLIP_EXTRACT_TIMEOUT_SECONDS)
            return False, True
        except Exception as exc:
            msg = str(exc).lower()
            if "nal" in msg or "aac" in msg or "decode" in msg:
                logger.error("[VideoExporter] 检测到解码错误: file=%s err=%s", src, exc)
            else:
                logger.error("[VideoExporter] 片段切出失败: file=%s err=%s", src, exc)
            return False, False

    def _is_clip_readable(self, path: str) -> bool:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return True

        cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height,duration", "-of", "json", path]
        try:
            completed = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=CLIP_PROBE_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
            )
            payload = json.loads(completed.stdout or "{}")
            streams = payload.get("streams", []) if isinstance(payload, dict) else []
            return bool(streams)
        except Exception:
            return False

    def _can_decode_clip_range(self, path: str, start_seconds: float) -> bool:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return True

        safe_start = max(float(start_seconds), 0.0)
        cmd = [ffmpeg, "-v", "error", "-ss", f"{safe_start:.3f}", "-i", path, "-frames:v", "1", "-f", "null", "-"]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=CLIP_DECODE_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
            )
            return True
        except Exception:
            return False

    def _probe_duration_seconds(self, path: str) -> float:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return 0.0
        cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
        try:
            completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
            payload = json.loads(completed.stdout or "{}")
            fmt = payload.get("format", {}) if isinstance(payload, dict) else {}
            return round(float(fmt.get("duration", 0.0) or 0.0), 3)
        except Exception:
            return 0.0
