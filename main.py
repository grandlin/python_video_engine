from __future__ import annotations
import argparse,json,os,shutil,socket,sys,threading,tkinter as tk,logging
import subprocess
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from pprint import pprint
from tkinter import filedialog,messagebox,ttk
from dotenv import load_dotenv

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
from src.python_video_engine.network import ProxySettings, check_tcp_connectivity, get_default_log_dir


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
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / ".env")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / ".env")
    else:
        candidates.append(Path(__file__).resolve().parent / ".env")
    candidates.append(Path.cwd() / ".env")
    for p in candidates:
        load_dotenv(p, override=False)


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
_auto_configure_proxy_from_common_ports()

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
BASE=r'Z:\00_客户06105名点工贸_测试'; CLIENT='名点工贸'; SETTINGS=Path.home()/'.jianying_auto_editor_settings.json'
def load_settings():
    try:return json.loads(SETTINGS.read_text(encoding='utf-8')) if SETTINGS.exists() else {}
    except Exception:return {}
def save_settings(d): SETTINGS.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')

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

    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


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

    has_any_mp4 = any(x.is_file() and x.suffix.lower() == '.mp4' for x in base.rglob('*'))
    if has_any_mp4:
        return []

    return ['未检测到可用 mp4 素材（可使用三分类目录，或直接在单目录放 mp4）']
