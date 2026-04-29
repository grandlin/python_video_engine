from __future__ import annotations
import json,logging,random,re,uuid,shutil
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from .assembly_engine import AssemblyPlan
from .content_generator import ContentGenerationResult
from .runtime_config import get_config_value
logger=logging.getLogger("python_video_engine.draft_renderer")
JY_TICKS_PER_SECOND=1_000_000
DEFAULT_CANVAS_WIDTH=1080
DEFAULT_CANVAS_HEIGHT=1920
DEFAULT_FPS=30.0
DEFAULT_DRAFT_VERSION="6.0.0"
SENTENCE_PUNCTUATION="，。！？；：,.!?、"
EN_MAX_CHARS_PER_LINE=40
EN_MAX_WORDS_PER_LINE=8
EN_FONT_SIZE_MAX=7.0
EN_FONT_SIZE_MIN=5.0
EN_FONT_SIZE_STEP_DOWN=0.35
ZH_MAX_CHARS_PER_LINE=15
EN_SECOND_LINE_SHRINK_THRESHOLD=80
EN_WORD_PATTERN=re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
EN_SPLIT_PATTERN=re.compile(r"[^.!?,;:]+[.!?,;:]?|[^.!?,;:]+$")
SUBTITLE_POS_X=0.0
SUBTITLE_POS_Y=-1470.0/DEFAULT_CANVAS_HEIGHT
SUBTITLE_STROKE_WIDTH=0.8
SUBTITLE_FONT_NAME="Source Han Sans CN"
SUBTITLE_TEXTBOX_WIDTH_RATIO=0.80
SUBTITLE_TEXTBOX_HEIGHT_RATIO=0.24
SUBTITLE_ALIGNMENT_CENTER=2
@dataclass(slots=True)
class DraftRenderResult:
    client_name:str; project_name:str; draft_directory:str; draft_content_path:str; draft_meta_info_path:str; total_duration_seconds:float; video_segment_count:int; subtitle_segment_count:int
