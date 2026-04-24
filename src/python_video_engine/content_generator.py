from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from mutagen.mp3 import MP3

logger = logging.getLogger("python_video_engine.content_generator")

VOICE_LIBRARY = {
    "female_standard": "zh-CN-XiaoxiaoNeural",
    "male_dynamic": "zh-CN-YunxiNeural",
    "male_mature": "zh-CN-YunjianNeural",
    "child_cute": "zh-CN-XiaoyiNeural",
}
DEFAULT_VOICE_KEY = "female_standard"
TTS_API_URL = "https://tts.zunqianlin.workers.dev/v1/audio/speech"
TTS_MAX_RETRIES = 3
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.siliconflow.cn/v1/chat/completions").strip()
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip()


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


class ContentGenerator:
    def __init__(self, voice_key: str = DEFAULT_VOICE_KEY) -> None:
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        self.voice_key = voice_key if voice_key in VOICE_LIBRARY else DEFAULT_VOICE_KEY
        self.voice = VOICE_LIBRARY[self.voice_key]
        self.temp_assets_dir = self._project_root() / "temp_assets"
        self.temp_assets_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, base_path: str | Path, client_name: str, keywords: list[str]) -> ContentGenerationResult:
        resolved_base_path = Path(base_path).expanduser().resolve(strict=False)
        logger.info("[ContentGenerator] 开始生成文案与配音: client=%s voice=%s", client_name, self.voice)

        script_text = self._generate_script(client_name=client_name, keywords=keywords)
        audio_path = self._build_audio_output_path(client_name=client_name)
        logger.info("[ContentGenerator] 文案生成完成: chars=%s", len(script_text))

        self.generate_voice(text=script_text, voice_name=self.voice, output_path=audio_path)
        self._ensure_valid_audio_file(audio_path)
        audio_duration_seconds = self._resolve_audio_duration(audio_path)

        logger.info(
            "[ContentGenerator] 语音结果: provider=%s duration=%.3fs file=%s",
            "worker-tts",
            audio_duration_seconds,
            audio_path,
        )

        return ContentGenerationResult(
            client_name=client_name,
            base_path=str(resolved_base_path),
            keywords=keywords.copy(),
            script_text=script_text,
            audio_path=str(audio_path),
            audio_duration_seconds=audio_duration_seconds,
            voice=self.voice,
            used_mock_tts=False,
            tts_provider="worker-tts",
        )

    def generate_voice(self, text: str, voice_name: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"input": text, "voice": voice_name, "model": "tts-1"}
        headers = {"Content-Type": "application/json"}
        last_error: Exception | None = None

        for attempt in range(1, TTS_MAX_RETRIES + 1):
            try:
                response = requests.post(TTS_API_URL, json=payload, headers=headers, timeout=90)
                if response.status_code == 200:
                    with open(output_path, "wb") as f:
                        f.write(response.content)
                    print(f"[ContentGenerator] 语音已成功生成并保存至: {output_path}")
                    return
                last_error = RuntimeError(f"语音请求失败，状态码: {response.status_code}, 详情: {response.text}")
                logger.warning("[ContentGenerator] TTS 请求失败，第 %s/%s 次: %s", attempt, TTS_MAX_RETRIES, last_error)
            except requests.exceptions.SSLError as exc:
                last_error = RuntimeError(f"TTS SSL 连接异常，第 {attempt}/{TTS_MAX_RETRIES} 次重试失败: {exc}")
                logger.warning("[ContentGenerator] %s", last_error)
            except requests.exceptions.RequestException as exc:
                last_error = RuntimeError(f"TTS 网络请求异常，第 {attempt}/{TTS_MAX_RETRIES} 次重试失败: {exc}")
                logger.warning("[ContentGenerator] %s", last_error)

            if attempt < TTS_MAX_RETRIES:
                time.sleep(1.5 * attempt)

        raise RuntimeError(
            "配音服务连接失败，已自动重试多次仍未成功。"
            f"\n接口：{TTS_API_URL}"
            f"\n详情：{last_error}"
        )

    def _generate_script(self, client_name: str, keywords: list[str]) -> str:
        llm_script = self._generate_llm_script(client_name=client_name, keywords=keywords)
        if llm_script:
            return llm_script
        return self._generate_mock_script(client_name=client_name, keywords=keywords)

    def _generate_llm_script(self, client_name: str, keywords: list[str]) -> str | None:
        if not LLM_API_KEY:
            logger.info("[ContentGenerator] 未配置大模型接口密钥，回退关键词模板文案")
            return None

        selected_keywords = [item.strip() for item in keywords if item.strip()][:8]
        keyword_text = "、".join(selected_keywords) if selected_keywords else "工厂实力、品质管控、交付稳定、出口服务"
        prompt = (
            f"你是短视频口播文案策划。请为客户“{client_name}”写一段中文工厂宣传口播稿。"
            f"参考关键词：{keyword_text}。要求：1. 口语化自然；2. 控制在110到150字；3. 突出工厂实力、产品/工艺、品质与交付；"
            "4. 不要分点，不要标题，不要加引号；5. 每次都换一种表达，不要固定套话。"
        )
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LLM_API_KEY}"}
        payload = {
            "model": LLM_MODEL,
            "temperature": 0.9,
            "messages": [
                {"role": "system", "content": "你擅长撰写中文外贸工厂短视频口播文案。"},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            response = requests.post(LLM_API_URL, json=payload, headers=headers, timeout=90)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            if content:
                logger.info("[ContentGenerator] 大模型文案生成成功: model=%s", LLM_MODEL)
                return content.replace("\n", " ").strip()
        except Exception as exc:
            logger.warning("[ContentGenerator] 大模型文案生成失败，回退关键词模板文案: %s", exc)
        return None

    def _generate_mock_script(self, client_name: str, keywords: list[str]) -> str:
        selected_keywords = [item.strip() for item in keywords if item.strip()][:4]
        joined_keywords = "、".join(selected_keywords) if selected_keywords else "稳定交付、品质管控、定制加工、出口服务"
        variants = [
            f"这里是{client_name}的生产现场。我们围绕{joined_keywords}持续打磨，从设备加工到成品检验与装箱发货，整个流程都强调稳定品质与交付效率，期待为更多海外客户提供可靠合作支持。",
            f"走进{client_name}工厂，可以看到从机器运转到成品出货的完整流程。我们重点深耕{joined_keywords}，坚持标准化管理、稳定产能和快速响应，为客户带来更省心的加工与出口交付服务。",
            f"在{client_name}，从车间管理到成品包装，每一步都围绕{joined_keywords}展开。我们注重效率、品质和交期控制，希望用更扎实的制造能力，为海内外客户创造长期合作价值。",
        ]
        return variants[datetime.now().second % len(variants)]

    def _ensure_valid_audio_file(self, audio_path: Path) -> None:
        if not audio_path.exists() or audio_path.stat().st_size <= 0:
            raise RuntimeError("audio file was not generated")
        MP3(str(audio_path))

    def _resolve_audio_duration(self, audio_path: Path) -> float:
        audio = MP3(str(audio_path))
        return round(float(audio.info.length), 3)

    def _build_audio_output_path(self, client_name: str) -> Path:
        safe_client_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in client_name).strip("_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.temp_assets_dir / f"{safe_client_name or 'client'}_{timestamp}.mp3"

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]
