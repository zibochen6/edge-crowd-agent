import csv
import json
import threading
import time
import uuid
import base64
from collections import deque
import cv2
from . import config
from .domain import Settings, OccupancyRule, Entries, occupancy
from .storage import atomic_json
from .behavior import RegionBehavior

class VideoService:
    def __init__(self,store,publish,on_event):
        self.store=store; self.publish=publish; self.on_event=on_event
        self.lock=threading.RLock();self.stop_event=threading.Event();self.idle=threading.Event();self.idle.set()
        row=store.db.execute('SELECT body,version FROM settings WHERE id=1').fetchone()
        self.settings=Settings.model_validate_json(row[0]) if row else Settings()
        self.version=row[1] if row else 1
        self.path=config.VIDEO; self.pending_reset=0.0; self.playing=True; self.loop=True; self.loop_cycle=1; self.loop_events={}; self.latest_event_id=None; self.speed=1.0;self.hold=False
        self.latest=None;self.error=None;self.backend='初始化中';self.fallback=None;self.fps=25.0;self.duration=0.0
        self.session='';self.video_time=0.0;self.closed=False
        self.thread=threading.Thread(target=self.run,name='crowd-vision',daemon=True)
    def start(self): self.thread.start()
    def status(self):
        with self.lock: return {'session_id':self.session,'playing':self.playing,'loop':self.loop,'loop_cycle':self.loop_cycle,'latest_event_id':self.latest_event_id,'speed':self.speed,'benchmark_hold':self.hold,'time':self.video_time,'duration':self.duration,'source':self.path.name,'backend':self.backend,'fallback':self.fallback,'error':self.error,'settings':self.settings.model_dump(),'config_version':self.version,'ready':self.latest is not None}
    def control(self,action,value=None):
        with self.lock:
            if action=='play': self.playing=True
            elif action=='pause':self.playing=False
            elif action=='loop':
                if value not in [0,1]:raise ValueError('循环开关仅支持 0 或 1')
                self.loop=bool(value)
            elif action=='speed':
                if value not in [0.5,1,1.5,2,4]:raise ValueError('播放速度不支持')
                self.speed=float(value)
            elif action in ['replay','rerun']: self.pending_reset=0.0;self.playing=True;self.loop_cycle=1;self.loop_events={};self.latest_event_id=None
            elif action=='seek':
                if value is None or not 0<=float(value)<self.duration:raise ValueError('定位超出视频范围')
                self.pending_reset=float(value);self.loop_cycle=1;self.loop_events={};self.latest_event_id=None
            else:raise ValueError('未知视频操作')
        return self.status()
    def configure(self,settings):
        with self.lock:
            self.settings=settings;self.version+=1;self.pending_reset=self.video_time;self.loop_cycle=1;self.loop_events={};self.latest_event_id=None
            with self.store.lock,self.store.db:
                self.store.db.execute('INSERT OR REPLACE INTO settings VALUES(1,?,?)',(settings.model_dump_json(),self.version))
        return self.status()
    def start_demo(self,mode,report_language='zh'):
        # Change mode and rewind as one operation so no intermediate session
        # can trigger an Agent using the previous mode or video position.
        with self.lock:
            settings=self.settings.model_copy(update={'mode':mode,'report_language':report_language,'enabled':True,'auto_agent':True})
            self.configure(settings)
            self.pending_reset=0.0;self.playing=True;self.loop=True;self.speed=1.0
            self.latest=None
            return self.status()
    def load(self,path,report_language=None):
        cap=cv2.VideoCapture(str(path));ok=cap.isOpened();cap.release()
        if not ok: raise ValueError('无法解码 MP4')
        with self.lock:
            if report_language and report_language!=self.settings.report_language:self.configure(self.settings.model_copy(update={'report_language':report_language}))
            self.path=path;self.pending_reset=0.0;self.playing=True;self.loop_cycle=1;self.loop_events={};self.latest_event_id=None
    def close(self): self.stop_event.set();self.thread.join(timeout=10)
    def run(self):
        from .vision import Detector,Tracker
        detector=None;cap=None;trace=None;table=None;last_display=0.0
        try:
            detector=Detector(); self.backend=detector.name;self.fallback=detector.fallback
            while not self.stop_event.is_set():
                with self.lock:
                    if self.hold:
                        self.idle.set(); wait=True; reset=None
                    else:
                        reset=self.pending_reset;self.pending_reset=None
                        wait=not self.playing and reset is None
                        if not wait:self.idle.clear()
                    settings=self.settings;version=self.version;speed=self.speed
                if wait: self.stop_event.wait(0.02);continue
                if reset is not None:
                    if cap:cap.release()
                    if trace:trace.close();table.close()
                    cap=cv2.VideoCapture(str(self.path))
                    if not cap.isOpened():raise RuntimeError(f'视频不存在或无法解码: {self.path}')
                    self.fps=cap.get(cv2.CAP_PROP_FPS) or 25.0
                    self.duration=cap.get(cv2.CAP_PROP_FRAME_COUNT)/self.fps
                    index=int(reset*self.fps);cap.set(cv2.CAP_PROP_POS_FRAMES,index)
                    tracker=Tracker(self.fps);rule=OccupancyRule(settings);entries=Entries();behavior=RegionBehavior();history=deque(maxlen=round(self.fps*8))
                    self.session=uuid.uuid4().hex[:12];folder=config.DATA/'sessions'/self.session;folder.mkdir(parents=True)
                    atomic_json(folder/'config.json',{'session_id':self.session,'video':str(self.path),'fps':self.fps,'start_seconds':reset,'config_version':version,'settings':settings.model_dump(),'detector_backend':self.backend,'engine':str(config.ENGINE),'onnx':str(config.ONNX),'confidence_low':0.1,'nms_iou':0.45})
                    trace=open(folder/'frames.jsonl','w');table=open(folder/'counts.csv','w',newline='')
                    writer=csv.writer(table);writer.writerow(['frame','video_seconds','full_count','roi_count','track_ids','cumulative_entries','state','detection_ms'])
                started=time.monotonic();ok,frame=cap.read()
                if not ok:
                    with self.lock:
                        if self.loop and self.playing:self.pending_reset=0.0;self.loop_cycle+=1
                        else:self.playing=False
                    self.idle.set();continue
                h,w=frame.shape[:2];t=index/self.fps
                boxes,scores,ms=detector.detect(frame);tracks=tracker.update(boxes,scores,w,h)
                with self.lock:
                    if version!=self.version or self.pending_reset is not None:continue
                    full,ids=occupancy(tracks,settings.polygon);total=entries.update(ids,[v['id'] for v in tracks]);trigger=rule.step(len(ids),t)
                    behavior_evidence=behavior.update(tracks,ids,t)
                    sample={'behavior_evidence':behavior_evidence,'frame':index,'video_seconds':t,'full_count':full,'roi_count':len(ids),'track_ids':ids,'tracks':tracks,'cumulative_entries':total,'state':rule.state,'trigger_elapsed_seconds':rule.trigger_elapsed(t),'detection_ms':ms}
                    history.append({k:sample[k] for k in ['video_seconds','full_count','roi_count','track_ids']})
                    trace.write(json.dumps(sample)+'\n');trace.flush()
                    writer.writerow([index,t,full,len(ids),json.dumps(ids),total,rule.state,ms]);table.flush()
                    if trigger and index in self.loop_events:
                        self.latest_event_id=self.loop_events[index]
                    elif trigger:
                        eid='EVT-'+uuid.uuid4().hex[:12]
                        snapshot=config.DATA/'snapshots'/f'{eid}.jpg'
                        if not cv2.imwrite(str(snapshot),frame):raise RuntimeError('抓拍写入失败')
                        event={'behavior_evidence':behavior_evidence,'event_id':eid,'event_type':'occupancy_threshold','camera_id':'CAM-01','zone_id':'ZONE-A','session_id':self.session,'config_version':version,'video_seconds':t,'video_source':str(self.path),'threshold':settings.threshold,'current_count':len(ids),'full_count':full,'duration_above_threshold_sec':t-rule.since,'track_ids':ids,'snapshot_path':f'snapshots/{eid}.jpg','status':'triggered','settings':settings.model_dump(),'count_history':list(history),'created_at':time.time()}
                        self.latest_event_id=eid;self.loop_events[index]=eid
                        self.store.save_event(event);atomic_json(config.DATA/'snapshots'/f'{eid}.json',event)
                        self.publish({'type':'event','event':event})
                        if settings.auto_agent:self.on_event(event,settings.mode)
                    now=time.monotonic()
                    if now-last_display>=0.1 or index==int(round(self.duration*self.fps))-1 or trigger:
                        display=cv2.resize(frame,(min(w,960),round(h*min(w,960)/w)))
                        image=base64.b64encode(cv2.imencode('.jpg',display,[cv2.IMWRITE_JPEG_QUALITY,65])[1]).decode()
                        message={'type':'frame',**sample,'session_id':self.session,'config_version':version,'polygon':settings.polygon,'settings':settings.model_dump(),'width':w,'height':h,'jpeg':image,'playing':self.playing,'loop_cycle':self.loop_cycle,'backend':self.backend,'processing_fps':1/max(time.monotonic()-started,0.00001)}
                        with self.lock:self.latest=message
                        self.publish(message);last_display=now
                    with self.lock:self.video_time=t
                index+=1;self.idle.set()
                # Inference never skips source frames to make the displayed FPS look faster.
                self.stop_event.wait(max(0,1/self.fps/speed-(time.monotonic()-started)))
        except Exception as exc:
            self.error=f'{type(exc).__name__}: {exc}';self.playing=False
            self.publish({'type':'video_error','error':self.error})
        finally:
            self.idle.set()
            if cap:cap.release()
            if trace:trace.close();table.close()
            if detector:detector.close()
            self.closed=True
