from __future__ import annotations
import json,logging,re,uuid
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from .assembly_engine import AssemblyPlan
from .content_generator import ContentGenerationResult
logger=logging.getLogger("python_video_engine.draft_renderer")
JY_TICKS_PER_SECOND=1_000_000
DEFAULT_CANVAS_WIDTH=1080
DEFAULT_CANVAS_HEIGHT=1920
DEFAULT_FPS=30.0
DEFAULT_DRAFT_VERSION="6.0.0"
SENTENCE_PUNCTUATION="，。！？；：,.!?、"
PUNCTUATION_PATTERN=r"[\s，。！？、“”‘’；：,.!?、]"
SUBTITLE_MIN_CHARS=8
SUBTITLE_MAX_CHARS=14
SUBTITLE_FONT_SIZE=11
SUBTITLE_POS_X=0.0
SUBTITLE_POS_Y=-1470.0/DEFAULT_CANVAS_HEIGHT
SUBTITLE_STROKE_WIDTH=0.8
SUBTITLE_FONT_NAME="Source Han Sans CN"
@dataclass(slots=True)
class DraftRenderResult:
    client_name:str; project_name:str; draft_directory:str; draft_content_path:str; draft_meta_info_path:str; total_duration_seconds:float; video_segment_count:int; subtitle_segment_count:int
