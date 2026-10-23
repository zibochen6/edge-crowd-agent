import math
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Settings(Strict):
    polygon: list[list[float]] = Field(default_factory=lambda: [[0.18,0.20],[0.75,0.20],[0.75,0.92],[0.18,0.92]])
    threshold: int = Field(default=5, ge=1, le=500)
    trigger_seconds: float = Field(default=1.5, ge=0, le=60)
    recovery_count: int = Field(default=3, ge=0, le=499)
    recovery_seconds: float = Field(default=2.0, ge=0, le=60)
    cooldown_seconds: float = Field(default=10.0, ge=0, le=600)
    enabled: bool = True
    auto_agent: bool = True
    report_language: Literal['zh','en'] = 'zh'
    mode: Literal['off','on'] = 'off'

    @model_validator(mode='after')
    def valid(self):
        if self.recovery_count >= self.threshold:
            raise ValueError('恢复人数必须小于触发阈值')
        p=self.polygon
        if p and (len(p)<3 or len(p)>32):
            raise ValueError('ROI 需要 3–32 个顶点，或空数组删除区域')
        if any(len(v)!=2 or any(not math.isfinite(x) or x<0 or x>1 for x in v) for v in p):
            raise ValueError('ROI 坐标必须位于 [0,1]')
        if p:
            area=abs(sum(p[i][0]*p[(i+1)%len(p)][1]-p[(i+1)%len(p)][0]*p[i][1] for i in range(len(p))))/2
            if area<0.0001: raise ValueError('ROI 面积过小')
            def orient(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            for i in range(len(p)):
                for j in range(i+1,len(p)):
                    if j==i+1 or (i==0 and j==len(p)-1): continue
                    a,b,c,d=p[i],p[(i+1)%len(p)],p[j],p[(j+1)%len(p)]
                    if orient(a,b,c)*orient(a,b,d)<0 and orient(c,d,a)*orient(c,d,b)<0:
                        raise ValueError('ROI 不能自交')
        return self

def inside(point, polygon):
    x,y=point; result=False
    for a,b in zip(polygon, polygon[1:]+polygon[:1]):
        cross=(x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        if abs(cross)<1e-10 and min(a[0],b[0])-1e-10<=x<=max(a[0],b[0])+1e-10 and min(a[1],b[1])-1e-10<=y<=max(a[1],b[1])+1e-10:
            return True
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]: result=not result
    return result

def occupancy(tracks, polygon):
    active={int(t['id']):t for t in tracks}
    ids=sorted(k for k,t in active.items() if inside(((t['box'][0]+t['box'][2])/2,t['box'][3]),polygon))
    return len(active),ids

class Entries:
    def __init__(self): self.previous={}; self.total=0
    def update(self, ids, active_ids=None):
        current=set(ids)
        active=set(active_ids) if active_ids is not None else set(self.previous)|current
        for tid in active:
            now=tid in current
            if now and not self.previous.get(tid,False):self.total+=1
            self.previous[tid]=now
        return self.total

class OccupancyRule:
    def __init__(self, settings):
        self.s=settings; self.state='NORMAL'; self.since=None; self.last_t=None; self.last_alert=-math.inf
    def trigger_elapsed(self, t):
        # Use the processed video timestamp; wall time must never advance this timer.
        if self.state in ('ALERT', 'RECOVERY'): return self.s.trigger_seconds
        if self.state=='PENDING' and self.since is not None:
            return min(self.s.trigger_seconds, max(0.0, t-self.since))
        return 0.0
    def step(self, count, t):
        if self.last_t is not None and (t<self.last_t or t-self.last_t>0.25):
            self.state='NORMAL'; self.since=None
        self.last_t=t
        if not self.s.enabled or not self.s.polygon:
            self.state='NORMAL'; self.since=None; return False
        if self.state=='NORMAL':
            if count>=self.s.threshold and t-self.last_alert>=self.s.cooldown_seconds:
                self.state='PENDING'; self.since=t
        if self.state=='PENDING':
            if count<self.s.threshold: self.state='NORMAL'; self.since=None
            elif t-self.since+1e-8>=self.s.trigger_seconds:
                self.state='ALERT'; self.last_alert=t; return True
        elif self.state=='ALERT':
            if count<=self.s.recovery_count: self.state='RECOVERY'; self.since=t
        elif self.state=='RECOVERY':
            if count>self.s.recovery_count: self.state='ALERT'; self.since=None
            elif t-self.since+1e-8>=self.s.recovery_seconds: self.state='NORMAL'; self.since=None
        return False

class AlertArgs(Strict):
    event_id: str
    level: Literal['info','warning']
    title: str = Field(min_length=1,max_length=120)
    description: str = Field(min_length=1,max_length=3000)
class NotifyArgs(Strict):
    event_id: str
    message: str = Field(min_length=1,max_length=3000)
    priority: Literal['normal','high']
class ReportArgs(Strict):
    event_id: str
    report_content: str = Field(min_length=20,max_length=20000)
class Decision(Strict):
    create_alert: AlertArgs
    notify_operator: NotifyArgs
    report_tool: Literal['save_report']

class ToolPlan(Strict):
    event_id: str
    actions: list[Literal['create_alert','notify_operator']] = Field(min_length=2,max_length=2)
    report_tool: Literal['save_report']

    @model_validator(mode='after')
    def valid_actions(self):
        if self.actions!=['create_alert','notify_operator']:
            raise ValueError('工具必须依次创建告警、通知操作员，不得重复或缺失')
        return self
