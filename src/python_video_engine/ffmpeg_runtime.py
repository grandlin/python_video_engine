from __future__ import annotations

import shutil
import sys
from pathlib import Path


_FFMPEG_REL = Path("third_party") / "ffmpeg" / "windows-x64"


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _candidate_binaries(name: str) -> list[Path]:
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        exe_dir = Path(sys.executable).resolve().parent

        if meipass:
            candidates.append(Path(meipass) / f"{name}.exe")
        candidates.append(exe_dir / "JianyingAutoEditor_lib" / f"{name}.exe")
        candidates.append(exe_dir / f"{name}.exe")
        return candidates

    base_dir = _runtime_base_dir()
    candidates.append(base_dir / _FFMPEG_REL / f"{name}.exe")
    candidates.append(base_dir / f"{name}.exe")
    return candidates


def _resolve_binary(name: str) -> str | None:
    for candidate in _candidate_binaries(name):
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    from_path = shutil.which(name)
    if from_path:
        return from_path

    return None


def get_ffmpeg_path() -> str | None:
    return _resolve_binary("ffmpeg")


def get_ffprobe_path() -> str | None:
    return _resolve_binary("ffprobe")