def resolve_target_language_by_voice_label(label:str)->str: return 'en' if label in EN_VOICES else 'zh'
def resolve_target_language_by_voice_key(key:str)->str: return 'en' if str(key).startswith('en-') else 'zh'
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
    import time
    results=[]
    for video_idx in range(video_count):
        if progress: progress(5+video_idx*90//video_count,f'开始生成第 {video_idx+1}/{video_count} 个视频...')
        fetch=MaterialFetcher().fetch(base_path=base_path,client_name=client_name)
        if progress: progress(15+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：素材扫描完成，共 {len(fetch.materials)} 条，开始生成文案与配音...')
        try:
            content=ContentGenerator(voice_key=voice_key,target_language=target_language,target_duration=target_duration,random_seed=video_idx).generate(base_path=base_path,client_name=client_name,keywords=fetch.keywords)
        except Exception as e:
            error_msg=f"第 {video_idx+1}/{video_count} 个视频生成失败: {str(e)}"
            if progress: progress(5+video_idx*90//video_count,error_msg)
            raise RuntimeError(error_msg)
        if progress: progress(45+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：配音完成，开始组装片段...')
        plan=AssemblyEngine(random_seed=(video_idx+1)*1009).assemble(base_path=base_path,client_name=client_name,audio_duration_seconds=content.audio_duration_seconds,materials=fetch.materials)
        if progress: progress(70+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：片段组装完成，开始生成剪映草稿...')
        draft=DraftRenderer(draft_box_path=draft_box).render(assembly_plan=plan,content_result=content)
        if progress: progress(85+video_idx*90//video_count,f'第 {video_idx+1}/{video_count} 个：草稿已生成，正在移动到剪映草稿箱...')
        exported=str(move_draft(draft.draft_directory,draft_box)) if draft_box else draft.draft_directory
        results.append({'script_text':content.script_text,'exported_draft_directory':exported,'selected_voice_key':voice_key,'generated_voice_name':content.voice,'target_language':target_language,'target_duration':target_duration,'video_index':video_idx+1})
        if video_idx<video_count-1:
            time.sleep(5)
    if progress: progress(100,f'全部完成：已成功生成 {video_count} 个视频草稿')
    return results
class App:
    def __init__(self):
        cfg=load_settings(); self.root=tk.Tk(); self.root.title('剪映自动剪辑工具'); self.root.geometry('1080x820'); self.root.minsize(1020,780); self.root.configure(bg='#f6f7fb')
        self.draft=tk.StringVar(value=cfg.get('draft_box_path','')); self.mix_output=tk.StringVar(value=cfg.get('mix_output_path','output_videos')); self.material=tk.StringVar(value=BASE); self.client=tk.StringVar(value=CLIENT); self.voice=tk.StringVar(value='温柔女声'); self.duration=tk.StringVar(value='30-60'); self.video_count=tk.IntVar(value=1); self.mode=tk.StringVar(value='draft'); self.lang_text=tk.StringVar(value='当前语种：zh'); self.status=tk.StringVar(value='请选择素材后开始生成'); self.script=tk.StringVar(value='生成文案后显示在这里'); self.output=tk.StringVar(value='生成结果会显示在这里'); self.draft_text=tk.StringVar(); self.mix_output_text=tk.StringVar(); self.progress_text=tk.StringVar(value='0%'); self.progress_value=tk.DoubleVar(value=0); self.buttons=[]; self.steps=[]; self.running=False; self._style(); self._ui(); self._refresh_draft(); self._refresh_mix_output(); self._on_voice_changed(); self._show(1); self.root.after(100,self._ensure_draft)
    def _style(self):
        s=ttk.Style();
        try:s.theme_use('clam')
        except tk.TclError:pass
        s.configure('P.TFrame',background='#f6f7fb'); s.configure('C.TFrame',background='#ffffff'); s.configure('T1.TLabel',background='#f6f7fb',foreground='#111827',font=('Microsoft YaHei UI',24,'bold')); s.configure('T2.TLabel',background='#f6f7fb',foreground='#6b7280',font=('Microsoft YaHei UI',11)); s.configure('H.TLabel',background='#ffffff',foreground='#111827',font=('Microsoft YaHei UI',15,'bold')); s.configure('B.TLabel',background='#ffffff',foreground='#374151',font=('Microsoft YaHei UI',11)); s.configure('Progress.Horizontal.TProgressbar',thickness=18); s.configure('TLabelframe',background='#ffffff',borderwidth=1,relief='solid'); s.configure('TLabelframe.Label',background='#ffffff',foreground='#374151',font=('Microsoft YaHei UI',10))
    def _ui(self):
        w=ttk.Frame(self.root,style='P.TFrame',padding=24); w.pack(fill='both',expand=True); w.columnconfigure(0,weight=1); w.rowconfigure(3,weight=1)
        h=ttk.Frame(w,style='P.TFrame'); h.grid(row=0,column=0,sticky='ew'); h.columnconfigure(0,weight=1); ttk.Label(h,text='剪映自动剪辑工具',style='T1.TLabel').grid(row=0,column=0,sticky='w'); btns=ttk.Frame(h,style='P.TFrame'); btns.grid(row=0,column=1,sticky='e'); ttk.Button(btns,text='草稿箱设置',command=self._change_draft).grid(row=0,column=0,padx=(0,10)); ttk.Button(btns,text='混剪输出设置',command=self._change_mix_output).grid(row=0,column=1,padx=(0,10)); ttk.Button(btns,text='打开日志',command=open_log_folder).grid(row=0,column=2); ttk.Label(h,text='素材选择 > 模式设置 > 生成视频',style='T2.TLabel').grid(row=1,column=0,sticky='w',pady=(6,0))
        c=ttk.Frame(w,style='C.TFrame',padding=14); c.grid(row=1,column=0,sticky='ew',pady=(16,0)); c.columnconfigure(0,weight=1); ttk.Label(c,text='当前剪映草稿箱',style='H.TLabel').grid(row=0,column=0,sticky='w'); ttk.Label(c,textvariable=self.draft_text,style='B.TLabel',wraplength=920).grid(row=1,column=0,sticky='w',pady=(8,0)); ttk.Label(c,text='当前混剪输出路径',style='H.TLabel').grid(row=2,column=0,sticky='w',pady=(12,0)); ttk.Label(c,textvariable=self.mix_output_text,style='B.TLabel',wraplength=920).grid(row=3,column=0,sticky='w',pady=(8,0))
        bar=ttk.Frame(w,style='C.TFrame',padding=18); bar.grid(row=2,column=0,sticky='ew',pady=(18,0))
        for i,t in enumerate(['素材选择','模式设置','生成视频'],1): bar.columnconfigure(i,weight=1); f=ttk.Frame(bar,style='C.TFrame'); f.grid(row=0,column=i,sticky='ew',padx=18); cv=tk.Canvas(f,width=44,height=44,bg='#ffffff',highlightthickness=0); ov=cv.create_oval(2,2,42,42,fill='#e5e7eb',outline=''); cv.create_text(22,22,text=str(i),fill='#6b7280',font=('Microsoft YaHei UI',12,'bold')); cv.pack(); lb=ttk.Label(f,text=t,style='B.TLabel'); lb.pack(pady=(8,0)); self.steps.append((cv,ov,lb))
        self.box=ttk.Frame(w,style='C.TFrame',padding=24); self.box.grid(row=3,column=0,sticky='nsew',pady=(18,0)); self.box.columnconfigure(0,weight=1); self.box.rowconfigure(0,weight=1)
        self.p1=self._page1(); self.p2=self._page2(); self.p3=self._page3(); [p.grid(row=0,column=0,sticky='nsew') for p in [self.p1,self.p2,self.p3]]
    def _page1(self):
        f=ttk.Frame(self.box,style='C.TFrame'); f.columnconfigure(0,weight=1); ttk.Label(f,text='1. 选择素材路径',style='H.TLabel').grid(row=0,column=0,sticky='w'); r=ttk.Frame(f,style='C.TFrame'); r.grid(row=1,column=0,sticky='ew',pady=(16,0)); r.columnconfigure(0,weight=1); ttk.Entry(r,textvariable=self.material).grid(row=0,column=0,sticky='ew',ipady=8,padx=(0,10)); ttk.Button(r,text='浏览素材',command=self._pick_material).grid(row=0,column=1); n=ttk.Frame(f,style='C.TFrame'); n.grid(row=2,column=0,sticky='ew',pady=(16,0)); n.columnconfigure(1,weight=1); ttk.Label(n,text='客户名称',style='B.TLabel').grid(row=0,column=0,padx=(0,10)); ttk.Entry(n,textvariable=self.client).grid(row=0,column=1,sticky='ew',ipady=8); b=ttk.Button(f,text='下一步',command=self._go2); b.grid(row=3,column=0,sticky='e',pady=(24,0)); self.buttons=[b]; return f
    def _page2(self):
        f=ttk.Frame(self.box,style='C.TFrame'); f.columnconfigure(0,weight=1); f.rowconfigure(0,weight=1)
        canvas=tk.Canvas(f,bg='#ffffff',highlightthickness=0); canvas.grid(row=0,column=0,sticky='nsew'); scrollbar=ttk.Scrollbar(f,orient='vertical',command=canvas.yview); scrollbar.grid(row=0,column=1,sticky='ns'); canvas.configure(yscrollcommand=scrollbar.set)
        scroll_frame=ttk.Frame(canvas,style='C.TFrame'); canvas_window=canvas.create_window((0,0),window=scroll_frame,anchor='nw')
        def _configure_scroll(event): canvas.configure(scrollregion=canvas.bbox('all')); canvas.itemconfig(canvas_window,width=event.width)
        def _on_mousewheel(event): canvas.yview_scroll(int(-1*(event.delta/120)),'units')
        scroll_frame.bind('<Configure>',_configure_scroll); canvas.bind('<Configure>',_configure_scroll); canvas.bind_all('<MouseWheel>',_on_mousewheel)
        ttk.Label(scroll_frame,text='2. 选择模式与参数',style='H.TLabel').grid(row=0,column=0,sticky='w',padx=24,pady=(12,0))
        mode_box=ttk.LabelFrame(scroll_frame,text='生成模式'); mode_box.grid(row=1,column=0,sticky='ew',pady=(12,0),padx=24); mode_frame=ttk.Frame(mode_box,style='C.TFrame'); mode_frame.pack(pady=8,padx=8); ttk.Radiobutton(mode_frame,text='完整视频模式（文案+配音+剪映草稿）',value='draft',variable=self.mode,command=self._on_mode_changed).grid(row=0,column=0,sticky='w',pady=5); ttk.Radiobutton(mode_frame,text='纯混剪模式（无文案无配音，直接MP4）',value='mix',variable=self.mode,command=self._on_mode_changed).grid(row=1,column=0,sticky='w',pady=5)
        self.voice_container=ttk.Frame(scroll_frame,style='C.TFrame'); self.voice_container.grid(row=2,column=0,sticky='ew',pady=(12,0),padx=24); ttk.Label(self.voice_container,text='声音选择（仅完整视频模式）',style='H.TLabel').grid(row=0,column=0,sticky='w',pady=(0,8)); voice_inner=ttk.Frame(self.voice_container,style='C.TFrame'); voice_inner.grid(row=1,column=0,sticky='ew'); voice_inner.columnconfigure(0,weight=1); voice_inner.columnconfigure(1,weight=1); zh_box=ttk.LabelFrame(voice_inner,text='中文声音 (zh-CN)'); zh_box.grid(row=0,column=0,sticky='nsew',padx=(0,10)); [ttk.Radiobutton(zh_box,text=k,value=k,variable=self.voice,command=self._on_voice_changed).grid(row=i,column=0,sticky='w',pady=8,padx=8) for i,k in enumerate(ZH_VOICES)]; en_box=ttk.LabelFrame(voice_inner,text='English Voices'); en_box.grid(row=0,column=1,sticky='nsew',padx=(10,0)); [ttk.Radiobutton(en_box,text=k,value=k,variable=self.voice,command=self._on_voice_changed).grid(row=i,column=0,sticky='w',pady=8,padx=8) for i,k in enumerate(EN_VOICES)]; ttk.Label(self.voice_container,textvariable=self.lang_text,style='B.TLabel').grid(row=2,column=0,sticky='w',pady=(10,0))
        settings_container=ttk.Frame(scroll_frame,style='C.TFrame'); settings_container.grid(row=3,column=0,sticky='ew',pady=(12,0),padx=24); settings_container.columnconfigure(0,weight=1); settings_container.columnconfigure(1,weight=1); duration_box=ttk.LabelFrame(settings_container,text='视频时长'); duration_box.grid(row=0,column=0,sticky='nsew',padx=(0,10)); dur_frame=ttk.Frame(duration_box,style='C.TFrame'); dur_frame.pack(pady=8,padx=8); ttk.Radiobutton(dur_frame,text='15-30秒',value='15-30',variable=self.duration).grid(row=0,column=0,padx=10,pady=5); ttk.Radiobutton(dur_frame,text='30-60秒',value='30-60',variable=self.duration).grid(row=0,column=1,padx=10,pady=5); count_box=ttk.LabelFrame(settings_container,text='生成数量'); count_box.grid(row=0,column=1,sticky='nsew',padx=(10,0)); count_frame=ttk.Frame(count_box,style='C.TFrame'); count_frame.pack(pady=8,padx=8); ttk.Label(count_frame,text='生成视频数量:',style='B.TLabel').grid(row=0,column=0,padx=(0,10)); count_spinbox=ttk.Spinbox(count_frame,from_=1,to=10,textvariable=self.video_count,width=10); count_spinbox.grid(row=0,column=1)
        foot=ttk.Frame(scroll_frame,style='C.TFrame'); foot.grid(row=4,column=0,sticky='ew',pady=(24,12),padx=24); foot.columnconfigure(1,weight=1); b1=ttk.Button(foot,text='上一步',command=lambda:self._show(1)); b2=ttk.Button(foot,text='下一步',command=lambda:self._show(3)); b1.grid(row=0,column=0,sticky='w'); b2.grid(row=0,column=1,sticky='e'); self.buttons=[b1,b2]; self._on_mode_changed(); return f
    def _page3(self):
        f=ttk.Frame(self.box,style='C.TFrame'); f.columnconfigure(0,weight=1); top=ttk.Frame(f,style='C.TFrame'); top.grid(row=0,column=0,sticky='ew',pady=(0,12)); top.columnconfigure(0,weight=3); top.columnconfigure(1,weight=2); top.columnconfigure(2,weight=2); top.columnconfigure(3,weight=3); b1=ttk.Button(top,text='上一步',command=lambda:self._show(2)); b2=ttk.Button(top,text='生成草稿',command=self._run); b1.grid(row=0,column=1,sticky='w'); b2.grid(row=0,column=2,sticky='e'); self.buttons=[b1,b2]; ttk.Label(f,text='3. 生成草稿',style='H.TLabel').grid(row=1,column=0,sticky='w'); self.summary=ttk.Label(f,text='-',style='B.TLabel',wraplength=900,justify='left'); self.summary.grid(row=2,column=0,sticky='w',pady=(8,16)); pw=ttk.Frame(f,style='C.TFrame'); pw.grid(row=3,column=0,sticky='ew'); pw.columnconfigure(0,weight=1); ttk.Progressbar(pw,mode='determinate',maximum=100,variable=self.progress_value,style='Progress.Horizontal.TProgressbar').grid(row=0,column=0,sticky='ew'); ttk.Label(pw,textvariable=self.progress_text,style='B.TLabel').grid(row=0,column=1,padx=(12,0)); ttk.Label(f,textvariable=self.status,style='B.TLabel').grid(row=4,column=0,sticky='w',pady=(10,18)); ttk.Label(f,text='文案预览',style='H.TLabel').grid(row=5,column=0,sticky='w'); ttk.Label(f,textvariable=self.script,style='B.TLabel',wraplength=900,justify='left').grid(row=6,column=0,sticky='w',pady=(8,18)); ttk.Label(f,text='草稿输出',style='H.TLabel').grid(row=7,column=0,sticky='w'); ttk.Label(f,textvariable=self.output,style='B.TLabel',wraplength=900,justify='left').grid(row=8,column=0,sticky='w',pady=(8,0)); return f
    def _on_voice_changed(self):
        global targetLanguage
        targetLanguage=resolve_target_language_by_voice_label(self.voice.get().strip()); self.lang_text.set(f'当前语种：{targetLanguage}')
    def _on_mode_changed(self):
        is_draft_mode=self.mode.get()=='draft'
        if hasattr(self,'voice_container'):
            try:
                if is_draft_mode:
                    self.voice_container.grid()
                else:
                    self.voice_container.grid_remove()
            except Exception:
                pass
    def _refresh_draft(self): self.draft_text.set(self.draft.get().strip() or '未设置。首次使用请先设置，之后应用会自动记住。')
    def _refresh_mix_output(self): self.mix_output_text.set(self.mix_output.get().strip() or 'output_videos（默认）')
    def _set_progress(self,v,t): v=max(0,min(100,int(v))); self.progress_value.set(v); self.progress_text.set(f'{v}%'); self.status.set(t)
    def _pick_material(self):
        v=filedialog.askdirectory(title='选择素材目录')
        if v: self.material.set(v); self.client.set(infer_client_name(v))
    def _change_draft(self):
        v=filedialog.askdirectory(title='选择剪映草稿箱路径')
        if v: self.draft.set(v); cfg=load_settings(); cfg['draft_box_path']=v; save_settings(cfg); self._refresh_draft(); self.status.set('草稿箱路径已保存，下次打开会自动记住')
    def _change_mix_output(self):
        v=filedialog.askdirectory(title='选择混剪视频输出路径')
        if v: self.mix_output.set(v); cfg=load_settings(); cfg['mix_output_path']=v; save_settings(cfg); self._refresh_mix_output(); self.status.set('混剪输出路径已保存，下次打开会自动记住')
    def _ensure_draft(self):
        return
    def _show(self,n):
        [self.p1,self.p2,self.p3][n-1].tkraise()
        if n==3:
            mode_text='完整视频模式' if self.mode.get()=='draft' else '纯混剪模式'
            output_path=self.draft.get() if self.mode.get()=='draft' else self.mix_output.get()
            self.summary.config(text=f'生成模式：{mode_text}\n输出路径：{output_path or "未设置"}\n素材目录：{self.material.get() or "未选择"}\n客户名称：{self.client.get() or "未填写"}\n声音风格：{self.voice.get() if self.mode.get()=="draft" else "无（混剪模式）"}\n视频时长：{self.duration.get()}秒\n生成数量：{self.video_count.get()}个\n目标语种：{targetLanguage if self.mode.get()=="draft" else "无"}')
        for i,(c,o,l) in enumerate(self.steps,1): c.itemconfigure(o,fill='#111827' if i<=n else '#e5e7eb'); c.itemconfigure(2,fill='#ffffff' if i<=n else '#6b7280'); l.configure(foreground='#111827' if i<=n else '#6b7280')
    def _go2(self):
        mode=self.mode.get()
        if mode=='draft' and not self.draft.get().strip(): messagebox.showwarning('提示','完整视频模式需要先设置剪映草稿箱路径。'); return
        if mode=='mix' and not self.mix_output.get().strip(): messagebox.showwarning('提示','纯混剪模式需要先设置混剪输出路径。'); return
        p=self.material.get().strip()
        if not p: messagebox.showwarning('提示','请先选择素材目录。'); return
        miss=check_material(p)
        if miss: messagebox.showwarning('目录结构不完整','缺少目录：\n'+'\n'.join(miss)); return
        if not self.client.get().strip(): messagebox.showwarning('提示','请填写客户名称。'); return
        self._show(2)
    def _set_busy(self,b): self.running=b; [x.configure(state='disabled' if b else 'normal') for x in self.buttons]
    def _report_progress(self,v,t): self.root.after(0,lambda:self._set_progress(v,t))
    def _run(self):
        if self.running: return
        mode=self.mode.get()
        if mode=='draft' and not all([self.draft.get().strip(),self.material.get().strip(),self.client.get().strip(),self.voice.get().strip()]): messagebox.showwarning('提示','请先完成前面步骤。'); return
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
                selected=self.voice.get().strip(); lang=resolve_target_language_by_voice_label(selected); duration=self.duration.get().strip()
                r=run_pipeline(Path(self.material.get()),self.client.get().strip(),VOICES[selected],Path(self.draft.get()),progress=self._report_progress,target_language=lang,target_duration=duration,video_count=count)
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
