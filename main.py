from __future__ import annotations
import argparse,json,shutil,sys,threading,tkinter as tk
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from pprint import pprint
from tkinter import filedialog,messagebox,ttk
from src.python_video_engine import AssemblyEngine,ContentGenerator,DraftRenderer,MaterialFetcher
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(errors='replace')
if hasattr(sys.stderr,'reconfigure'): sys.stderr.reconfigure(errors='replace')
VOICES={'温柔女声':'female_standard','活力男声':'male_dynamic','成熟男声':'male_mature','童声':'child_cute'}
BASE=r'Z:\00_客户06105名点工贸_测试'; CLIENT='名点工贸'; SETTINGS=Path.home()/'.jianying_auto_editor_settings.json'
def load_settings():
    try:return json.loads(SETTINGS.read_text(encoding='utf-8')) if SETTINGS.exists() else {}
    except Exception:return {}
def save_settings(d): SETTINGS.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def infer_client_name(p): return Path(p).expanduser().resolve(strict=False).name.strip() or CLIENT
def check_material(p): return [x for x in ['01_工厂全景与大环境','02_机器运转与加工细节','03_成品展示与发货'] if not (Path(p)/x).exists()]
def move_draft(src,dst_root):
    src=Path(src).resolve(strict=False); dst_root=Path(dst_root).expanduser().resolve(strict=False); dst_root.mkdir(parents=True,exist_ok=True); base=f"{src.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"; dst=dst_root/base; i=1
    while dst.exists(): dst=dst_root/f'{base}_{i}'; i+=1
    return Path(shutil.move(str(src),str(dst)))
def run_pipeline(base_path,client_name,voice_key='female_standard',draft_box=None,progress=None):
    if progress: progress(5,'开始扫描素材...')
    fetch=MaterialFetcher().fetch(base_path=base_path,client_name=client_name); pprint(fetch.counts_by_category); pprint([asdict(x) for x in fetch.materials[:2]])
    if progress: progress(35,f'素材扫描完成，共 {len(fetch.materials)} 条，开始生成文案与配音...')
    content=ContentGenerator(voice_key=voice_key).generate(base_path=base_path,client_name=client_name,keywords=fetch.keywords)
    if progress: progress(60,'配音完成，开始组装片段...')
    plan=AssemblyEngine().assemble(base_path=base_path,client_name=client_name,audio_duration_seconds=content.audio_duration_seconds,materials=fetch.materials)
    if progress: progress(82,'片段组装完成，开始生成剪映草稿...')
    draft=DraftRenderer().render(assembly_plan=plan,content_result=content)
    if progress: progress(92,'草稿已生成，正在移动到剪映草稿箱...')
    exported=str(move_draft(draft.draft_directory,draft_box)) if draft_box else draft.draft_directory
    if progress: progress(100,'草稿已成功移动到剪映草稿箱')
    return {'script_text':content.script_text,'exported_draft_directory':exported}
