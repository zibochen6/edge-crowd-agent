"""Observable ROI track motion; no identity, intent or action recognition."""
import math
from collections import deque

class RegionBehavior:
    window_seconds=3.0
    minimum_seconds=0.8
    moving_threshold=0.012  # image diagonal fraction per video second

    def __init__(self):
        self.tracks={}

    def update(self, tracks, roi_ids, t):
        ids=set(roi_ids)
        self.tracks={key:value for key,value in self.tracks.items() if key in ids and t-value['last']<=.25 and t>=value['last']}
        seen=set()
        for track in tracks:
            tid=track['id']
            if tid not in ids or tid in seen:continue
            seen.add(tid)
            box=track['box'];point=((box[0]+box[2])/2,box[3])
            state=self.tracks.setdefault(tid,{'first':t,'last':t,'points':deque()})
            state['last']=t
            points=state['points']
            if not points or points[-1][0]!=t:points.append((t,point))
            while len(points)>1 and points[0][0]<t-self.window_seconds:points.popleft()
        moving=low=insufficient=0;details=[]
        for tid in sorted(seen):
            state=self.tracks[tid];points=state['points'];span=t-points[0][0]
            displacement=math.dist(points[0][1],points[-1][1])/math.sqrt(2)
            speed=displacement/span if span>0 else None
            category='insufficient' if span<self.minimum_seconds else 'moving' if speed>=self.moving_threshold else 'low_displacement'
            moving+=category=='moving';low+=category=='low_displacement';insufficient+=category=='insufficient'
            details.append({'track_id':tid,'continuous_roi_seconds':round(t-state['first'],2),'observed_motion_seconds':round(span,2),'net_displacement_fraction':round(displacement,5),'category':category})
        return {'source':'tracked_bbox_bottom_center','window_seconds':self.window_seconds,'minimum_observation_seconds':self.minimum_seconds,'moving_threshold_diagonal_fraction_per_second':self.moving_threshold,'current_roi_count':len(seen),'moving_count':moving,'low_displacement_count':low,'insufficient_count':insufficient,'longest_continuous_roi_seconds':max((v['continuous_roi_seconds'] for v in details),default=0),'tracks':details,'limitations':'位移来自画面归一化坐标，不是物理速度；连续可见时长不包含片段前或遮挡期间。不能据此识别打斗、跌倒或人员意图。'}
