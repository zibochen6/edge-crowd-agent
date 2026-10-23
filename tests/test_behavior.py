import pytest
from backend.behavior import RegionBehavior

def track(i,x):return {'id':i,'box':[x-.01,.2,x+.01,.5]}
def test_motion_groups_and_observed_stay_are_measured_and_deduplicated():
    b=RegionBehavior()
    for frame in range(26):
        t=frame/25;r=b.update([track(1,.2+t*.1),track(2,.7),track(2,.7)],[1,2],t)
    assert r['moving_count']==1 and r['low_displacement_count']==1
    assert r['current_roi_count']==2 and r['longest_continuous_roi_seconds']==1
    assert r['insufficient_count']==0

def test_disappearance_exit_and_seek_never_count_unseen_stay():
    b=RegionBehavior();b.update([track(1,.4)],[1],0)
    r=b.update([track(1,.5)],[1],5)
    assert r['longest_continuous_roi_seconds']==0 and r['insufficient_count']==1
    b.update([track(1,.5)],[],5.04)
    assert b.update([track(1,.5)],[1],5.08)['longest_continuous_roi_seconds']==0
    assert b.update([track(1,.5)],[1],0)['longest_continuous_roi_seconds']==0

def test_pause_does_not_grow_track_observation():
    b=RegionBehavior()
    for _ in range(100):r=b.update([track(1,.4)],[1],.4)
    assert r['longest_continuous_roi_seconds']==0
    assert len(b.tracks[1]['points'])==1
