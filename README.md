# Python Video Engine

## v0.1.3（2026-05-05）更新说明

- **支持单目录素材直混**：不再强制要求 `01/02/03` 三分类目录，只要素材目录内存在 mp4 即可直接生成。
- **混剪差异性增强**：素材分配优先低使用频次并打散顺序，降低连续视频使用同一素材开头的概率。
- **开头去重策略优化**：新视频前段优先避开上一条视频已使用素材，减少“开头雷同”。
- **随机种子优化**：批量生成时使用更分散的随机种子，进一步拉开多条视频的选材差异。
- **控制台打包版本**：提供带黑色日志窗口的 `console` EXE，便于一线同事观察进度与排查问题。

## v0.1.2（2026-05-05）更新说明

- **新增纯混剪模式**：支持无文案、无配音，直接生成 MP4 视频
- **双模式支持**：完整视频模式（文案+配音+剪映草稿）和纯混剪模式（直接 MP4）
- **批量生成**：支持一次生成多个视频（1-10个）
- **智能素材复用**：优先使用历史上用得少的素材，避免重复
- **随机片段时长**：每个素材片段 3-4 秒之间随机，节奏更自然
- **灵活时长控制**：支持 15-30 秒和 30-60 秒两种时长范围

## v0.1.1（2026-04-26）更新说明

- 修复英文朗读/英文字幕处理：补全英文文本切分与换行逻辑，避免生成草稿阶段因英文处理缺失导致崩溃。
- 修复 API 连接与网络稳定性：支持系统代理/自定义代理（不再写死本地端口），并统一超时与重试；启动时增加网络连通性检查提示。
- 运行时配置加载更稳：默认关闭远程配置加载，避免 401 导致的启动失败，改用本地配置/缓存兜底。

This isolated directory hosts the new Python backend video processing engine.

Current scope:
- step 1 `MaterialFetcher` — 扫描素材文件夹
- step 2 `ContentGenerator` — 生成文案和配音（完整视频模式）
- step 3 `AssemblyEngine` — 智能组装视频片段
- step 4 `DraftRenderer` — 渲染剪映草稿（完整视频模式）
- step 5 `VideoExporter` — 导出 MP4 视频（纯混剪模式）
- desktop GUI workflow for selecting materials, mode, and generating videos

## Structure

- `src/python_video_engine/` — Python package source
- `main.py` — CLI entry and desktop GUI entry
- `temp_assets/` — temporary generated audio assets (完整视频模式)
- `output_drafts/` — generated local draft project folders (完整视频模式)
- `output_videos/` — generated MP4 videos (纯混剪模式，默认路径)
- `requirements.txt` — third-party dependency list for the engine

## Voice options

- `female_standard` → `zh-CN-XiaoxiaoNeural`
- `male_dynamic` → `zh-CN-YunxiNeural`
- `male_mature` → `zh-CN-YunjianNeural`
- `child_cute` → `zh-CN-XiaoyiNeural`

## Desktop workflow

The desktop app now supports two modes:

### 完整视频模式（文案+配音+剪映草稿）
- first launch: set Jianying draft box path once, then the app remembers it
- choose customer material path
- choose voice (Chinese or English)
- set video duration (15-30s or 30-60s)
- set video count (1-10)
- click generate
- automatically move the generated draft into the Jianying draft box
- exported folder name automatically appends a timestamp to avoid conflicts

### 纯混剪模式（无文案无配音，直接MP4）
- first launch: set mix output path once, then the app remembers it
- choose customer material path
- set video duration (15-30s or 30-60s)
- set video count (1-10)
- click generate
- MP4 videos are directly exported to the output folder
- each video has a unique filename with timestamp

Recommended material folder structure:

- `01_工厂全景与大环境`
- `02_机器运转与加工细节`
- `03_成品展示与发货`
- optional `keywords.txt`

## Install

```bash
pip install -r requirements.txt
```

## Run GUI

```bash
python main.py
```

or

```bash
python main.py --gui
```

## Run CLI

If `--draft-box-path` is omitted in CLI mode, the app will try to use the saved local setting.

For real AI script generation, configure these environment variables before running:

- `SILICONFLOW_API_KEY`
- optional `LLM_API_URL` (default base: `https://api.siliconflow.cn/v1`)
- optional `LLM_MODEL` (default: `Qwen/Qwen2.5-7B-Instruct`)

If `SILICONFLOW_API_KEY` is missing, or the LLM request fails, the app raises an explicit error directly (no built-in template fallback).

```bash
python main.py --base-path "Z:\00_客户06105名点工贸_测试" --client-name "名点工贸" --voice female_standard --draft-box-path "C:\Users\用户名\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft" --json
```

## Package to exe

Install packaging dependency:

```bash
pip install pyinstaller
```

Build:

```bash
pyinstaller --noconfirm --onefile --windowed --name JianyingAutoEditor main.py
```

After packaging, the executable will be generated in `dist/JianyingAutoEditor.exe`.
