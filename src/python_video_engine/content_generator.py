from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from mutagen.mp3 import MP3
from moviepy.editor import AudioFileClip, concatenate_audioclips
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from .network import ProxySettings, build_httpx_client, check_tcp_connectivity

from .runtime_config import get_config_value, get_enabled_voices, get_runtime_config

logger = logging.getLogger("python_video_engine.content_generator")

DEFAULT_PROVIDER_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_VOICE_KEY = "female_standard"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_CHAT_COMPLETIONS_URL = f"{DASHSCOPE_BASE_URL}/chat/completions"
DASHSCOPE_HOST = "dashscope.aliyuncs.com"

SCRIPT_LANGUAGE_ZH = "zh"
SCRIPT_LANGUAGE_EN = "en"
ENGLISH_SYSTEM_PROMPT = (
    "You are a professional copywriter. Based on keywords.txt, generate a video script entirely in English. "
    "Do not include any Chinese characters. Always include proper punctuation (commas, periods, question marks)."
)

VOICE_LIBRARY = {
    "female_standard": "zh-CN-XiaoxiaoNeural",
    "male_dynamic": "zh-CN-YunxiNeural",
    "male_mature": "zh-CN-YunjianNeural",
    "child_cute": "zh-CN-XiaoyiNeural",
    "en-US-JennyNeural": "en-US-JennyNeural",
    "en-US-GuyNeural": "en-US-GuyNeural",
    "en-GB-SoniaNeural": "en-GB-SoniaNeural",
    "en-US-AndrewNeural": "en-US-AndrewNeural",
}


@dataclass(slots=True)
class ContentGenerationResult:
    client_name: str
    base_path: str
    keywords: list[str]
    script_text: str
    audio_path: str
    audio_duration_seconds: float
    voice: str
    used_mock_tts: bool
    tts_provider: str
    script_language: str
    script_structure: dict[str, str]
    subtitle_units: list[str] = field(default_factory=list)
    subtitle_durations_ms: list[int] = field(default_factory=list)
    subtitle_audio_paths: list[str] = field(default_factory=list)


