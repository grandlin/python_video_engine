from __future__ import annotations
import argparse,json,os,shutil,socket,sys,threading,tkinter as tk,logging
import subprocess
import tempfile
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from pprint import pprint
from tkinter import filedialog,messagebox,ttk

# 配置日志输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def _install_audioop_compat() -> None:
    try:
        import audioop  # noqa: F401
        return
    except Exception:
        pass

    import importlib
    import os

    candidates: list[str] = []
    env_name = os.getenv("AUDIOOP_COMPAT_MODULE", "").strip()
    if env_name:
        candidates.append(env_name)
    candidates.extend([
        "pyaudioop",
        "audioop_compat",
        "audioop_lts",
    ])

    for name in candidates:
        try:
            mod = importlib.import_module(name)
            sys.modules["audioop"] = mod
            return
        except Exception:
            continue


_install_audioop_compat()

from src.python_video_engine import AssemblyEngine,ContentGenerator,DraftRenderer,MaterialFetcher,VideoExporter
from src.python_video_engine.content_generator import DEFAULT_STYLE_PROMPTS
from src.python_video_engine.ffmpeg_runtime import get_ffmpeg_path, get_ffprobe_path
from src.python_video_engine.runtime_config import USER_SETTINGS_PATH, cleanup_legacy_secret_cache, get_config_value, get_runtime_config
from src.python_video_engine.network import ProxySettings, check_tcp_connectivity, get_default_log_dir

APP_RUNTIME_DIR = Path.home()/'.jianying_auto_editor'
APP_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _build_scan_progress_adapter(progress, video_idx: int, video_count: int):
    if not progress:
        return None

    def _cb(done: int, total: int, current: str) -> None:
        if total <= 0:
            return
        ratio = done / total
        stage_value = 8 + int(ratio * 12)
        stage_value = max(8, min(24, stage_value))
        progress(stage_value + video_idx * 90 // video_count, f"第 {video_idx+1}/{video_count} 个：正在扫描素材 {done}/{total}（{current}）")

    return _cb

def _build_precheck_progress_adapter(progress, video_idx: int, video_count: int):
    if not progress:
        return None

    def _cb(done: int, total: int, current: str) -> None:
        if total <= 0:
            return
        ratio = done / total
        stage_value = 62 + int(ratio * 18)
        stage_value = max(62, min(80, stage_value))
        progress(stage_value + video_idx * 90 // video_count, f"第 {video_idx+1}/{video_count} 个：预检片段可读性 {done}/{total}（{current}）")

    return _cb


def _load_env_for_runtime() -> None:
    return


def _auto_configure_proxy_from_common_ports() -> None:
    if any(str(os.getenv(k, "")).strip() for k in ("CUSTOM_PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY")):
        return
    for port in (7897, 7890, 10809, 20171):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                proxy = f"http://127.0.0.1:{port}"
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
                os.environ["USE_PROXY"] = "true"
                os.environ["CUSTOM_PROXY_URL"] = proxy
                print(f"[Proxy] 已自动识别本地代理: {proxy}")
                return
        except Exception:
            continue

_load_env_for_runtime()
cleanup_legacy_secret_cache()
_auto_configure_proxy_from_common_ports()

logger.info("[Startup] ffmpeg path: %s", get_ffmpeg_path() or "NOT_FOUND")
logger.info("[Startup] ffprobe path: %s", get_ffprobe_path() or "NOT_FOUND")

def startup_network_check() -> None:
    settings = ProxySettings.from_env()
    if settings.use_proxy and settings.custom_proxy_url:
        return
    ok, detail = check_tcp_connectivity("dashscope.aliyuncs.com", 443, timeout_seconds=3.0)
    if not ok:
        messagebox.showerror(
            "网络异常",
            "无法连接到 AI 服务器，请检查网络或代理设置\n" + "目标：dashscope.aliyuncs.com:443\n" + f"详情：{detail}",
        )


def open_log_folder() -> None:
    try:
        log_dir = get_default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["explorer", str(log_dir)], check=False)
    except Exception as exc:
        messagebox.showerror("打开失败", "无法打开日志文件夹。\n详情：" + str(exc))


if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(errors='replace')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(errors='replace')
ZH_VOICES={'温柔女声':'female_standard','活力男声':'male_dynamic','成熟男声':'male_mature','童声':'child_cute'}; EN_VOICES={'Jenny (Professional Female)':'en-US-JennyNeural','Guy (Narrative Male)':'en-US-GuyNeural','Sonia (Elegant British)':'en-GB-SoniaNeural','Andrew (Business Male)':'en-US-AndrewNeural'}; VOICES={**ZH_VOICES,**EN_VOICES}; targetLanguage='zh'
STYLE_TAG_LIMIT=10
STYLE_PROMPT_CONFIG_PATH=(APP_RUNTIME_DIR/'config'/'style_prompts.json') if getattr(sys,'frozen',False) else (Path(__file__).resolve().parent/'config'/'style_prompts.json')
COMPANY_PROFILE_CANDIDATES=['公司简介.txt','公司介绍.txt','企业简介.txt','company_profile.txt']
BASE=r'Z:\00_客户06105名点工贸_测试'; CLIENT='名点工贸'; SETTINGS=Path.home()/'.jianying_auto_editor_settings.json'
def load_settings():
    try:return json.loads(SETTINGS.read_text(encoding='utf-8')) if SETTINGS.exists() else {}
    except Exception:return {}
def save_settings(d): SETTINGS.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')

def _load_embedded_style_prompts()->dict[str,str]:
    candidates=[]
    meipass=getattr(sys,'_MEIPASS',None)
    if meipass:
        candidates.append(Path(meipass)/'config'/'style_prompts.json')
    candidates.append(Path(__file__).resolve().parent/'config'/'style_prompts.json')
    for p in candidates:
        try:
            if p.exists() and p.is_file():
                payload=json.loads(p.read_text(encoding='utf-8'))
                prompts=payload.get('style_prompts',{}) if isinstance(payload,dict) else {}
                if isinstance(prompts,dict):
                    merged=dict(DEFAULT_STYLE_PROMPTS)
                    for k,v in prompts.items():
                        if k in merged and str(v).strip(): merged[k]=str(v).strip()
                    return merged
        except Exception:
            continue
    return dict(DEFAULT_STYLE_PROMPTS)

def ensure_style_prompt_config()->dict:
    payload={'version':'1.0','updated_at':datetime.now().isoformat(timespec='seconds'),'style_prompts':_load_embedded_style_prompts()}
    result={'config':payload,'recovered':False,'backup_path':''}
    try:
        STYLE_PROMPT_CONFIG_PATH.parent.mkdir(parents=True,exist_ok=True)
        if not STYLE_PROMPT_CONFIG_PATH.exists():
            STYLE_PROMPT_CONFIG_PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            result['config']=payload
            return result
        raw_text=STYLE_PROMPT_CONFIG_PATH.read_text(encoding='utf-8')
        existing=json.loads(raw_text)
        if not isinstance(existing,dict):
            raise ValueError('invalid config root')
        style_prompts=existing.get('style_prompts',{}) if isinstance(existing.get('style_prompts',{}),dict) else {}
        merged=dict(DEFAULT_STYLE_PROMPTS)
        for k,v in style_prompts.items():
            if k in merged and str(v).strip(): merged[k]=str(v).strip()
        existing['style_prompts']=merged
        if 'version' not in existing: existing['version']='1.0'
        existing['updated_at']=datetime.now().isoformat(timespec='seconds')
        STYLE_PROMPT_CONFIG_PATH.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding='utf-8')
        result['config']=existing
        return result
    except Exception:
        backup_path=''
        try:
            if STYLE_PROMPT_CONFIG_PATH.exists():
                backup_path=str(STYLE_PROMPT_CONFIG_PATH.with_name(f"style_prompts.broken.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"))
                shutil.copy2(str(STYLE_PROMPT_CONFIG_PATH),backup_path)
        except Exception:
            backup_path=''
        STYLE_PROMPT_CONFIG_PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        result['config']=payload
        result['recovered']=True
        result['backup_path']=backup_path
        return result