class DraftRenderer:
    def __init__(self)->None:
        if not logging.getLogger().handlers: logging.basicConfig(level=logging.INFO,format="%(message)s")
        self.output_root=self._project_root()/"output_drafts"; self.output_root.mkdir(parents=True,exist_ok=True)
    def render(self,assembly_plan:AssemblyPlan,content_result:ContentGenerationResult)->DraftRenderResult:
        name=f"{assembly_plan.client_name}_AI初稿"; draft_dir=self.output_root/name; draft_dir.mkdir(parents=True,exist_ok=True)
        subs=self._build_subtitle_chunks(content_result.script_text,content_result.audio_duration_seconds)
        content=self._build_draft_content(assembly_plan,content_result,subs)
        meta=self._build_draft_meta_info(assembly_plan,content_result,name,subs)
        cp=draft_dir/"draft_content.json"; mp=draft_dir/"draft_meta_info.json"
        cp.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding="utf-8")
        mp.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
        logger.info("[DraftRenderer] 草稿文件已生成: %s",cp); logger.info("[DraftRenderer] 草稿文件已生成: %s",mp)
        return DraftRenderResult(assembly_plan.client_name,name,str(draft_dir),str(cp),str(mp),assembly_plan.total_audio_duration_seconds,len(assembly_plan.clips),len(subs))
    def _build_draft_content(self,plan:AssemblyPlan,result:ContentGenerationResult,subs:list[dict[str,float|int|str]])->dict[str,object]:
        ap=Path(result.audio_path).resolve(strict=False); ai=self._read_audio_info(ap); at=self._seconds_to_ticks(ai["duration_seconds"]); total=max(self._seconds_to_ticks(plan.total_audio_duration_seconds),at)
        videos=[]; audios=[]; texts=[]; canvases=[]; sound_maps=[]; speeds=[]; vseg=[]; aseg=[]; tseg=[]
        aid=self._uuid(); amid=self._uuid()
        audios.append({"id":aid,"type":"music","path":str(ap),"name":ap.name,"material_name":ap.name,"category_id":"local","local_material_id":aid,"duration":at,"has_audio":True,"wave_points":[]})
        sound_maps.append({"id":amid,"is_config_open":False,"type":"stereo"})
        aseg.append({"id":self._uuid(),"material_id":aid,"target_timerange":{"start":0,"duration":at},"source_timerange":{"start":0,"duration":at},"extra_material_refs":[amid],"clip":None,"common_keyframes":[],"enable_adjust":True,"is_placeholder":False,"speed":1.0,"visible":True,"volume":1.0})
        cursor=0
        for clip in plan.clips:
            ct=self._seconds_to_ticks(clip.clip_duration_seconds); st=self._seconds_to_ticks(clip.clip_start_seconds); vid=self._uuid(); cid=self._uuid(); sid=self._uuid(); spid=self._uuid()
            videos.append({"id":vid,"type":"video","path":clip.absolute_path,"name":clip.file_name,"material_name":clip.file_name,"category_id":"local","local_material_id":vid,"duration":ct,"width":DEFAULT_CANVAS_WIDTH,"height":DEFAULT_CANVAS_HEIGHT,"has_audio":False})
            canvases.append({"id":cid,"type":"canvas_color","color":"#000000"}); sound_maps.append({"id":sid,"is_config_open":False,"type":"stereo"}); speeds.append({"id":spid,"mode":0,"speed":1.0,"type":"speed"})
            vseg.append({"id":self._uuid(),"material_id":vid,"target_timerange":{"start":cursor,"duration":ct},"source_timerange":{"start":st,"duration":ct},"extra_material_refs":[cid,sid,spid],"clip":{"alpha":1.0,"flip":{"horizontal":False,"vertical":False},"rotation":0.0,"scale":{"x":1.0,"y":1.0},"transform":{"x":0.0,"y":0.0}},"common_keyframes":[],"enable_adjust":True,"is_placeholder":False,"speed":1.0,"visible":True,"volume":0.0})
            cursor+=ct
        for chunk in subs:
            tid=self._uuid(); tt=self._seconds_to_ticks(float(chunk["duration_seconds"])); ts=self._seconds_to_ticks(float(chunk["start_seconds"]))
            texts.append(self._build_text_material(tid,str(chunk["text"])))
            tseg.append({"id":self._uuid(),"material_id":tid,"target_timerange":{"start":ts,"duration":tt},"source_timerange":{"start":0,"duration":tt},"extra_material_refs":[],"clip":{"alpha":1.0,"flip":{"horizontal":False,"vertical":False},"rotation":0.0,"scale":{"x":1.0,"y":1.0},"transform":{"x":SUBTITLE_POS_X,"y":SUBTITLE_POS_Y}},"common_keyframes":[],"enable_adjust":True,"is_placeholder":False,"speed":1.0,"visible":True})
        return {"id":self._uuid(),"name":f"{plan.client_name}_AI初稿","duration":total,"fps":DEFAULT_FPS,"color_space":0,"canvas_config":{"ratio":"9:16","width":DEFAULT_CANVAS_WIDTH,"height":DEFAULT_CANVAS_HEIGHT},"config":{"maintrack_adsorb":True,"material_save_mode":0,"subtitle_sync":True,"lyrics_sync":False,"video_mute":False},"keyframes":{"adjusts":[],"audios":[],"effects":[],"filters":[],"texts":[],"videos":[]},"materials":{"videos":videos,"audios":audios,"texts":texts,"canvases":canvases,"effects":[],"transitions":[],"video_effects":[],"sound_channel_mappings":sound_maps,"speeds":speeds,"audio_fades":[]},"tracks":[{"id":self._uuid(),"attribute":0,"flag":0,"is_default_name":False,"name":"视频主轨","type":"video","segments":vseg},{"id":self._uuid(),"attribute":0,"flag":0,"is_default_name":False,"name":"音频轨","type":"audio","segments":aseg},{"id":self._uuid(),"attribute":0,"flag":0,"is_default_name":False,"name":"字幕轨","type":"text","segments":tseg}],"platform":{"os":"windows","app":"jianying_pro"},"version":DEFAULT_DRAFT_VERSION,"created_at":self._now_iso(),"updated_at":self._now_iso()}
    def _build_text_material(self,tid:str,text:str)->dict[str,object]:
        content=json.dumps({"text":text,"styles":[{"range":[0,len(text)],"size":SUBTITLE_FONT_SIZE,"font_name":SUBTITLE_FONT_NAME,"color":"#FFFFFF","stroke_color":"#000000","stroke_width":SUBTITLE_STROKE_WIDTH,"bold":False,"italic":False,"underline":False,"scale":{"x":1.0,"y":1.0}}]},ensure_ascii=False)
        return {"id":tid,"type":"text","content":content,"text":text,"font_size":SUBTITLE_FONT_SIZE,"font_name":SUBTITLE_FONT_NAME,"font_path":"","text_color":"#FFFFFF","stroke_color":"#000000","stroke_width":SUBTITLE_STROKE_WIDTH,"background_alpha":0.0,"alignment":1,"bold":False,"italic":False,"underline":False,"scale":{"x":1.0,"y":1.0},"text_style":{"size":SUBTITLE_FONT_SIZE,"font_name":SUBTITLE_FONT_NAME,"color":"#FFFFFF","stroke_color":"#000000","stroke_width":SUBTITLE_STROKE_WIDTH,"scale":{"x":1.0,"y":1.0}}}
    def _build_subtitle_chunks(self,script_text:str,audio_duration_seconds:float)->list[dict[str,float|int|str]]:
        sentence_units=self._split_by_punctuation(script_text)
        if not sentence_units: return []
        slices=[]
        for unit in sentence_units:
            cleaned=self._normalize_subtitle_text(unit)
            if not cleaned: continue
            slices.extend(self._split_long_unit(cleaned))
        slices=self._merge_short_tail_chunks(slices)
        total=sum(len(x) for x in slices)
        if total<=0: return []
        tpc=audio_duration_seconds/total; cursor=0.0; out=[]
        for i,text in enumerate(slices):
            chars=len(text); dur=round(chars*tpc,3)
            if i==len(slices)-1: dur=round(max(audio_duration_seconds-cursor,0.0),3)
            start=round(cursor,3); cursor=round(cursor+dur,3)
            item={"text":text,"char_count":chars,"start_seconds":start,"duration_seconds":dur}; out.append(item)
            logger.info("[DraftRenderer][Subtitle] chunk=%s chars=%s start=%.3fs duration=%.3fs",text,chars,start,dur)
        logger.info("[DraftRenderer][Subtitle] 前 %s 条切片预览: %s",min(5,len(out)),out[:5]); return out
    def _split_by_punctuation(self,script_text:str)->list[str]:
        units=[]; buf=[]
        for ch in script_text:
            if ch in "\r\n": continue
            buf.append(ch)
            if ch in SENTENCE_PUNCTUATION:
                units.append("".join(buf)); buf=[]
        if buf: units.append("".join(buf))
        return units
    def _normalize_subtitle_text(self,text:str)->str:
        return re.sub(r"[\s]+","",text).strip("，。！？；：,.!?、")
    def _split_long_unit(self,text:str)->list[str]:
        if len(text)<=SUBTITLE_MAX_CHARS: return [text]
        chunks=[]; remaining=text
        while len(remaining)>SUBTITLE_MAX_CHARS:
            split_at=self._best_split_index(remaining)
            chunks.append(remaining[:split_at])
            remaining=remaining[split_at:]
        if remaining: chunks.append(remaining)
        return chunks
    def _best_split_index(self,text:str)->int:
        max_idx=min(len(text),SUBTITLE_MAX_CHARS); min_idx=min(SUBTITLE_MIN_CHARS,max_idx)
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
            if merged and len(chunk)<SUBTITLE_MIN_CHARS and len(merged[-1])+len(chunk)<=SUBTITLE_MAX_CHARS:
                merged[-1]+=chunk
            else:
                merged.append(chunk)
        return merged
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
    def _project_root(self)->Path: return Path(__file__).resolve().parents[2]