class DraftRenderer:
    def __init__(self, project_root: str | Path | None = None, draft_box_path: str | Path | None = None)->None:
        if not logging.getLogger().handlers: logging.basicConfig(level=logging.INFO,format="%(message)s")
        self._project_root=Path(project_root).expanduser().resolve(strict=False) if project_root else Path(__file__).resolve().parents[2]
        self.output_root=self._project_root/"output_drafts"; self.output_root.mkdir(parents=True,exist_ok=True)
        self.draft_box_path=Path(draft_box_path).expanduser().resolve(strict=False) if draft_box_path else None
        self.audio_storage_dir=self._get_audio_storage_dir()
        self.subtitle_min_chars=int(get_config_value("subtitle","min_chars",default=8) or 8)
        self.subtitle_max_chars=int(get_config_value("subtitle","max_chars",default=14) or 14)
        self.subtitle_font_size=int(get_config_value("subtitle","font_size",default=11) or 11)
        self._random=random.Random()
    def _get_audio_storage_dir(self)->Path:
        if self.draft_box_path and self.draft_box_path.exists():
            audio_dir=self.draft_box_path/"环球出海音频暂存"
            audio_dir.mkdir(parents=True,exist_ok=True)
            return audio_dir
        return self.output_root
    def render(self,assembly_plan:AssemblyPlan,content_result:ContentGenerationResult)->DraftRenderResult:
        ts=datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        name=f"{assembly_plan.client_name}_AI初稿_{ts}"; draft_dir=self.output_root/name; draft_dir.mkdir(parents=True,exist_ok=True)
        audio_src=Path(content_result.audio_path).resolve(strict=False)
        if not audio_src.exists():
            raise RuntimeError(f"音频源文件不存在: {audio_src}")
        audio_filename=f"audio_{ts}.mp3"
        audio_dst=self.audio_storage_dir/audio_filename
        shutil.copy2(str(audio_src),str(audio_dst))
        if not audio_dst.exists() or audio_dst.stat().st_size<=0:
            raise RuntimeError(f"音频文件复制失败: {audio_dst}")
        logger.info("[DraftRenderer] 音频文件已复制到固定目录: %s (大小: %s bytes)",audio_dst,audio_dst.stat().st_size)
        content_result.audio_path=str(audio_dst)
        subs=[]
        content=self._build_draft_content(assembly_plan,content_result,subs,draft_dir,audio_filename)
        meta=self._build_draft_meta_info(assembly_plan,content_result,name,subs)
        cp=draft_dir/"draft_content.json"; mp=draft_dir/"draft_meta_info.json"
        cp.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding="utf-8")
        mp.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
        logger.info("[DraftRenderer] 草稿文件已生成: %s",cp); logger.info("[DraftRenderer] 草稿文件已生成: %s",mp)
        return DraftRenderResult(assembly_plan.client_name,name,str(draft_dir),str(cp),str(mp),assembly_plan.total_audio_duration_seconds,len(assembly_plan.clips),0)
    def _build_draft_content(self,plan:AssemblyPlan,result:ContentGenerationResult,subs:list[dict[str,float|int|str]],draft_dir:Path,audio_filename:str)->dict[str,object]:
        ap=Path(result.audio_path).resolve(strict=False); ai=self._read_audio_info(ap); at=self._seconds_to_ticks(ai["duration_seconds"]); total=max(self._seconds_to_ticks(plan.total_audio_duration_seconds),at)
        audio_absolute_path=str(ap)
        videos=[]; audios=[]; texts=[]; canvases=[]; sound_maps=[]; speeds=[]; vseg=[]; aseg=[]; tseg=[]
        aid=self._uuid(); amid=self._uuid()
        audios.append({"id":aid,"type":"music","path":audio_absolute_path,"name":ap.name,"material_name":ap.name,"category_id":"local","local_material_id":aid,"duration":at,"has_audio":True,"wave_points":[]})
        sound_maps.append({"id":amid,"is_config_open":False,"type":"stereo"})
        aseg.append({"id":self._uuid(),"material_id":aid,"target_timerange":{"start":0,"duration":at},"source_timerange":{"start":0,"duration":at},"extra_material_refs":[amid],"clip":None,"common_keyframes":[],"enable_adjust":True,"is_placeholder":False,"speed":1.0,"visible":True,"volume":1.0})
        cursor=0
        video_durations_ticks=[]
        if not video_durations_ticks:
            video_durations_ticks=[max(self._seconds_to_ticks(c.clip_duration_seconds),1) for c in plan.clips]
        for i,ct in enumerate(video_durations_ticks):
            if not plan.clips:
                break
            clip=plan.clips[i % len(plan.clips)]
            max_shift=max(min(clip.clip_duration_seconds*0.12,0.18),0.0)
            random_shift=self._random.uniform(0.0,max_shift) if max_shift>0 else 0.0
            shifted_start=max(clip.clip_start_seconds+random_shift,0.0)
            st=self._seconds_to_ticks(shifted_start); source_ct=max(self._seconds_to_ticks(clip.clip_duration_seconds),1); vid=self._uuid(); cid=self._uuid(); sid=self._uuid(); spid=self._uuid()
            scale_x=round(self._random.uniform(1.02,1.10),4); scale_y=scale_x
            videos.append({"id":vid,"type":"video","path":clip.absolute_path,"name":clip.file_name,"material_name":clip.file_name,"category_id":"local","local_material_id":vid,"duration":source_ct,"width":DEFAULT_CANVAS_WIDTH,"height":DEFAULT_CANVAS_HEIGHT,"has_audio":False})
            canvases.append({"id":cid,"type":"canvas_color","color":"#000000"}); sound_maps.append({"id":sid,"is_config_open":False,"type":"stereo"}); speeds.append({"id":spid,"mode":0,"speed":1.0,"type":"speed"})
            vseg.append({"id":self._uuid(),"material_id":vid,"target_timerange":{"start":cursor,"duration":ct},"source_timerange":{"start":st,"duration":min(ct,source_ct)},"extra_material_refs":[cid,sid,spid],"clip":{"alpha":1.0,"flip":{"horizontal":False,"vertical":False},"rotation":0.0,"scale":{"x":scale_x,"y":scale_y},"transform":{"x":0.0,"y":0.0}},"common_keyframes":[],"enable_adjust":True,"is_placeholder":False,"speed":1.0,"visible":True,"volume":0.0})
            cursor+=ct
        total=max(total,cursor)
        return {"id":self._uuid(),"name":f"{plan.client_name}_AI初稿","duration":total,"fps":DEFAULT_FPS,"color_space":0,"canvas_config":{"ratio":"9:16","width":DEFAULT_CANVAS_WIDTH,"height":DEFAULT_CANVAS_HEIGHT},"config":{"maintrack_adsorb":True,"material_save_mode":0,"subtitle_sync":True,"lyrics_sync":False,"video_mute":False},"keyframes":{"adjusts":[],"audios":[],"effects":[],"filters":[],"texts":[],"videos":[]},"materials":{"videos":videos,"audios":audios,"texts":texts,"canvases":canvases,"effects":[],"transitions":[],"video_effects":[],"sound_channel_mappings":sound_maps,"speeds":speeds,"audio_fades":[]},"tracks":[{"id":self._uuid(),"attribute":0,"flag":0,"is_default_name":False,"name":"视频主轨","type":"video","segments":vseg},{"id":self._uuid(),"attribute":0,"flag":0,"is_default_name":False,"name":"音频轨","type":"audio","segments":aseg}],"platform":{"os":"windows","app":"jianying_pro"},"version":DEFAULT_DRAFT_VERSION,"created_at":self._now_iso(),"updated_at":self._now_iso()}
    def _build_text_material(self,tid:str,chunk:dict[str,float|int|str])->dict[str,object]:
        text=str(chunk["text"])
        render_text=str(chunk.get("render_text") or text)
        font_size=float(chunk.get("font_size") or self.subtitle_font_size)
        font_size=max(5.0,min(7.0,font_size))
        style_range=[0,len(render_text)]
        style={"range":style_range,"size":font_size,"font_name":SUBTITLE_FONT_NAME,"color":"#FFFFFF","stroke_color":"#000000","stroke_width":SUBTITLE_STROKE_WIDTH,"bold":False,"italic":False,"underline":False,"scale":{"x":1.0,"y":1.0},"alignment":SUBTITLE_ALIGNMENT_CENTER}
        content=json.dumps({"text":render_text,"styles":[style],"paragraphs":[{"range":style_range,"alignment":SUBTITLE_ALIGNMENT_CENTER,"line_break":True}],"bounding_box":{"width_ratio":SUBTITLE_TEXTBOX_WIDTH_RATIO,"height_ratio":SUBTITLE_TEXTBOX_HEIGHT_RATIO},"wrap":True,"auto_scale":True},ensure_ascii=False)
        return {"id":tid,"type":"text","content":content,"text":render_text,"font_size":font_size,"font_name":SUBTITLE_FONT_NAME,"font_path":"","text_color":"#FFFFFF","stroke_color":"#000000","stroke_width":SUBTITLE_STROKE_WIDTH,"background_alpha":0.0,"alignment":SUBTITLE_ALIGNMENT_CENTER,"bold":False,"italic":False,"underline":False,"scale":{"x":1.0,"y":1.0},"text_style":{"size":font_size,"font_name":SUBTITLE_FONT_NAME,"color":"#FFFFFF","stroke_color":"#000000","stroke_width":SUBTITLE_STROKE_WIDTH,"scale":{"x":1.0,"y":1.0},"alignment":SUBTITLE_ALIGNMENT_CENTER},"bounding_box":{"width":round(DEFAULT_CANVAS_WIDTH*SUBTITLE_TEXTBOX_WIDTH_RATIO,2),"height":round(DEFAULT_CANVAS_HEIGHT*SUBTITLE_TEXTBOX_HEIGHT_RATIO,2)},"wrap":True,"auto_scale":True}
    def _build_subtitle_chunks(self,result:ContentGenerationResult)->list[dict[str,float|int|str]]:
        lang=(result.script_language or 'zh').lower()
        script_text=result.script_text; audio_duration_seconds=float(result.audio_duration_seconds or 0.0)
        if result.subtitle_units and len(result.subtitle_units)==len(result.subtitle_durations_ms):
            raw_slices=[str(x).strip() for x in result.subtitle_units if str(x).strip()]
        else:
            raw_slices=self._split_english_by_words(script_text) if lang.startswith('en') else self._split_chinese(script_text)
        if not raw_slices: return []
        prepared=[self._prepare_subtitle_layout(text,lang) for text in raw_slices]
        truth_ms=self._resolve_truth_durations_ms(result,len(prepared))
        if truth_ms:
            start_ms=0; out=[]
            for i,chunk in enumerate(prepared):
                dur_ms=max(int(truth_ms[i]),1)
                start=round(start_ms/1000.0,3); dur=round(dur_ms/1000.0,3)
                item={**chunk,"char_count":len(str(chunk["text"])),"start_seconds":start,"duration_seconds":dur,"start_ticks":int(round(start*1000))*1000,"duration_ticks":dur_ms*1000}; out.append(item)
                start_ms+=dur_ms
                logger.info("[DraftRenderer][Subtitle] chunk=%s render=%s chars=%s start=%.3fs duration=%.3fs font=%.2f",chunk["text"],chunk.get("render_text"),len(str(chunk["text"])),start,dur,float(chunk.get("font_size") or self.subtitle_font_size))
            return out
        weights=[self._chunk_weight(str(x["text"])) for x in prepared]; total=sum(weights) or 1.0; cursor=0.0; out=[]
        for i,chunk in enumerate(prepared):
            dur=round(audio_duration_seconds*(weights[i]/total),3)
            if i==len(prepared)-1: dur=round(max(audio_duration_seconds-cursor,0.0),3)
            start=round(cursor,3); cursor=round(cursor+dur,3)
            item={**chunk,"char_count":len(str(chunk["text"])),"start_seconds":start,"duration_seconds":dur,"start_ticks":int(round(start*1000))*1000,"duration_ticks":int(round(dur*1000))*1000}; out.append(item)
            logger.info("[DraftRenderer][Subtitle] chunk=%s render=%s chars=%s start=%.3fs duration=%.3fs font=%.2f",chunk["text"],chunk.get("render_text"),len(str(chunk["text"])),start,dur,float(chunk.get("font_size") or self.subtitle_font_size))
        return out

    def _resolve_truth_durations_ms(self,result:ContentGenerationResult,expected_count:int)->list[int]:
        if expected_count<=0:
            return []
        paths=[str(p) for p in getattr(result,"subtitle_audio_paths",[]) if str(p).strip()]
        if len(paths)!=expected_count:
            if len(result.subtitle_durations_ms)==expected_count:
                return [max(int(x),1) for x in result.subtitle_durations_ms]
            return []
        out=[]
        warned=False
        for p in paths:
            try:
                import audioop  # noqa: F401
                from pydub import AudioSegment

                seg=AudioSegment.from_file(p)
                out.append(max(int(round(seg.duration_seconds*1000.0)),1))
            except Exception as exc:
                if not warned:
                    warned=True
                    logger.warning("[DraftRenderer] pydub 不可用，真值回退到 subtitle_durations_ms。请确保入口处已注入 audioop 兼容层（可在 .env 设置 AUDIOOP_COMPAT_MODULE）。详情: %s", exc)
                if len(result.subtitle_durations_ms)==expected_count:
                    return [max(int(x),1) for x in result.subtitle_durations_ms]
                return []
        return out
    def _prepare_subtitle_layout(self,text:str,lang:str)->dict[str,object]:
        raw=self._clean_subtitle_text(text.strip())
        if not raw:
            return {"text":"","render_text":"","font_size":self.subtitle_font_size}
        render_text=self.format_subtitle(raw,lang)
        if lang.startswith('en'):
            font_size=self._resolve_english_font_size(render_text)
            return {"text":raw,"render_text":render_text,"font_size":font_size}
        zh_font=max(5.0,min(7.0,float(self.subtitle_font_size)))
        return {"text":raw,"render_text":render_text,"font_size":round(zh_font,2)}

    def format_subtitle(self,text:str,lang:str)->str:
        return self.split_text_to_lines(text,lang)

    def split_text_to_lines(self,text:str,lang:str)->str:
        if lang.startswith('en'):
            normalized=' '.join(text.split())
            if not normalized:
                return text
            return self._split_english_line_by_center_space(normalized)
        normalized=text.strip()
        if not normalized or len(normalized)<=ZH_MAX_CHARS_PER_LINE:
            return normalized or text
        center=len(normalized)//2
        return normalized[:center]+"\n"+normalized[center:]

    def _split_english_line_by_center_space(self,text:str)->str:
        words=text.split(' ')
        if len(words)<=EN_MAX_WORDS_PER_LINE and len(text)<=EN_MAX_CHARS_PER_LINE:
            return text
        midpoint=len(text)//2
        spaces=[i for i,ch in enumerate(text) if ch==' ']
        if not spaces:
            return text
        valid=[i for i in spaces if i<=EN_MAX_CHARS_PER_LINE and len(text)-i-1<=EN_MAX_CHARS_PER_LINE]
        candidates=valid or spaces
        split_at=min(candidates,key=lambda i: abs(i-midpoint))
        left=text[:split_at].strip()
        right=text[split_at+1:].strip()
        if not left or not right:
            return text
        return left+"\n"+right

    def _resolve_english_font_size(self,render_text:str)->float:
        longest=max((len(line.strip()) for line in render_text.split('\n')),default=0)
        total_chars=len(render_text.replace('\n',''))
        font_size=min(float(self.subtitle_font_size),EN_FONT_SIZE_MAX)
        if longest>EN_MAX_CHARS_PER_LINE*0.9 or total_chars>EN_SECOND_LINE_SHRINK_THRESHOLD:
            steps=max(1,(total_chars-EN_SECOND_LINE_SHRINK_THRESHOLD+9)//10) if total_chars>EN_SECOND_LINE_SHRINK_THRESHOLD else 1
            font_size=max(EN_FONT_SIZE_MIN,font_size-steps*EN_FONT_SIZE_STEP_DOWN)
        return round(font_size,2)

    def _split_english_by_words(self,text:str)->list[str]:
        cleaned=re.sub(r"\\s+"," ",text).strip()
        if not cleaned: return []
        phrases=[x.strip() for x in EN_SPLIT_PATTERN.findall(cleaned) if x.strip()]
        out=[]
        for phrase in phrases:
            out.extend(self._split_long_english_phrase(phrase))
        return [x for x in out if x]

    def _split_long_english_phrase(self,phrase:str)->list[str]:
        phrase=phrase.strip(); trailing=''
        if not phrase: return []
        if phrase[-1] in ',.!?;:': trailing=phrase[-1]; phrase=phrase[:-1].strip()
        words=phrase.split()
        if not words: return [trailing] if trailing else []
        chunks=[]; cur=[]
        for w in words:
            cand=cur+[w]; cand_text=' '.join(cand)
            if cur and (len(cand)>EN_MAX_WORDS_PER_LINE or len(cand_text)>EN_MAX_CHARS_PER_LINE):
                chunks.append(' '.join(cur)); cur=[w]
            else:
                cur=cand
        if cur: chunks.append(' '.join(cur))
        if trailing and chunks: chunks[-1]=chunks[-1]+trailing
        return chunks

    def _split_chinese(self,script_text:str)->list[str]:
        sentence_units=self._split_by_punctuation(script_text)
        if not sentence_units: return []
        slices=[]
        for unit in sentence_units:
            cleaned=self._normalize_subtitle_text(unit)
            if not cleaned: continue
            slices.extend(self._split_long_unit(cleaned))
        return self._merge_short_tail_chunks(slices)

    def _split_by_punctuation(self,script_text:str)->list[str]:
        units=[]; buf=[]
        for ch in script_text:
            if ch in "\\r\\n": continue
            buf.append(ch)
            if ch in SENTENCE_PUNCTUATION:
                units.append(''.join(buf)); buf=[]
        if buf: units.append(''.join(buf))
        return units

    def _normalize_subtitle_text(self,text:str)->str:
        return re.sub(r"[\\s]+","",text).strip("，。！？；：,.!?、")

    def _split_long_unit(self,text:str)->list[str]:
        if len(text)<=self.subtitle_max_chars: return [text]
        chunks=[]; remaining=text
        while len(remaining)>self.subtitle_max_chars:
            split_at=self._best_split_index(remaining)
            chunks.append(remaining[:split_at])
            remaining=remaining[split_at:]
        if remaining: chunks.append(remaining)
        return chunks

    def _best_split_index(self,text:str)->int:
        max_idx=min(len(text),self.subtitle_max_chars); min_idx=min(self.subtitle_min_chars,max_idx)
        preferred=["，","、","与","和","及","并","让","把","为"]
        search=text[:max_idx]
        for marker in preferred:
            idx=search.rfind(marker)
            if idx>=min_idx-1: return idx+1
        return max_idx

    def _merge_short_tail_chunks(self,chunks:list[str])->list[str]:
        if not chunks: return []
        merged=[]
        for chunk in chunks:
            if merged and len(chunk)<self.subtitle_min_chars and len(merged[-1])+len(chunk)<=self.subtitle_max_chars:
                merged[-1]+=chunk
            else:
                merged.append(chunk)
        return merged

    def _clean_subtitle_text(self,text:str)->str:
        if not text:
            return ""
        cleaned=text.replace("\\n", " ").replace("\\r", " ")
        cleaned=cleaned.replace("/n", " ").replace("/r", " ")
        cleaned=re.sub(r"\s+"," ",cleaned).strip()
        cleaned=cleaned.strip("，。！？；：,.!?、;:·…—- ")
        return cleaned

    def _chunk_weight(self,text:str)->float:
        base=len(re.sub(r"\\s+","",text)); punct=sum(1 for ch in text if ch in SENTENCE_PUNCTUATION)*2
        return float(max(base+punct,1))

    def _post_validate_subtitle_texts(self,source_script:str,subs:list[dict[str,float|int|str]],script_language:str)->None:
        if not (script_language or '').lower().startswith('en'): return
        src=EN_WORD_PATTERN.findall(source_script)
        dst=EN_WORD_PATTERN.findall(' '.join(str(x['text']) for x in subs))
        if src!=dst: raise RuntimeError("英文字幕切分校验失败：检测到单词可能被截断，请重试。")

    def _build_draft_meta_info(self,plan:AssemblyPlan,result:ContentGenerationResult,project_name:str,subs:list[dict[str,float|int|str]])->dict[str,object]:
        ap=Path(result.audio_path).resolve(strict=False); ai=self._read_audio_info(ap)
        return {"draft_name":project_name,"draft_id":self._uuid(),"draft_version":DEFAULT_DRAFT_VERSION,"timeline_duration":self._seconds_to_ticks(max(plan.total_audio_duration_seconds,ai["duration_seconds"])),"audio_path":str(ap),"audio_file_name":ap.name,"audio_duration_seconds":ai["duration_seconds"],"audio_bitrate":ai["bitrate"],"audio_sample_rate":ai["sample_rate"],"used_mock_tts":result.used_mock_tts,"tts_provider":result.tts_provider,"client_name":plan.client_name,"base_path":plan.base_path,"video_segment_count":len(plan.clips),"subtitle_segment_count":len(subs),"subtitles":subs,"source_videos":[{"file_name":c.file_name,"absolute_path":c.absolute_path,"clip_start_seconds":c.clip_start_seconds,"clip_end_seconds":c.clip_end_seconds,"clip_duration_seconds":c.clip_duration_seconds,"allocated_category":c.allocated_category,"source_category":c.source_category} for c in plan.clips],"created_at":self._now_iso(),"updated_at":self._now_iso()}

    def _read_audio_info(self,audio_path:Path):
        try:
            from mutagen.mp3 import MP3
            a=MP3(str(audio_path))
            return {"duration_seconds":round(float(a.info.length),3),"bitrate":int(getattr(a.info,"bitrate",0) or 0),"sample_rate":int(getattr(a.info,"sample_rate",0) or 0)}
        except Exception as e:
            print(f"[警告] 音频读取失败，使用默认时长兜底: {e}")
            return {"duration_seconds":35.0,"bitrate":128000,"sample_rate":44100}

    def _seconds_to_ticks(self,seconds:float)->int: return max(int(round(max(seconds,0.0)*JY_TICKS_PER_SECOND)),0)
    def _uuid(self)->str: return str(uuid.uuid4())
    def _now_iso(self)->str: return datetime.now(timezone.utc).isoformat()