def _upsert_bad_materials(base_path: Path, bad_paths: list[str], reason: str, detail: str) -> None:
    if not bad_paths:
        return
    state_path = base_path / '.python_video_engine_bad_materials.json'
    payload = {}
    if state_path.exists():
        try:
            payload = json.loads(state_path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}

    now = datetime.now().isoformat(timespec='seconds')
    hard_reasons = {'nal_error', 'aac_decode_error', 'timeout_error'}

    for raw in bad_paths:
        key = str(Path(raw).resolve(strict=False))
        prev = payload.get(key, {}) if isinstance(payload, dict) else {}

        prev_soft = int(prev.get('soft_failures', 0) or 0)
        soft_failures = prev_soft + 1

        if reason in hard_reasons:
            effective_reason = reason
        elif reason == 'decode_error':
            effective_reason = 'decode_error' if soft_failures >= 3 else 'transient_error'
        else:
            effective_reason = reason

        payload[key] = {
            'reason': effective_reason,
            'detail': detail[:500],
            'first_seen': str(prev.get('first_seen', now)),
            'last_seen': now,
            'failures': int(prev.get('failures', 0) or 0) + 1,
            'soft_failures': soft_failures,
        }

    _safe_write_json_file(state_path, payload)


def _safe_write_json_file(path: Path, payload: dict) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for _ in range(3):
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8', dir=str(parent), prefix=path.name + '.tmp_') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                tmp_path = Path(f.name)
            os.replace(str(tmp_path), str(path))
            return
        except Exception as exc:
            last_err = exc
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            time.sleep(0.2)
    logger.warning('[State] 写入状态文件失败，已忽略，不影响主流程: %s err=%s', path, last_err)


