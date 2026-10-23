import pytest
from backend.domain import Settings,inside,occupancy,Entries,OccupancyRule,Decision

def test_polygon_boundary_and_scale():
    p=[[.2,.2],[.8,.2],[.8,.8],[.2,.8]]
    assert inside((.2,.5),p) and inside((.5,.5),p)
    assert not inside((.9,.5),p)
    assert inside((960/1920,540/1080),p)==inside((480/960,270/540),p)
def test_tracks_current_and_duplicate():
    t={'id':4,'box':[.3,.1,.5,.5]}
    assert occupancy([t,t],[[0.,0.],[1.,0.],[1.,1.],[0.,1.]])==(1,[4])
    assert occupancy([],[[0.,0.],[1.,0.],[1.,1.]])==(0,[])
def test_entries():
    e=Entries();assert e.update([1,1,2])==2;assert e.update([1,2])==2;assert e.update([])==2;assert e.update([1])==3
def test_short_tracking_loss_does_not_count_new_entry():
    e=Entries();assert e.update([1],[1])==1
    assert e.update([],[])==1
    assert e.update([1],[1])==1
    assert e.update([],[1])==1
    assert e.update([1],[1])==2
def test_threshold_jitter_and_cooldown():
    r=OccupancyRule(Settings())
    alerts=[]
    for frame in range(1000):
        t=frame/25
        count=5 if t<3 or t>9 else 3
        if r.step(count,t):alerts.append(t)
    assert alerts[0]==1.52
    assert len(alerts)==2
    assert alerts[1]-alerts[0]>=10
def test_pause_has_no_elapsed_time():
    r=OccupancyRule(Settings());r.step(5,0)
    for _ in range(100):assert not r.step(5,0)
    assert r.state=='PENDING'
    assert r.trigger_elapsed(0)==0
def test_many_entries_below_current_occupancy_threshold_never_trigger():
    entries=Entries();rule=OccupancyRule(Settings())
    for frame in range(250):
        ids=[frame] if frame%2 else []
        entries.update(ids, [frame])
        assert not rule.step(len(ids),frame/25)
    assert entries.total>rule.s.threshold
    assert rule.state=='NORMAL' and rule.trigger_elapsed(249/25)==0
def test_trigger_progress_uses_continuous_video_time_and_resets():
    rule=OccupancyRule(Settings())
    for frame in range(26):rule.step(5,frame/25)
    assert rule.trigger_elapsed(1)==1
    rule.step(4,1.04)
    assert rule.trigger_elapsed(1.04)==0
    rule.step(5,1.08);rule.step(5,10)
    assert rule.trigger_elapsed(10)==0
    for frame in range(1,40):rule.step(5,10+frame/25)
    assert rule.state=='ALERT' and rule.trigger_elapsed(11.56)==1.5
def test_seek_resets_pending():
    r=OccupancyRule(Settings());r.step(5,0);assert not r.step(5,10)
    assert r.state=='PENDING' and r.since==10
    r.step(5,0);assert r.since==0
def test_disabled_and_deleted_roi():
    assert not OccupancyRule(Settings(enabled=False)).step(100,0)
    assert not OccupancyRule(Settings(polygon=[])).step(100,0)
@pytest.mark.parametrize('change',[{'polygon':[[0.,0.],[1.,1.],[0.,1.],[1.,0.]]},{'polygon':[[2.,0.],[1.,0.],[0.,1.]]},{'threshold':3,'recovery_count':3},{'threshold':-1}])
def test_settings_reject_invalid(change):
    with pytest.raises(ValueError):Settings(**change)
def test_invalid_llm_json():
    with pytest.raises(ValueError):Decision.model_validate_json('{"shell":"rm -rf"}')