class ContentGenerator:
    def __init__(self, voice_key: str = DEFAULT_VOICE_KEY, target_language: str = SCRIPT_LANGUAGE_ZH) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self._load_runtime_env()

        self.runtime_config = get_runtime_config()
        self.voice_library = {item["key"]: item["provider_voice"] for item in get_enabled_voices()}
        if not self.voice_library:
            self.voice_library = dict(VOICE_LIBRARY)
        else:
            self.voice_library.update(VOICE_LIBRARY)

        self.default_voice_key = next(iter(self.voice_library.keys()), DEFAULT_VOICE_KEY)
        self.voice_key = voice_key if voice_key in self.voice_library else self.default_voice_key
        if voice_key.startswith("en-"):
            self.voice_key = voice_key
        self.voice = self.voice_library.get(self.voice_key, self.voice_key if self.voice_key.startswith("en-") else DEFAULT_PROVIDER_VOICE)
        self.target_language = target_language if target_language in {SCRIPT_LANGUAGE_ZH, SCRIPT_LANGUAGE_EN} else SCRIPT_LANGUAGE_ZH

        self.temp_assets_dir = self._project_root() / "temp_assets"
        self.temp_assets_dir.mkdir(parents=True, exist_ok=True)

        self.llm_api_url = (os.getenv("LLM_API_URL", "").strip() or DASHSCOPE_BASE_URL)
        self.llm_model = os.getenv("LLM_MODEL", str(get_config_value("llm", "model", default="qwen-plus"))).strip()
        self.llm_timeout = int(os.getenv("API_TIMEOUT", str(get_config_value("llm", "timeout_seconds", default=120) or 120)).strip() or 120)
        self.llm_api_key_env = str(get_config_value("llm", "api_key_env", default="SILICONFLOW_API_KEY")).strip() or "SILICONFLOW_API_KEY"
        self.llm_requires_api_key = bool(get_config_value("llm", "requires_api_key", default=True))
        self.llm_system_prompt = str(get_config_value("llm", "system_prompt", default="你擅长撰写中文外贸工厂短视频口播文案。")).strip()
        self.llm_api_key = self._resolve_llm_api_key()
        self.translation_enabled = bool(get_config_value("llm", "translation_enabled", default=False))

        self.proxy_settings = ProxySettings.from_env()
        self._ai_server_checked = False



        self.tts_api_url = str(get_config_value("tts", "api_url", default="https://tts.zunqianlin.workers.dev/v1/audio/speech")).strip()
        self.tts_timeout = int(get_config_value("tts", "timeout_seconds", default=180) or 180)
        self.tts_max_retries = int(get_config_value("tts", "retry_count", default=3) or 3)
        self.tts_model = str(get_config_value("tts", "model", default="tts-1")).strip() or "tts-1"
        self._tts_server_checked = False
        self._pydub_warned = False

    def generate(self, base_path: str | Path, client_name: str, keywords: list[str]) -> ContentGenerationResult:
        resolved_base_path = Path(base_path).expanduser().resolve(strict=False)
        logger.info("[ContentGenerator] 开始生成文案与配音: client=%s voice=%s lang=%s", client_name, self.voice, self.target_language)

        latest_keywords = self._load_latest_keywords(resolved_base_path)
        effective_keywords = latest_keywords if latest_keywords else keywords
        if latest_keywords:
            logger.info("[ContentGenerator] 使用 keywords.txt 最新内容: count=%s", len(latest_keywords))

        script_structure = self._generate_script(client_name=client_name, keywords=effective_keywords)
        script_text = script_structure["script_for_tts"]
        if self.translation_enabled:
            logger.info("[ContentGenerator] translation_enabled=true，但当前版本已屏蔽翻译调用")

        audio_path = self._build_audio_output_path(client_name=client_name)
        subtitle_units = self._split_script_into_units(script_text, self.target_language)
        subtitle_durations_ms, subtitle_audio_paths = self._generate_audio_by_units(subtitle_units, self.voice, audio_path)
        self._ensure_valid_audio_file(audio_path)
        audio_duration_seconds = self._resolve_audio_duration(audio_path)

        return ContentGenerationResult(
            client_name=client_name,
            base_path=str(resolved_base_path),
            keywords=effective_keywords.copy(),
            script_text=script_text,
            audio_path=str(audio_path),
            audio_duration_seconds=audio_duration_seconds,
            voice=self.voice,
            used_mock_tts=False,
            tts_provider="worker-tts",
            script_language=self.target_language,
            script_structure=script_structure,
            subtitle_units=subtitle_units,
            subtitle_durations_ms=subtitle_durations_ms,
            subtitle_audio_paths=subtitle_audio_paths,
        )

    def _split_script_into_units(self, script_text: str, target_language: str) -> list[str]:
        cleaned = " ".join(script_text.split()).strip()
        if not cleaned:
            return []
        punctuation = set(".!?,;:") if target_language == SCRIPT_LANGUAGE_EN else set("，。！？；：,.!?、")

        units: list[str] = []
        buf: list[str] = []
        for ch in cleaned:
            if ch in "\r\n":
                continue
            buf.append(ch)
            if ch in punctuation:
                unit = "".join(buf).strip()
                if unit:
                    units.append(unit)
                buf = []
        if buf:
            unit = "".join(buf).strip()
            if unit:
                units.append(unit)
        return units

    def _generate_audio_by_units(self, units: list[str], voice_name: str, output_path: Path) -> tuple[list[int], list[str]]:
        if not units:
            self.generate_voice(text=" ", voice_name=voice_name, output_path=output_path)
            self._strip_silence_inplace(output_path)
            return [self._resolve_segment_duration_ms(output_path)], [str(output_path)]

        durations_ms: list[int] = []
        clips: list[AudioFileClip] = []
        merged = None
        temp_files: list[Path] = []

        try:
            for index, unit in enumerate(units):
                temp_path = output_path.with_name(f"{output_path.stem}_u{index:03d}.mp3")
                temp_files.append(temp_path)
                self.generate_voice(text=unit, voice_name=voice_name, output_path=temp_path)
                self._ensure_valid_audio_file(temp_path)
                self._strip_silence_inplace(temp_path)
                durations_ms.append(self._resolve_segment_duration_ms(temp_path))
            clips = [AudioFileClip(str(path)) for path in temp_files]
            if clips:
                merged = concatenate_audioclips(clips)
                merged.write_audiofile(str(output_path), fps=44100, logger=None)
        finally:
            try:
                if merged is not None:
                    merged.close()
            except Exception:
                pass
            for clip in clips:
                try:
                    clip.close()
                except Exception:
                    pass

        return durations_ms, [str(x) for x in temp_files]

    def _strip_silence_inplace(self, audio_path: Path) -> None:
        try:
            import audioop  # noqa: F401
            from pydub import AudioSegment
            from pydub.effects import strip_silence

            segment = AudioSegment.from_file(str(audio_path))
            dbfs = float(segment.dBFS) if segment.dBFS != float("-inf") else -40.0
            trimmed = strip_silence(segment, silence_len=120, silence_thresh=dbfs - 16.0, padding=80)
            if len(trimmed) <= 0:
                trimmed = segment
            trimmed.export(str(audio_path), format="mp3")
            return
        except Exception as exc:
            if self._try_strip_silence_ffmpeg(audio_path):
                if not self._pydub_warned:
                    self._pydub_warned = True
                    logger.warning("[ContentGenerator] pydub/audioop 不可用，已自动回退 ffmpeg silenceremove。详情: %s", exc)
                return
            if not self._pydub_warned:
                self._pydub_warned = True
                logger.warning("[ContentGenerator] pydub/strip_silence 不可用，且 ffmpeg 回退失败，已保留原音频。请检查 audioop 兼容层或 ffmpeg。详情: %s", exc)
            else:
                logger.warning("[ContentGenerator] strip_silence 失败，回退原音频: %s", exc)

    def _try_strip_silence_ffmpeg(self, audio_path: Path) -> bool:
        temp_path = audio_path.with_name(f"{audio_path.stem}.trimmed{audio_path.suffix}")
        filter_arg = "silenceremove=start_periods=1:start_duration=0.12:start_threshold=-40dB:stop_periods=-1:stop_duration=0.12:stop_threshold=-40dB"
        cmd = [
            self._resolve_ffmpeg_executable(),
            "-y",
            "-i",
            str(audio_path),
            "-af",
            filter_arg,
            str(temp_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            ok = proc.returncode == 0 and temp_path.exists() and temp_path.stat().st_size > 0
            if not ok:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                return False
            temp_path.replace(audio_path)
            return True
        except Exception:
            try:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def _resolve_ffmpeg_executable(self) -> str:
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return "ffmpeg"

    def _resolve_segment_duration_ms(self, audio_path: Path) -> int:
        try:
            import audioop  # noqa: F401
            from pydub import AudioSegment

            segment = AudioSegment.from_file(str(audio_path))
            return max(int(round(segment.duration_seconds * 1000.0)), 1)
        except Exception:
            duration = self._resolve_duration_ffprobe(audio_path)
            if duration is not None:
                return max(int(round(duration * 1000.0)), 1)
            return max(int(round(self._resolve_audio_duration(audio_path) * 1000.0)), 1)

    def _resolve_duration_ffprobe(self, audio_path: Path) -> float | None:
        cmd = [
            self._resolve_ffprobe_executable(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                return None
            value = (proc.stdout or "").strip()
            if not value:
                return None
            return float(value)
        except Exception:
            return None

    def _resolve_ffprobe_executable(self) -> str:
        ffmpeg_exe = self._resolve_ffmpeg_executable()
        if ffmpeg_exe.lower().endswith("ffmpeg.exe"):
            return ffmpeg_exe[:-10] + "ffprobe.exe"
        if ffmpeg_exe.lower().endswith("ffmpeg"):
            return ffmpeg_exe[:-6] + "ffprobe"
        return "ffprobe"

    def generate_voice(self, text: str, voice_name: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"input": text, "voice": voice_name, "model": self.tts_model}
        headers = {"Content-Type": "application/json"}
        last_error: Exception | None = None
        if not self._tts_server_checked and not self.proxy_settings.use_proxy:
            ok, detail = check_tcp_connectivity("tts.zunqianlin.workers.dev", 443, timeout_seconds=3.0)
            self._tts_server_checked = True
            if not ok:
                logger.warning("[ContentGenerator] TTS 连通性预检查失败，继续尝试请求: %s", detail)
        for attempt in range(1, self.tts_max_retries + 1):
            try:
                with build_httpx_client(timeout_seconds=float(self.tts_timeout), proxy_settings=self.proxy_settings) as client:
                    resp = client.post(self.tts_api_url, json=payload, headers=headers)
                if resp.status_code == 200:
                    output_path.write_bytes(resp.content)
                    return
                last_error = RuntimeError(f"语音请求失败，状态码: {resp.status_code}, 详情: {resp.text}")
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError, httpx.HTTPError) as exc:
                last_error = RuntimeError(f"TTS 网络请求异常，第 {attempt}/{self.tts_max_retries} 次重试失败: {exc}")
            if attempt < self.tts_max_retries:
                time.sleep(1.5 * attempt)
        raise RuntimeError("配音服务连接失败，已自动重试多次仍未成功。" f"\n接口：{self.tts_api_url}" f"\n详情：{last_error}" "\n请检查代理软件是否开启，或尝试更换代理节点（推荐使用日本或新加坡节点）。")

    def _generate_script(self, client_name: str, keywords: list[str]) -> dict[str, str]:
        if self.target_language == SCRIPT_LANGUAGE_EN:
            script_en = self._generate_llm_script_en(client_name=client_name, keywords=keywords)
            return {"script_zh": "", "script_en": script_en, "script_translated": "", "script_for_tts": script_en}
        script_zh = self._generate_llm_script_zh(client_name=client_name, keywords=keywords)
        return {"script_zh": script_zh, "script_en": "", "script_translated": "", "script_for_tts": script_zh}

    def _generate_llm_script_zh(self, client_name: str, keywords: list[str]) -> str:
        keyword_text = self._keywords_to_prompt_text(keywords)
        prompt = (
            f"请根据 keywords.txt 的业务关键词，为客户“{client_name}”创作一段中文工厂宣传口播稿。"
            f"关键词全文（请完整吸收，不要只挑少量词）：{keyword_text}。"
            "要求：1. 110~150 字；2. 口语化但不空泛，避免口水话和万能套话；"
            "3. 必须体现具体业务信息：至少包含产品/工艺、品质控制、交付/服务中的两项；"
            "4. 每次生成都要有明显差异化表达与不同叙事角度；"
            "5. 不要标题、不要分点、不要引号，只输出文案正文。"
        )
        return self._request_llm(system_prompt=self.llm_system_prompt, user_prompt=prompt)

    def _generate_llm_script_en(self, client_name: str, keywords: list[str]) -> str:
        keyword_text = self._keywords_to_prompt_text(keywords)
        prompt = (
            f"Based on the full business keywords from keywords.txt for client '{client_name}', write an English factory promo voiceover script. "
            f"Keywords (use comprehensively): {keyword_text}. "
            "Requirements: 110-150 words, no Chinese characters, no bullet points, no title, no quotation marks, "
            "avoid filler language, include concrete business details about product/process, quality control, and delivery/service. "
            "Use a clearly different angle each time."
        )
        for attempt in range(1, 4):
            content = self._request_llm(system_prompt=ENGLISH_SYSTEM_PROMPT, user_prompt=prompt)
            if not self._looks_degenerate_english_script(content):
                return content
            logger.warning("[ContentGenerator] 检测到英文文案异常重复，自动重试生成: attempt=%s/3", attempt)
        raise RuntimeError("英文文案生成异常：检测到重复灌词（如 on on on ...），请重试。")

    def _request_llm(self, system_prompt: str, user_prompt: str) -> str:
        api_url = self._resolve_llm_api_url()
        if self.llm_requires_api_key and not self.llm_api_key:
            raise RuntimeError("未检测到大模型接口密钥。\n请在项目根目录 .env 中配置 SILICONFLOW_API_KEY（百炼 API Key）后重试。")
        headers = {"Content-Type": "application/json"}
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"
        payload = {
            "model": self.llm_model,
            "temperature": 0.8,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        }
        try:
            resp = self._llm_post(api_url, headers=headers, payload=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            detail = exc.response.text if exc.response is not None else str(exc)
            if status == 401:
                raise RuntimeError("百炼鉴权失败（HTTP 401）。请检查 SILICONFLOW_API_KEY 是否正确。\n接口：" + api_url + "\n返回：" + detail) from exc
            if status == 429:
                raise RuntimeError("百炼触发频率限制（HTTP 429）。已自动重试仍未成功，请稍后再试。\n接口：" + api_url + "\n返回：" + detail) from exc
            raise RuntimeError("大模型文案生成失败，请检查 API Key、网络或接口配置。\n接口：" + api_url + "\nHTTP 状态：" + str(status) + "\n详情：" + detail) from exc
        except Exception as exc:
            raise RuntimeError("大模型文案生成失败，请检查 API Key、网络或接口配置。\n接口：" + api_url + "\n详情：" + str(exc)) from exc
        if not content:
            raise RuntimeError("大模型返回内容为空，无法继续生成文案。" f"\n接口：{api_url}")
        return content.replace("\n", " ").strip()

    def _llm_post(self, url: str, headers: dict[str, str], payload: dict) -> httpx.Response:
        if not self._ai_server_checked:
            ok, detail = check_tcp_connectivity(DASHSCOPE_HOST, 443, timeout_seconds=3.0)
            self._ai_server_checked = True
            if not ok:
                logger.warning("[ContentGenerator] 百炼连通性预检查失败，继续尝试请求: %s", detail)

        @retry(
            retry=retry_if_exception(self._is_retryable_llm_exception),
            stop=stop_after_attempt(3),
            wait=wait_fixed(1),
            reraise=True,
            before_sleep=lambda _: logger.warning("网络拥堵或触发频率限制，正在尝试重新连接..."),
        )
        def _do() -> httpx.Response:
            if "aliyuncs.com" in url:
                try:
                    with httpx.Client(timeout=httpx.Timeout(float(self.llm_timeout)), trust_env=True, follow_redirects=True, proxy=None) as client:
                        response = client.post(url, json=payload, headers=headers)
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError):
                    with httpx.Client(timeout=httpx.Timeout(float(self.llm_timeout)), trust_env=True, follow_redirects=True) as client:
                        response = client.post(url, json=payload, headers=headers)
            else:
                with build_httpx_client(timeout_seconds=float(self.llm_timeout), proxy_settings=self.proxy_settings) as client:
                    response = client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise httpx.HTTPStatusError("Rate limited", request=response.request, response=response)
            return response

        return _do()

    def _is_retryable_llm_exception(self, exc: Exception) -> bool:
        if isinstance(exc, httpx.ReadTimeout):
            return True
        if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
            return exc.response.status_code == 429
        return False

    def _keywords_to_prompt_text(self, keywords: list[str]) -> str:
        selected = [item.strip() for item in keywords if item.strip()][:50]
        return "、".join(selected) if selected else "factory capability, quality control, stable delivery, export service"

    def _load_latest_keywords(self, base_path: Path) -> list[str]:
        for file_name in ["keywords.txt", "keywords"]:
            p = base_path / file_name
            if not p.exists() or not p.is_file():
                continue
            try:
                lines = [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
            except Exception as exc:
                logger.warning("[ContentGenerator] 读取关键词文件失败: file=%s err=%s", p, exc)
                return []
            return lines
        return []

    def _looks_degenerate_english_script(self, text: str) -> bool:
        words = re.findall(r"[A-Za-z]+", text.lower())
        if len(words) < 40:
            return False
        unique_ratio = len(set(words)) / max(len(words), 1)
        if unique_ratio < 0.28:
            return True
        max_run = 1
        run = 1
        for i in range(1, len(words)):
            if words[i] == words[i - 1]:
                run += 1
                if run > max_run:
                    max_run = run
            else:
                run = 1
        if max_run >= 8:
            return True
        return False

    def _resolve_llm_api_key(self) -> str:
        for value in [os.getenv("SILICONFLOW_API_KEY", "").strip(), os.getenv(self.llm_api_key_env, "").strip(), os.getenv("LLM_API_KEY", "").strip()]:
            if value:
                return value
        return ""

    def _resolve_llm_api_url(self) -> str:
        configured = self.llm_api_url.strip().rstrip("/")
        base = DASHSCOPE_BASE_URL.rstrip("/")
        if not configured or configured == base:
            return DASHSCOPE_CHAT_COMPLETIONS_URL
        if configured.startswith(base):
            return configured
        raise RuntimeError("大模型接口地址配置错误。\n" f"当前配置：{configured}\n" f"请使用阿里云百炼 OpenAI 兼容地址：{DASHSCOPE_BASE_URL}")

    def _ensure_valid_audio_file(self, audio_path: Path) -> None:
        if not audio_path.exists() or audio_path.stat().st_size <= 0:
            raise RuntimeError("audio file was not generated")
        MP3(str(audio_path))

    def _resolve_audio_duration(self, audio_path: Path) -> float:
        return round(float(MP3(str(audio_path)).info.length), 3)

    def _build_audio_output_path(self, client_name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in client_name).strip("_")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.temp_assets_dir / f"{safe or 'client'}_{ts}.mp3"

    def _load_runtime_env(self) -> None:
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / ".env")
        candidates.append(self._project_root() / ".env")
        candidates.append(Path.cwd() / ".env")
        for p in candidates:
            load_dotenv(p, override=False)

    def _project_root(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]