def _rehabilitate_transient_blacklist(base_path: Path) -> None:
    state_path = base_path / '.python_video_engine_bad_materials.json'
    if not state_path.exists():
        return
    try:
        payload = json.loads(state_path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            return
    except Exception:
        return

    changed = False
    for key, record in list(payload.items()):
        if not isinstance(record, dict):
            continue
        reason = str(record.get('reason', '')).strip().lower()
        if reason == 'decode_error' and int(record.get('soft_failures', 0) or 0) < 3:
            record['reason'] = 'transient_error'
            changed = True

    if changed:
        state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
def infer_client_name(p): return Path(p).expanduser().resolve(strict=False).name.strip() or CLIENT
def check_material(p):
    base = Path(p).expanduser().resolve(strict=False)
    if not base.exists() or not base.is_dir():
        return ['素材目录不存在或不可访问']

    required = ['01_工厂全景与大环境', '02_机器运转与加工细节', '03_成品展示与发货']
    has_all_required_dirs = all((base / name).is_dir() for name in required)
    if has_all_required_dirs:
        return []

    supported_exts = {'.mp4', '.mov', '.m4v', '.avi', '.mkv'}
    has_any_video = any(x.is_file() and x.suffix.lower() in supported_exts for x in base.rglob('*'))
    if has_any_video:
        return []

    return ['未检测到可用视频素材（支持 .mp4/.mov/.m4v/.avi/.mkv）']
def resolve_target_language_by_voice_label(label:str)->str: return 'en' if label in EN_VOICES else 'zh'
def resolve_target_language_by_voice_key(key:str)->str: return 'en' if str(key).startswith('en-') else 'zh'
def detect_company_profile_file(material_path:str)->str:
    base=Path(material_path).expanduser().resolve(strict=False)
    for name in COMPANY_PROFILE_CANDIDATES:
        p=base/name
        if p.exists() and p.is_file():
            return name
    return ''
def move_draft(src,dst_root):
    src=Path(src).resolve(strict=False); dst_root=Path(dst_root).expanduser().resolve(strict=False); dst_root.mkdir(parents=True,exist_ok=True); base=f"{src.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"; dst=dst_root/base; i=1
    while dst.exists(): dst=dst_root/f'{base}_{i}'; i+=1
    moved_dst=Path(shutil.move(str(src),str(dst)))
    return moved_dst
def run_pipeline_mix(base_path,client_name,target_duration_seconds=30,output_dir=None,progress=None,video_count=1):
    import time,random
    _rehabilitate_transient_blacklist(Path(base_path))
    results=[]
    for video_idx in range(video_count):
        if progress: progress(5+video_idx*90//video_count,f'开始生成第 {video_idx+1}/{video_count} 个混剪视频...')
        fetch=MaterialFetcher(progress_callback=_build_scan_progress_adapter(progress, video_idx, video_count)).fetch(base_path=base_path,client_name=client_name)
        if progress: progress(24+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：素材扫描完成，可用 {len(fetch.materials)} 条，开始组装片段...')
        duration_with_variance=target_duration_seconds+random.uniform(-3,3)
        plan=AssemblyEngine(random_seed=(video_idx+1)*1009).assemble(base_path=base_path,client_name=client_name,audio_duration_seconds=duration_with_variance,materials=fetch.materials)
        if progress: progress(60+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：片段组装完成，开始导出 MP4...')
        exporter=VideoExporter(output_dir=output_dir)
        if progress: progress(62+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：开始预检片段可读性...')
        checked_plan, pre_skipped_files = exporter.precheck_plan_clips(plan, progress_callback=_build_precheck_progress_adapter(progress, video_idx, video_count))
        if pre_skipped_files:
            checked_paths = {c.absolute_path for c in checked_plan.clips}
            pre_bad_paths = [c.absolute_path for c in plan.clips if c.absolute_path not in checked_paths]
            _upsert_bad_materials(Path(base_path), pre_bad_paths, reason='decode_error', detail='precheck failed: NAL/decode/AAC error')
        if not checked_plan.clips:
            raise RuntimeError(f'第 {video_idx+1}/{video_count} 个：预检后无可用片段，已跳过该视频。请检查素材质量。')
        if pre_skipped_files and progress:
            progress(80+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：预检已跳过 {len(pre_skipped_files)} 个异常片段，继续导出')
        export_result=exporter.export(assembly_plan=checked_plan,video_index=video_idx+1)
        if export_result.blacklisted_paths:
            _upsert_bad_materials(Path(base_path), export_result.blacklisted_paths, reason='timeout_error', detail='export timed out >15s, auto-skip source file')
        total_skipped_files = sorted(set(pre_skipped_files + (export_result.skipped_files or [])))
        total_skipped_count = len(total_skipped_files)
        if total_skipped_count > 0 and progress:
            progress(86+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：已跳过 {total_skipped_count} 个异常片段，继续导出')
        if progress: progress(90+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：MP4 导出完成')
        results.append({'output_path':export_result.output_path,'duration_seconds':export_result.duration_seconds,'clip_count':export_result.clip_count,'video_index':video_idx+1,'skipped_clip_count':total_skipped_count,'skipped_files':total_skipped_files})
        if video_idx<video_count-1:
            time.sleep(2)
    if progress: progress(100,f'全部完成：已成功生成 {video_count} 个混剪视频')
    return results

def run_pipeline(base_path, client_name, voice_key=None, draft_box=None, progress=None, target_language=None, target_duration=None, video_count=1, style_tags=None):
    tags=[str(x).strip() for x in (style_tags or []) if str(x).strip()]
    if not tags:
        raise RuntimeError('请至少选择 1 个文风标签后再生成。')
    min_ready_materials=max(1,int(get_config_value('scan','min_ready_materials',default=30) or 30))
    generator=ContentGenerator(voice_key=voice_key,target_language=target_language,target_duration=target_duration,random_seed=0)
    fetcher=MaterialFetcher(progress_callback=_build_scan_progress_adapter(progress, 0, 1))
    fetch=fetcher.fetch_ready_then_background(base_path=base_path,client_name=client_name,min_ready_materials=min_ready_materials)
    if len(fetch.materials) < min_ready_materials:
        raise RuntimeError(f'可用素材不足，当前仅 {len(fetch.materials)} 条，未达到最小可开工阈值 {min_ready_materials}。')
    if progress:
        progress(20,f'素材快速扫描完成，可用 {len(fetch.materials)} 条，已达到可开工阈值，继续生成...')

    assembly_plans=[]
    content_results=[]
    total_count=len(tags)

    for video_idx,style_label in enumerate(tags):
        if progress:
            progress(25+video_idx*55//total_count,f'开始生成第 {video_idx+1}/{total_count} 个视频（文风：{style_label}）...')
        try:
            content=generator.generate(base_path=base_path,client_name=client_name,keywords=fetch.keywords,style_label=style_label)
        except Exception as e:
            error_msg=f"第 {video_idx+1}/{total_count} 个视频生成失败: {str(e)}"
            if progress:
                progress(25+video_idx*55//total_count,error_msg)
            raise RuntimeError(error_msg)

        duration_key=str(target_duration).strip()
        max_duration_seconds = 30 if duration_key == '15-30' else (60 if duration_key == '30-60' else None)
        plan=AssemblyEngine(random_seed=(video_idx+1)*1009).assemble(
            base_path=base_path,
            client_name=client_name,
            audio_duration_seconds=content.audio_duration_seconds,
            materials=fetch.materials,
            max_duration_seconds=max_duration_seconds,
        )
        assembly_plans.append(plan)
        content_results.append(content)

        if progress:
            progress(30+(video_idx+1)*55//total_count,f'第 {video_idx+1}/{total_count} 个：文案+配音+片段组装完成，已追加到单例草稿队列')

    if progress:
        progress(88,'所有视频任务已就绪，开始一次性生成单草稿（串烧追加模式）...')

    renderer=DraftRenderer(draft_box_path=draft_box)
    draft=renderer.render_multiple_timelines(assembly_plans=assembly_plans,content_results=content_results,client_name=client_name)

    if progress:
        progress(95,'单草稿已生成，正在移动到剪映草稿箱...')

    exported=str(move_draft(draft.draft_directory,draft_box)) if draft_box else draft.draft_directory

    results=[]
    for video_idx,(style_label,content) in enumerate(zip(tags,content_results),1):
        results.append({
            'script_text':content.script_text,
            'exported_draft_directory':exported,
            'selected_voice_key':voice_key,
            'generated_voice_name':content.voice,
            'target_language':target_language,
            'target_duration':target_duration,
            'video_index':video_idx,
            'style_label':style_label,
        })

    if progress:
        progress(100,f'全部完成：已将 {total_count} 个视频追加到同一个草稿')
    return results

class App:
    def __init__(self):
        cfg=load_settings(); self.root=tk.Tk(); self.root.title('剪映自动剪辑工具'); self.root.geometry('1080x820'); self.root.minsize(1020,780); self.root.configure(bg='#f6f7fb')
        style_cfg_result=ensure_style_prompt_config()
        self.style_config_recovered=bool(style_cfg_result.get('recovered',False))
        self.style_config_backup_path=str(style_cfg_result.get('backup_path','') or '')
        self.draft=tk.StringVar(value=cfg.get('draft_box_path','')); self.mix_output=tk.StringVar(value=cfg.get('mix_output_path','output_videos')); self.material=tk.StringVar(value=BASE); self.client=tk.StringVar(value=CLIENT); self.voice=tk.StringVar(value='温柔女声'); self.duration=tk.StringVar(value='15-30'); self.video_count=tk.IntVar(value=1); self.mode=tk.StringVar(value='draft'); self.lang_text=tk.StringVar(value='当前语种：zh'); self.status=tk.StringVar(value='请选择素材后开始生成'); self.script=tk.StringVar(value='生成文案后显示在这里'); self.output=tk.StringVar(value='生成结果会显示在这里'); self.draft_text=tk.StringVar(); self.mix_output_text=tk.StringVar(); self.progress_text=tk.StringVar(value='0%'); self.progress_value=tk.DoubleVar(value=0); self.buttons=[]; self.steps=[]; self.running=False
        # 文风选择相关
        self.style_keywords=tk.StringVar(value=''); self.selected_style_tags=[]; self.style_display=tk.StringVar(value='请选择文风')
        self._style(); self._ui(); self._refresh_style_preview(); self._refresh_draft(); self._refresh_mix_output(); self._on_voice_changed(); self._show(3); self.root.after(100,self._ensure_draft); self.root.after(200,self._notify_style_config_recovery_if_needed)
    def _style(self):
        s=ttk.Style();
        try:s.theme_use('clam')
        except tk.TclError:pass
        s.configure('P.TFrame',background='#f6f7fb'); s.configure('C.TFrame',background='#ffffff'); s.configure('T1.TLabel',background='#f6f7fb',foreground='#111827',font=('Microsoft YaHei UI',16,'bold')); s.configure('T2.TLabel',background='#f6f7fb',foreground='#6b7280',font=('Microsoft YaHei UI',10)); s.configure('H.TLabel',background='#ffffff',foreground='#111827',font=('Microsoft YaHei UI',12,'bold')); s.configure('B.TLabel',background='#ffffff',foreground='#374151',font=('Microsoft YaHei UI',10)); s.configure('TButton',font=('Microsoft YaHei UI',10),padding=(8,4)); s.configure('TRadiobutton',font=('Microsoft YaHei UI',10)); s.configure('TEntry',padding=(6,4)); s.configure('TCombobox',padding=(4,2)); s.configure('Progress.Horizontal.TProgressbar',thickness=16); s.configure('TLabelframe',background='#ffffff',borderwidth=1,relief='solid'); s.configure('TLabelframe.Label',background='#ffffff',foreground='#374151',font=('Microsoft YaHei UI',10))
    def _ui(self):
        self.root.geometry('1280x760'); self.root.minsize(1180,720)
        w=ttk.Frame(self.root,style='P.TFrame',padding=8); w.pack(fill='both',expand=True); w.columnconfigure(0,weight=1); w.rowconfigure(2,weight=1); w.rowconfigure(3,weight=0)

        h=ttk.Frame(w,style='P.TFrame'); h.grid(row=0,column=0,sticky='ew',pady=(0,4)); h.columnconfigure(0,weight=1)
        ttk.Label(h,text='剪映自动剪辑工具',style='H.TLabel').grid(row=0,column=0,sticky='w')
        btns=ttk.Frame(h,style='P.TFrame'); btns.grid(row=0,column=1,sticky='e')
        ttk.Button(btns,text='文风提示词设置',command=self._open_style_prompt_settings).grid(row=0,column=0,padx=(0,4))
        ttk.Button(btns,text='剪映草稿箱设置',command=self._change_draft).grid(row=0,column=1,padx=(0,4))
        ttk.Button(btns,text='混剪输出设置',command=self._change_mix_output).grid(row=0,column=2,padx=(0,4))
        ttk.Button(btns,text='音频安全缓冲设置',command=self._open_audio_lead_in_settings).grid(row=0,column=3,padx=(0,4))
        ttk.Button(btns,text='打开日志',command=open_log_folder).grid(row=0,column=4)

        self.box=ttk.Frame(w,style='C.TFrame',padding=8); self.box.grid(row=2,column=0,sticky='nsew',pady=(0,4)); self.box.columnconfigure(0,weight=2); self.box.columnconfigure(1,weight=3); self.box.rowconfigure(0,weight=1)
        self.left_panel=ttk.Frame(self.box,style='C.TFrame'); self.left_panel.grid(row=0,column=0,sticky='nsew',padx=(0,6)); self.left_panel.columnconfigure(0,weight=1)
        self.right_panel=ttk.Frame(self.box,style='C.TFrame'); self.right_panel.grid(row=0,column=1,sticky='nsew',padx=(6,0)); self.right_panel.columnconfigure(0,weight=1); self.right_panel.rowconfigure(6,weight=1)

        self.p1=self._page1(); self.p1.grid(row=0,column=0,sticky='ew')
        self.p2=self._page2(); self.p2.grid(row=1,column=0,sticky='nsew',pady=(6,0))

        action_bar=ttk.Frame(self.left_panel,style='C.TFrame'); action_bar.grid(row=2,column=0,sticky='ew',pady=(8,0)); action_bar.columnconfigure(0,weight=1)
        self.generate_button=ttk.Button(action_bar,text='开始生成',command=self._run)
        self.generate_button.grid(row=0,column=0,sticky='w')
        self.buttons=[self.generate_button]

        self.p3=self._page3(); self.p3.grid(row=0,column=0,sticky='nsew')

    def _page1(self):
        f=ttk.LabelFrame(self.left_panel,text='基础输入'); f.columnconfigure(1,weight=1)
        ttk.Label(f,text='素材路径',style='B.TLabel').grid(row=0,column=0,sticky='w',padx=(6,6),pady=(6,4)); ttk.Entry(f,textvariable=self.material).grid(row=0,column=1,sticky='ew',pady=(6,4)); ttk.Button(f,text='浏览',command=self._pick_material).grid(row=0,column=2,padx=(6,6),pady=(6,4))
        ttk.Label(f,text='客户名称',style='B.TLabel').grid(row=1,column=0,sticky='w',padx=(6,6),pady=(2,4)); ttk.Entry(f,textvariable=self.client).grid(row=1,column=1,sticky='ew',pady=(2,4))
        ttk.Label(f,text='剪映草稿箱',style='B.TLabel').grid(row=2,column=0,sticky='w',padx=(6,6),pady=(2,4)); ttk.Label(f,textvariable=self.draft_text,style='B.TLabel').grid(row=2,column=1,columnspan=2,sticky='w',pady=(2,4))
        ttk.Label(f,text='混剪输出',style='B.TLabel').grid(row=3,column=0,sticky='w',padx=(6,6),pady=(2,6)); ttk.Label(f,textvariable=self.mix_output_text,style='B.TLabel').grid(row=3,column=1,columnspan=2,sticky='w',pady=(2,6))
        return f

    def _page2(self):
        f=ttk.LabelFrame(self.left_panel,text='模式与参数'); f.columnconfigure(1,weight=1)

        ttk.Label(f,text='生成模式',style='B.TLabel').grid(row=0,column=0,sticky='w',padx=(6,8),pady=(6,4))
        mode_cell=ttk.Frame(f,style='C.TFrame'); mode_cell.grid(row=0,column=1,sticky='ew',pady=(6,4))
        ttk.Radiobutton(mode_cell,text='完整视频',value='draft',variable=self.mode,command=self._on_mode_changed).grid(row=0,column=0,sticky='w',padx=(0,10))
        ttk.Radiobutton(mode_cell,text='纯混剪',value='mix',variable=self.mode,command=self._on_mode_changed).grid(row=0,column=1,sticky='w')

        ttk.Label(f,text='文风添加',style='B.TLabel').grid(row=1,column=0,sticky='w',padx=(6,8),pady=4)
        style_cell=ttk.Frame(f,style='C.TFrame'); style_cell.grid(row=1,column=1,sticky='ew',pady=4)
        style_options=['实力品控','核心产品','诚邀合作','定制研发','高效交付']
        for idx,style_text in enumerate(style_options): ttk.Button(style_cell,text=style_text,command=lambda k=style_text: self._on_style_toggled(k)).grid(row=0,column=idx,sticky='w',padx=(0,4))

        ttk.Label(f,text='已选文风',style='B.TLabel').grid(row=2,column=0,sticky='w',padx=(6,8),pady=4)
        self.style_preview_box=tk.Frame(f,bg='#eef8ff',relief='solid',bd=1); self.style_preview_box.grid(row=2,column=1,sticky='ew',pady=4)
        self.style_preview_inner=tk.Frame(self.style_preview_box,bg='#eef8ff'); self.style_preview_inner.pack(fill='both',expand=True,padx=4,pady=2)

        self.draft_options_container=ttk.Frame(f,style='C.TFrame'); self.draft_options_container.grid(row=3,column=0,columnspan=2,sticky='ew')
        self.draft_options_container.columnconfigure(1,weight=1)
        ttk.Label(self.draft_options_container,text='声音',style='B.TLabel').grid(row=0,column=0,sticky='w',padx=(6,8),pady=4)
        voice_values=list(ZH_VOICES.keys())+list(EN_VOICES.keys())
        voice_row=ttk.Frame(self.draft_options_container,style='C.TFrame')
        voice_row.grid(row=0,column=1,sticky='w',pady=4)
        voice_cb=ttk.Combobox(voice_row,textvariable=self.voice,values=voice_values,state='readonly',width=32)
        voice_cb.grid(row=0,column=0,sticky='w'); voice_cb.bind('<<ComboboxSelected>>',self._on_voice_changed)
        ttk.Label(voice_row,textvariable=self.lang_text,style='B.TLabel').grid(row=0,column=1,sticky='w',padx=(12,0))

        ttk.Label(self.draft_options_container,text='视频时长',style='B.TLabel').grid(row=1,column=0,sticky='w',padx=(6,8),pady=4)
        dur_cell=ttk.Frame(self.draft_options_container,style='C.TFrame'); dur_cell.grid(row=1,column=1,sticky='w',pady=4)
        ttk.Radiobutton(dur_cell,text='15-30秒',value='15-30',variable=self.duration).grid(row=0,column=0,sticky='w',padx=(0,8))
        ttk.Radiobutton(dur_cell,text='30-60秒',value='30-60',variable=self.duration).grid(row=0,column=1,sticky='w')

        self.mix_options_container=ttk.Frame(f,style='C.TFrame'); self.mix_options_container.grid(row=4,column=0,columnspan=2,sticky='ew')
        ttk.Label(self.mix_options_container,text='混剪数量',style='B.TLabel').grid(row=0,column=0,sticky='w',padx=(6,8),pady=4)
        ttk.Spinbox(self.mix_options_container,from_=1,to=10,textvariable=self.video_count,width=8).grid(row=0,column=1,sticky='w',pady=4)

        self._on_mode_changed(); return f

    def _on_style_toggled(self,keyword):
        if len(self.selected_style_tags) >= STYLE_TAG_LIMIT:
            messagebox.showwarning('提示',f'最多只能添加 {STYLE_TAG_LIMIT} 个文风标签。')
            return
        self.selected_style_tags.append(keyword)
        self._refresh_style_preview()

    def _remove_style_tag(self,index):
        if index<0 or index>=len(self.selected_style_tags):
            return
        self.selected_style_tags.pop(index)
        self._refresh_style_preview()

    def _refresh_style_preview(self):
        for child in self.style_preview_inner.winfo_children():
            child.destroy()

        if not self.selected_style_tags:
            empty_label=tk.Label(self.style_preview_inner,text='请选择文风',bg='#fff3cd',fg='#856404',font=('Microsoft YaHei UI',11))
            empty_label.pack(anchor='w')
            self.style_preview_box.config(bg='#fff3cd')
            self.style_preview_inner.config(bg='#fff3cd')
            return

        self.style_preview_box.config(bg='#eef8ff')
        self.style_preview_inner.config(bg='#eef8ff')

        tag_wrap=tk.Frame(self.style_preview_inner,bg='#eef8ff')
        tag_wrap.pack(anchor='w',fill='x')

        max_cols=4
        for idx,tag in enumerate(self.selected_style_tags):
            r=idx//max_cols
            c=idx%max_cols
            tag_btn=tk.Button(tag_wrap,text=f'{tag} ✕',relief='flat',bd=0,bg='#0ea5e9',fg='white',activebackground='#0284c7',activeforeground='white',font=('Microsoft YaHei UI',10),padx=8,pady=2,cursor='hand2',command=lambda i=idx: self._remove_style_tag(i))
            tag_btn.grid(row=r,column=c,sticky='w',padx=(0,8),pady=4)

    def _page3(self):
        f=ttk.Frame(self.right_panel,style='C.TFrame'); f.columnconfigure(0,weight=1); f.rowconfigure(4,weight=1)
        pw=ttk.Frame(f,style='C.TFrame'); pw.grid(row=1,column=0,sticky='ew',pady=(0,4)); pw.columnconfigure(0,weight=1)
        ttk.Progressbar(pw,mode='determinate',maximum=100,variable=self.progress_value,style='Progress.Horizontal.TProgressbar').grid(row=0,column=0,sticky='ew')
        ttk.Label(pw,textvariable=self.progress_text,style='B.TLabel').grid(row=0,column=1,padx=(8,0))
        ttk.Label(f,textvariable=self.status,style='B.TLabel').grid(row=2,column=0,sticky='w',pady=(0,4))

        log=ttk.LabelFrame(f,text='控制台输出'); log.grid(row=4,column=0,sticky='nsew'); log.columnconfigure(0,weight=1); log.rowconfigure(0,weight=1)
        text=tk.Text(log,height=18,bg='#0b1020',fg='#c9d1d9',insertbackground='#c9d1d9',font=('Consolas',10),wrap='word')
        text.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(log,orient='vertical',command=text.yview); scroll.grid(row=0,column=1,sticky='ns'); text.configure(yscrollcommand=scroll.set)
        ttk.Label(log,text='文案与输出：',style='B.TLabel').grid(row=1,column=0,sticky='w',pady=(4,0))
        preview_wrap=tk.Frame(log,bg='#0b1020',highlightthickness=1,highlightbackground='#30363d')
        preview_wrap.grid(row=2,column=0,columnspan=2,sticky='nsew',pady=(4,0))
        log.rowconfigure(2,weight=1)
        preview_text=tk.Text(preview_wrap,height=8,bg='#0b1020',fg='#c9d1d9',insertbackground='#c9d1d9',font=('Consolas',10),wrap='word',relief='flat',bd=0,padx=8,pady=6)
        preview_text.grid(row=0,column=0,sticky='nsew')
        preview_scroll=ttk.Scrollbar(preview_wrap,orient='vertical',command=preview_text.yview)
        preview_scroll.grid(row=0,column=1,sticky='ns')
        preview_wrap.columnconfigure(0,weight=1); preview_wrap.rowconfigure(0,weight=1)
        preview_text.configure(yscrollcommand=preview_scroll.set)

        preview_menu=tk.Menu(preview_text,tearoff=0)

        def _copy_preview_text():
            try:
                selected=preview_text.selection_get()
            except Exception:
                selected=''
            if not selected:
                selected=preview_text.get('1.0','end-1c')
            if selected:
                self.root.clipboard_clear()
                self.root.clipboard_append(selected)
            preview_menu.unpost()

        def _select_all_preview_text():
            preview_text.tag_add('sel','1.0','end-1c')
            preview_text.mark_set('insert','1.0')
            preview_text.see('insert')
            preview_menu.unpost()

        def _deselect_preview_text():
            preview_text.tag_remove('sel','1.0','end')
            preview_menu.unpost()

        def _show_preview_menu(event):
            try:
                preview_menu.tk_popup(event.x_root,event.y_root)
            finally:
                preview_menu.grab_release()
            return 'break'

        def _hide_preview_menu(_event=None):
            try:
                preview_menu.unpost()
            except Exception:
                pass

        preview_menu.add_command(label='复制 (Copy)',command=_copy_preview_text)
        preview_menu.add_command(label='全选 (Select All)',command=_select_all_preview_text)
        preview_menu.add_command(label='取消选择 (Deselect)',command=_deselect_preview_text)

        preview_text.bind('<Button-3>',_show_preview_menu)
        preview_text.bind('<FocusOut>',_hide_preview_menu)
        self.root.bind('<Button-1>',_hide_preview_menu,add='+')

        text.tag_configure('ansi_info',foreground='#7ee787')
        text.tag_configure('ansi_warn',foreground='#ffd866')
        text.tag_configure('ansi_err',foreground='#ff7b72')
        text.tag_configure('ansi_dim',foreground='#8b949e')

        def _sync_console(*_):
            text.delete('1.0','end')
            header=f"[{self.progress_text.get()}] {self.status.get()}\n"
            text.insert('end',header,'ansi_info')
            text.insert('end','-'*72+'\n','ansi_dim')
            out=self.output.get().strip()
            if out:
                for line in out.splitlines():
                    lower=line.lower()
                    if ('失败' in line) or ('error' in lower) or ('异常' in line):
                        text.insert('end',line+'\n','ansi_err')
                    elif ('跳过' in line) or ('warning' in lower) or ('warn' in lower):
                        text.insert('end',line+'\n','ansi_warn')
                    else:
                        text.insert('end',line+'\n')
            else:
                text.insert('end','生成结果会显示在这里\n','ansi_dim')
            text.see('end')

            preview_text.config(state='normal')
            preview_text.delete('1.0','end')
            preview_text.insert('end','文案：\n')
            preview_text.insert('end',(self.script.get() or '生成文案后显示在这里')+'\n\n')
            preview_text.insert('end','输出：\n')
            preview_text.insert('end',(self.output.get() or '生成结果会显示在这里')+'\n')
            preview_text.config(state='disabled')
        self.status.trace_add('write',_sync_console); self.output.trace_add('write',_sync_console); self.progress_text.trace_add('write',_sync_console); self.script.trace_add('write',_sync_console); _sync_console()
        return f
    def _on_voice_changed(self,*_):
        global targetLanguage
        targetLanguage=resolve_target_language_by_voice_label(self.voice.get().strip()); self.lang_text.set(f'当前语种：{targetLanguage}')
    def _on_mode_changed(self):
        is_draft_mode=self.mode.get()=='draft'
        if hasattr(self,'draft_options_container'):
            try:
                if is_draft_mode:
                    self.draft_options_container.grid()
                else:
                    self.draft_options_container.grid_remove()
            except Exception:
                pass
        if hasattr(self,'mix_options_container'):
            try:
                if not is_draft_mode:
                    self.mix_options_container.grid()
                else:
                    self.mix_options_container.grid_remove()
            except Exception:
                pass
    def _refresh_draft(self): self.draft_text.set(self.draft.get().strip() or '未设置。首次使用请先设置，之后应用会自动记住。')
    def _refresh_mix_output(self): self.mix_output_text.set(self.mix_output.get().strip() or 'output_videos（默认）')
    def _set_progress(self,v,t): v=max(0,min(100,int(v))); self.progress_value.set(v); self.progress_text.set(f'{v}%'); self.status.set(t)
    def _pick_material(self):
        v=filedialog.askdirectory(title='选择素材目录')
        if v:
            self.material.set(v); self.client.set(infer_client_name(v))
            profile_name=detect_company_profile_file(v)
            if profile_name:
                self.status.set(f'已识别公司简介文件：{profile_name}')
            else:
                self.status.set('未检测到公司简介文件（可选：公司简介.txt/公司介绍.txt/企业简介.txt/company_profile.txt）')
    def _change_draft(self):
        v=filedialog.askdirectory(title='选择剪映草稿箱路径')
        if v: self.draft.set(v); cfg=load_settings(); cfg['draft_box_path']=v; save_settings(cfg); self._refresh_draft(); self.status.set('草稿箱路径已保存，下次打开会自动记住')
    def _change_mix_output(self):
        v=filedialog.askdirectory(title='选择混剪视频输出路径')
        if v: self.mix_output.set(v); cfg=load_settings(); cfg['mix_output_path']=v; save_settings(cfg); self._refresh_mix_output(); self.status.set('混剪输出路径已保存，下次打开会自动记住')
    def _open_audio_lead_in_settings(self):
        current_start=float(get_config_value('draft','audio_buffer_start',default=0.1) or 0.1)
        current_end=float(get_config_value('draft','audio_buffer_end',default=0.1) or 0.1)
        win=tk.Toplevel(self.root); win.title('音频安全缓冲设置'); win.geometry('560x280'); win.configure(bg='#f6f7fb')
        frame=ttk.Frame(win,padding=16); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='音频安全缓冲设置',style='H.TLabel').grid(row=0,column=0,columnspan=2,sticky='w')
        ttk.Label(frame,text='建议范围：0.0 ~ 1.0。该值会让每段音频相对视频画面前后延后或缩进对应秒数。',style='B.TLabel',wraplength=500,justify='left').grid(row=1,column=0,columnspan=2,sticky='w',pady=(8,14))

        ttk.Label(frame,text='音频开头缓冲（秒）',style='B.TLabel').grid(row=2,column=0,sticky='w',pady=(0,8))
        start_var=tk.StringVar(value=f'{current_start:.2f}')
        ttk.Entry(frame,textvariable=start_var,width=16).grid(row=2,column=1,sticky='w',ipady=6,pady=(0,8))

        ttk.Label(frame,text='音频结尾缓冲（秒）',style='B.TLabel').grid(row=3,column=0,sticky='w')
        end_var=tk.StringVar(value=f'{current_end:.2f}')
        ttk.Entry(frame,textvariable=end_var,width=16).grid(row=3,column=1,sticky='w',ipady=6)

        foot=ttk.Frame(frame); foot.grid(row=4,column=0,columnspan=2,sticky='ew',pady=(18,0)); foot.columnconfigure(0,weight=1)

        def _parse_value(raw:str)->float|None:
            try:
                value=float(raw.strip())
            except Exception:
                return None
            if value<0.0 or value>1.0:
                return None
            return value

        def _save():
            start_value=_parse_value(start_var.get())
            end_value=_parse_value(end_var.get())
            if start_value is None or end_value is None:
                messagebox.showwarning('提示','请输入 0.0 到 1.0 之间的合法数字（例如 0.10）。')
                return

            cfg=USER_SETTINGS_PATH
            existing={}
            if cfg.exists():
                try:
                    existing=json.loads(cfg.read_text(encoding='utf-8'))
                    if not isinstance(existing,dict):
                        existing={}
                except Exception:
                    existing={}

            draft_obj=existing.get('draft',{}) if isinstance(existing.get('draft',{}),dict) else {}
            draft_obj['audio_buffer_start']=round(start_value,3)
            draft_obj['audio_buffer_end']=round(end_value,3)
            existing['draft']=draft_obj
            cfg.parent.mkdir(parents=True,exist_ok=True)
            cfg.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding='utf-8')
            try:
                get_runtime_config.cache_clear()
            except Exception:
                pass
            self.status.set(f'音频安全缓冲已保存：开头 {round(start_value,3)} 秒，结尾 {round(end_value,3)} 秒（下次生成生效）')
            messagebox.showinfo('完成',f'已保存音频安全缓冲：\n开头 {round(start_value,3)} 秒\n结尾 {round(end_value,3)} 秒')
            win.destroy()

        def _reset_defaults():
            start_var.set('0.10')
            end_var.set('0.10')

        ttk.Button(foot,text='恢复默认',command=_reset_defaults).grid(row=0,column=0,sticky='w')
        ttk.Button(foot,text='保存',command=_save).grid(row=0,column=1,sticky='e')

    def _open_style_prompt_settings(self):
        cfg_result=ensure_style_prompt_config()
        cfg=cfg_result.get('config',{}) if isinstance(cfg_result,dict) else {}
        prompts=cfg.get('style_prompts',{}) if isinstance(cfg,dict) else {}
        if isinstance(cfg_result,dict) and cfg_result.get('recovered'):
            backup_path=str(cfg_result.get('backup_path','') or '')
            tip='文风提示词配置异常，已自动恢复为默认模板。'
            if backup_path: tip+=f'\n已备份原文件：{backup_path}'
            messagebox.showwarning('配置已修复',tip)
        win=tk.Toplevel(self.root); win.title('文风提示词设置'); win.geometry('900x640'); win.configure(bg='#f6f7fb')
        frame=ttk.Frame(win,padding=16); frame.pack(fill='both',expand=True)
        frame.columnconfigure(0,weight=1); frame.rowconfigure(0,weight=1)
        text=tk.Text(frame,wrap='word',font=('Consolas',11),undo=True)
        text.grid(row=0,column=0,sticky='nsew')
        content='\n\n'.join([f'## {k}\n{prompts.get(k,"")}' for k in DEFAULT_STYLE_PROMPTS.keys()])
        text.insert('1.0',content)
        foot=ttk.Frame(frame); foot.grid(row=1,column=0,sticky='ew',pady=(10,0)); foot.columnconfigure(0,weight=1)
        def _parse_text(raw:str)->dict:
            result={k:'' for k in DEFAULT_STYLE_PROMPTS.keys()}; current=None
            for line in raw.splitlines():
                if line.startswith('## '):
                    key=line[3:].strip(); current=key if key in result else None
                    continue
                if current is not None:
                    result[current]=(result[current]+'\n'+line).strip() if result[current] else line
            for k,v in list(result.items()):
                if not str(v).strip(): result[k]=DEFAULT_STYLE_PROMPTS[k]
            return result
        def _save():
            parsed=_parse_text(text.get('1.0','end').strip())
            payload={'version':'1.0','updated_at':datetime.now().isoformat(timespec='seconds'),'style_prompts':parsed}
            STYLE_PROMPT_CONFIG_PATH.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            messagebox.showinfo('完成','提示词配置已保存。')
        def _reset():
            text.delete('1.0','end')
            text.insert('1.0','\n\n'.join([f'## {k}\n{v}' for k,v in DEFAULT_STYLE_PROMPTS.items()]))
        ttk.Button(foot,text='恢复默认',command=_reset).grid(row=0,column=0,sticky='w')
        ttk.Button(foot,text='保存',command=_save).grid(row=0,column=1,sticky='e')
    def _notify_style_config_recovery_if_needed(self):
        if not getattr(self,'style_config_recovered',False):
            return
        tip='文风提示词配置异常，已自动恢复为默认模板。'
        if getattr(self,'style_config_backup_path',''):
            tip+=f'\n已备份原文件：{self.style_config_backup_path}'
        messagebox.showwarning('配置已修复',tip)

    def _ensure_draft(self):
        return
    def _show(self,n):
        return
    def _go2(self):
        return
    def _set_busy(self,b): self.running=b; [x.configure(state='disabled' if b else 'normal') for x in self.buttons]
    def _report_progress(self,v,t): self.root.after(0,lambda:self._set_progress(v,t))
    def _run(self):
        if self.running: return
        mode=self.mode.get()
        if mode=='draft' and not all([self.draft.get().strip(),self.material.get().strip(),self.client.get().strip(),self.voice.get().strip()]): messagebox.showwarning('提示','请先完成前面步骤。'); return
        if mode=='draft' and len(self.selected_style_tags)==0: messagebox.showwarning('提示','请至少选择 1 个文风标签。'); return
        if mode=='mix' and not all([self.mix_output.get().strip(),self.material.get().strip(),self.client.get().strip()]): messagebox.showwarning('提示','请先完成前面步骤。'); return
        self._set_busy(True); self._set_progress(1,'准备开始...'); self.script.set('正在生成，请稍候...'); self.output.set('正在处理...'); threading.Thread(target=self._worker,daemon=True).start()
    def _worker(self):
        try:
            mode=self.mode.get(); count=max(1,min(10,self.video_count.get()))
            if mode=='mix':
                duration_range=self.duration.get().strip(); target_seconds=45 if duration_range=='30-60' else 22.5
                r=run_pipeline_mix(Path(self.material.get()),self.client.get().strip(),target_duration_seconds=target_seconds,output_dir=self.mix_output.get().strip(),progress=self._report_progress,video_count=count)
                self.root.after(0,lambda:self._ok_mix(r))
            else:
                selected=self.voice.get().strip(); lang=resolve_target_language_by_voice_label(selected); duration=self.duration.get().strip(); style_tags=list(self.selected_style_tags)
                r=run_pipeline(Path(self.material.get()),self.client.get().strip(),VOICES[selected],Path(self.draft.get()),progress=self._report_progress,target_language=lang,target_duration=duration,style_tags=style_tags)
                self.root.after(0,lambda:self._ok(r))
        except Exception as e:
            err_msg=str(e)
            self.root.after(0,lambda msg=err_msg:self._fail(msg))
    def _ok(self,r):
        self._set_busy(False); self._set_progress(100,f'已完成：已生成 {len(r)} 个视频草稿');
        if isinstance(r,list) and len(r)>0:
            scripts='\n\n---\n\n'.join([f"视频 {i+1}:\n{item.get('script_text','')}" for i,item in enumerate(r)])
            outputs='\n'.join([f"视频 {i+1}: {item.get('exported_draft_directory','')}" for i,item in enumerate(r)])
            self.script.set(scripts); self.output.set(outputs)
            messagebox.showinfo('完成',f'已成功生成 {len(r)} 个视频草稿。')
        else:
            self.script.set(str(r.get('script_text') or '')); self.output.set(f"已移动到：{r.get('exported_draft_directory')}")
            messagebox.showinfo('完成','草稿已生成并移动完成。')
    def _ok_mix(self,r):
        self._set_busy(False); self._set_progress(100,f'已完成：已生成 {len(r)} 个混剪视频')
        self.script.set('混剪模式：无文案')
        outputs='\n'.join([f"视频 {i+1}: {item.get('output_path','')} (时长: {item.get('duration_seconds',0):.1f}秒, 片段数: {item.get('clip_count',0)}, 跳过: {item.get('skipped_clip_count',0)})" for i,item in enumerate(r)])
        self.output.set(outputs)

        total_skipped=sum(int(item.get('skipped_clip_count',0) or 0) for item in r)
        skipped_files=[]
        for item in r:
            skipped_files.extend(item.get('skipped_files',[]) or [])
        skipped_files=sorted(set(skipped_files))

        if total_skipped>0:
            preview='、'.join(skipped_files[:5]) if skipped_files else '（文件名不可用）'
            suffix='...' if len(skipped_files)>5 else ''
            messagebox.showwarning('完成（已剔除坏素材）',f'已成功生成 {len(r)} 个混剪视频。\n已剔除坏素材：{preview}{suffix}\n共剔除 {total_skipped} 个异常片段。')
        else:
            messagebox.showinfo('完成',f'已成功生成 {len(r)} 个混剪视频。')
    def _fail(self,msg): self._set_busy(False); self.status.set('生成失败，请检查路径、网络或素材结构'); self.output.set(msg); self.script.set('生成失败。'); self.progress_text.set('失败'); messagebox.showerror('生成失败',msg)
    def run(self): self.root.mainloop()
def parse_args():
    p=argparse.ArgumentParser(description='Run local auto-edit pipeline'); p.add_argument('--base-path',default=BASE); p.add_argument('--client-name',default=CLIENT); p.add_argument('--voice',default='female_standard'); p.add_argument('--draft-box-path',default=''); p.add_argument('--json',dest='json_output',action='store_true'); p.add_argument('--gui',action='store_true'); return p.parse_args()
def main():
    logger.info("=" * 60)
    logger.info("剪映自动剪辑工具 v0.1.2")
    logger.info("=" * 60)
    a=parse_args(); cfg=load_settings(); draft=a.draft_box_path or cfg.get('draft_box_path','')
    if a.gui or len(sys.argv)==1:
        logger.info("启动 GUI 模式...")
        App().run()
        return
    logger.info("启动 CLI 模式...")
    lang=resolve_target_language_by_voice_key(a.voice)
    r=run_pipeline(Path(a.base_path),a.client_name,a.voice,Path(draft) if draft else None,target_language=lang)
    if a.json_output: print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__': main()