class App:
    def __init__(self):
        cfg=load_settings(); self.root=tk.Tk(); self.root.title('剪映自动剪辑工具'); self.root.geometry('1080x820'); self.root.minsize(1020,780); self.root.configure(bg='#f6f7fb')
        self.draft=tk.StringVar(value=cfg.get('draft_box_path','')); self.material=tk.StringVar(value=BASE); self.client=tk.StringVar(value=CLIENT); self.voice=tk.StringVar(value='温柔女声'); self.status=tk.StringVar(value='请选择素材后开始生成'); self.script=tk.StringVar(value='生成文案后显示在这里'); self.output=tk.StringVar(value='生成结果会显示在这里'); self.draft_text=tk.StringVar(); self.progress_text=tk.StringVar(value='0%'); self.progress_value=tk.DoubleVar(value=0); self.buttons=[]; self.steps=[]; self.running=False; self._style(); self._ui(); self._refresh_draft(); self._show(1); self.root.after(100,self._ensure_draft)
    def _style(self):
        s=ttk.Style();
        try:s.theme_use('clam')
        except tk.TclError:pass
        s.configure('P.TFrame',background='#f6f7fb'); s.configure('C.TFrame',background='#ffffff'); s.configure('T1.TLabel',background='#f6f7fb',foreground='#111827',font=('Microsoft YaHei UI',24,'bold')); s.configure('T2.TLabel',background='#f6f7fb',foreground='#6b7280',font=('Microsoft YaHei UI',11)); s.configure('H.TLabel',background='#ffffff',foreground='#111827',font=('Microsoft YaHei UI',15,'bold')); s.configure('B.TLabel',background='#ffffff',foreground='#374151',font=('Microsoft YaHei UI',11)); s.configure('Progress.Horizontal.TProgressbar',thickness=18)
    def _ui(self):
        w=ttk.Frame(self.root,style='P.TFrame',padding=24); w.pack(fill='both',expand=True); w.columnconfigure(0,weight=1); w.rowconfigure(3,weight=1)
        h=ttk.Frame(w,style='P.TFrame'); h.grid(row=0,column=0,sticky='ew'); h.columnconfigure(0,weight=1); ttk.Label(h,text='剪映自动剪辑工具',style='T1.TLabel').grid(row=0,column=0,sticky='w'); ttk.Button(h,text='草稿箱设置',command=self._change_draft).grid(row=0,column=1,sticky='e'); ttk.Label(h,text='素材选择 > 声音设置 > 生成草稿',style='T2.TLabel').grid(row=1,column=0,sticky='w',pady=(6,0))
        c=ttk.Frame(w,style='C.TFrame',padding=14); c.grid(row=1,column=0,sticky='ew',pady=(16,0)); c.columnconfigure(0,weight=1); ttk.Label(c,text='当前剪映草稿箱',style='H.TLabel').grid(row=0,column=0,sticky='w'); ttk.Label(c,textvariable=self.draft_text,style='B.TLabel',wraplength=920).grid(row=1,column=0,sticky='w',pady=(8,0))
        bar=ttk.Frame(w,style='C.TFrame',padding=18); bar.grid(row=2,column=0,sticky='ew',pady=(18,0))
        for i,t in enumerate(['素材选择','声音设置','生成草稿'],1): bar.columnconfigure(i,weight=1); f=ttk.Frame(bar,style='C.TFrame'); f.grid(row=0,column=i,sticky='ew',padx=18); cv=tk.Canvas(f,width=44,height=44,bg='#ffffff',highlightthickness=0); ov=cv.create_oval(2,2,42,42,fill='#e5e7eb',outline=''); cv.create_text(22,22,text=str(i),fill='#6b7280',font=('Microsoft YaHei UI',12,'bold')); cv.pack(); lb=ttk.Label(f,text=t,style='B.TLabel'); lb.pack(pady=(8,0)); self.steps.append((cv,ov,lb))
        self.box=ttk.Frame(w,style='C.TFrame',padding=24); self.box.grid(row=3,column=0,sticky='nsew',pady=(18,0)); self.box.columnconfigure(0,weight=1); self.box.rowconfigure(0,weight=1)
        self.p1=self._page1(); self.p2=self._page2(); self.p3=self._page3(); [p.grid(row=0,column=0,sticky='nsew') for p in [self.p1,self.p2,self.p3]]
    def _page1(self):
        f=ttk.Frame(self.box,style='C.TFrame'); f.columnconfigure(0,weight=1); ttk.Label(f,text='1. 选择素材路径',style='H.TLabel').grid(row=0,column=0,sticky='w'); r=ttk.Frame(f,style='C.TFrame'); r.grid(row=1,column=0,sticky='ew',pady=(16,0)); r.columnconfigure(0,weight=1); ttk.Entry(r,textvariable=self.material).grid(row=0,column=0,sticky='ew',ipady=8,padx=(0,10)); ttk.Button(r,text='浏览素材',command=self._pick_material).grid(row=0,column=1); n=ttk.Frame(f,style='C.TFrame'); n.grid(row=2,column=0,sticky='ew',pady=(16,0)); n.columnconfigure(1,weight=1); ttk.Label(n,text='客户名称',style='B.TLabel').grid(row=0,column=0,padx=(0,10)); ttk.Entry(n,textvariable=self.client).grid(row=0,column=1,sticky='ew',ipady=8); b=ttk.Button(f,text='下一步',command=self._go2); b.grid(row=3,column=0,sticky='e',pady=(24,0)); self.buttons=[b]; return f
    def _page2(self):
        f=ttk.Frame(self.box,style='C.TFrame'); ttk.Label(f,text='2. 选择声音',style='H.TLabel').grid(row=0,column=0,sticky='w'); [ttk.Radiobutton(f,text=k,value=k,variable=self.voice).grid(row=1+i,column=0,sticky='w',pady=8) for i,k in enumerate(VOICES)]; foot=ttk.Frame(f,style='C.TFrame'); foot.grid(row=6,column=0,sticky='ew',pady=(24,0)); foot.columnconfigure(1,weight=1); b1=ttk.Button(foot,text='上一步',command=lambda:self._show(1)); b2=ttk.Button(foot,text='下一步',command=lambda:self._show(3)); b1.grid(row=0,column=0,sticky='w'); b2.grid(row=0,column=1,sticky='e'); self.buttons=[b1,b2]; return f
    def _page3(self):
        f=ttk.Frame(self.box,style='C.TFrame'); f.columnconfigure(0,weight=1); top=ttk.Frame(f,style='C.TFrame'); top.grid(row=0,column=0,sticky='ew',pady=(0,12)); top.columnconfigure(0,weight=3); top.columnconfigure(1,weight=2); top.columnconfigure(2,weight=2); top.columnconfigure(3,weight=3); b1=ttk.Button(top,text='上一步',command=lambda:self._show(2)); b2=ttk.Button(top,text='生成草稿',command=self._run); b1.grid(row=0,column=1,sticky='w'); b2.grid(row=0,column=2,sticky='e'); self.buttons=[b1,b2]; ttk.Label(f,text='3. 生成草稿',style='H.TLabel').grid(row=1,column=0,sticky='w'); self.summary=ttk.Label(f,text='-',style='B.TLabel',wraplength=900,justify='left'); self.summary.grid(row=2,column=0,sticky='w',pady=(8,16)); pw=ttk.Frame(f,style='C.TFrame'); pw.grid(row=3,column=0,sticky='ew'); pw.columnconfigure(0,weight=1); ttk.Progressbar(pw,mode='determinate',maximum=100,variable=self.progress_value,style='Progress.Horizontal.TProgressbar').grid(row=0,column=0,sticky='ew'); ttk.Label(pw,textvariable=self.progress_text,style='B.TLabel').grid(row=0,column=1,padx=(12,0)); ttk.Label(f,textvariable=self.status,style='B.TLabel').grid(row=4,column=0,sticky='w',pady=(10,18)); ttk.Label(f,text='文案预览',style='H.TLabel').grid(row=5,column=0,sticky='w'); ttk.Label(f,textvariable=self.script,style='B.TLabel',wraplength=900,justify='left').grid(row=6,column=0,sticky='w',pady=(8,18)); ttk.Label(f,text='草稿输出',style='H.TLabel').grid(row=7,column=0,sticky='w'); ttk.Label(f,textvariable=self.output,style='B.TLabel',wraplength=900,justify='left').grid(row=8,column=0,sticky='w',pady=(8,0)); return f
    def _refresh_draft(self): self.draft_text.set(self.draft.get().strip() or '未设置。首次使用请先设置，之后应用会自动记住。')
    def _set_progress(self,v,t): v=max(0,min(100,int(v))); self.progress_value.set(v); self.progress_text.set(f'{v}%'); self.status.set(t)
    def _pick_material(self):
        v=filedialog.askdirectory(title='选择素材目录')
        if v: self.material.set(v); self.client.set(infer_client_name(v))
    def _change_draft(self):
        v=filedialog.askdirectory(title='选择剪映草稿箱路径')
        if v: self.draft.set(v); save_settings({'draft_box_path':v}); self._refresh_draft(); self.status.set('草稿箱路径已保存，下次打开会自动记住')
    def _ensure_draft(self):
        if self.draft.get().strip(): return
        messagebox.showinfo('首次设置','请先设置一次剪映草稿箱路径，后续应用会自动记住。'); self._change_draft()
    def _show(self,n):
        [self.p1,self.p2,self.p3][n-1].tkraise()
        if n==3: self.summary.config(text=f'剪映草稿箱：{self.draft.get() or "未设置"}\n素材目录：{self.material.get() or "未选择"}\n客户名称：{self.client.get() or "未填写"}\n声音风格：{self.voice.get() or "未选择"}')
        for i,(c,o,l) in enumerate(self.steps,1): c.itemconfigure(o,fill='#111827' if i<=n else '#e5e7eb'); c.itemconfigure(2,fill='#ffffff' if i<=n else '#6b7280'); l.configure(foreground='#111827' if i<=n else '#6b7280')
    def _go2(self):
        if not self.draft.get().strip(): messagebox.showwarning('提示','请先设置剪映草稿箱路径。'); return
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
        if not all([self.draft.get().strip(),self.material.get().strip(),self.client.get().strip(),self.voice.get().strip()]): messagebox.showwarning('提示','请先完成前面步骤。'); return
        self._set_busy(True); self._set_progress(1,'准备开始...'); self.script.set('正在生成文案，请稍候...'); self.output.set('正在移动到剪映草稿箱...'); threading.Thread(target=self._worker,daemon=True).start()
    def _worker(self):
        try: r=run_pipeline(Path(self.material.get()),self.client.get().strip(),VOICES[self.voice.get().strip()],Path(self.draft.get()),progress=self._report_progress); self.root.after(0,lambda:self._ok(r))
        except Exception as e:
            err_msg=str(e)
            self.root.after(0,lambda msg=err_msg:self._fail(msg))
    def _ok(self,r): self._set_busy(False); self._set_progress(100,'已完成：草稿已自动移动到剪映草稿箱'); self.script.set(str(r.get('script_text') or '')); self.output.set(f"已移动到：{r.get('exported_draft_directory')}"); messagebox.showinfo('完成','草稿已生成并移动完成。')
    def _fail(self,msg): self._set_busy(False); self.status.set('生成失败，请检查路径、网络或素材结构'); self.output.set(msg); self.script.set('生成失败。'); self.progress_text.set('失败'); messagebox.showerror('生成失败',msg)
    def run(self): self.root.mainloop()
def parse_args():
    p=argparse.ArgumentParser(description='Run local auto-edit pipeline'); p.add_argument('--base-path',default=BASE); p.add_argument('--client-name',default=CLIENT); p.add_argument('--voice',default='female_standard'); p.add_argument('--draft-box-path',default=''); p.add_argument('--json',dest='json_output',action='store_true'); p.add_argument('--gui',action='store_true'); return p.parse_args()
def main():
    a=parse_args(); cfg=load_settings(); draft=a.draft_box_path or cfg.get('draft_box_path','')
    if a.gui or len(sys.argv)==1: App().run(); return
    r=run_pipeline(Path(a.base_path),a.client_name,a.voice,Path(draft) if draft else None)
    if a.json_output: print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__': main()
