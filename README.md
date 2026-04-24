# Python Video Engine

This isolated directory hosts the new Python backend video processing engine.

Current scope:
- step 1 `MaterialFetcher`
- step 2 `ContentGenerator`
- step 3 `AssemblyEngine`
- step 4 `DraftRenderer`
- desktop GUI workflow for selecting materials, voice, and generating drafts

## Structure

- `src/python_video_engine/` — Python package source
- `main.py` — CLI entry and desktop GUI entry
- `temp_assets/` — temporary generated audio assets
- `output_drafts/` — generated local draft project folders
- `requirements.txt` — third-party dependency list for the engine

## Voice options

- `female_standard` → `zh-CN-XiaoxiaoNeural`
- `male_dynamic` → `zh-CN-YunxiNeural`
- `male_mature` → `zh-CN-YunjianNeural`
- `child_cute` → `zh-CN-XiaoyiNeural`

## Desktop workflow

The desktop app now supports this flow:

- first launch: set Jianying draft box path once, then the app remembers it
- choose customer material path
- choose voice
- click generate
- automatically move the generated draft into the Jianying draft box
- exported folder name automatically appends a timestamp to avoid conflicts

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

- `LLM_API_URL`
- `LLM_API_KEY`
- optional `LLM_MODEL` (default: `gpt-4o-mini`)

If they are not configured, the app will fall back to built-in template copywriting.

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
