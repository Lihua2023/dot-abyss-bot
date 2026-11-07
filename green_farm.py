"""Supervised depth-10 green-coat farm. F12 stops; uncertain screens stop safely.

Run with --observe to save one screenshot without input. --run enables clicks.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app_paths import RESOURCE_ROOT, FROZEN
if not FROZEN and sys.prefix == sys.base_prefix and (RESOURCE_ROOT / '.runtime').exists():
    sys.path.insert(0, str(RESOURCE_ROOT / '.runtime'))

import cv2
import numpy as np

from abyss_bot import GameWindow
from app_runtime import SingleInstance, stop_requested
from green_farm_policy import FarmObservation, GreenFarmPolicy
from green_loot import inspect as inspect_loot

SIZE=(1919,1079)
ASSETS=RESOURCE_ROOT/'assets'/'green_ui'
POINTS={
    'sortie':(1275,1016), 'chest':(1660,97), 'close_loot':(1774,104),
    'fc':(1600,870), 'fc_confirm':(960,540), 'retry':(1580,1018),
    'auto':(1440,1051),
}
JITTER_RANGES={
    'sortie':(35,12), 'quest_start':(25,10), 'chest':(18,10),
    'close_loot':(8,8), 'fc':(12,10), 'fc_confirm':(45,30),
    'retry':(28,14), 'auto':(22,6), 'loot_scroll':(80,60),
}


def _jitter_point(name,point):
    bx,by=point
    jx,jy=JITTER_RANGES.get(name,(6,6))
    dx=random.randint(-jx,jx) if jx>0 else 0
    dy=random.randint(-jy,jy) if jy>0 else 0
    return (max(8,min(SIZE[0]-8,int(bx)+dx)),max(8,min(SIZE[1]-8,int(by)+dy)))
TEMPLATES={name:cv2.imdecode(np.fromfile(str(ASSETS/f'{name}.png'),dtype=np.uint8),cv2.IMREAD_COLOR)
           for name in ('battle_title','chest_button','zero_digit','failed_title','retry_button',
                        'quest_title','sortie_button','aim_cancel',
                        'quest_title_zh','battle_title_zh','battle_title_suffix',
                        'explore_header','quest_start_button')}
TEMPLATES['quest_clear']=cv2.resize(
    cv2.imdecode(np.fromfile(str(RESOURCE_ROOT/'assets'/'templates'/'quest_clear.png'),dtype=np.uint8),cv2.IMREAD_COLOR),
    None,fx=1919/1470,fy=1919/1470,interpolation=cv2.INTER_NEAREST)
_AIM_MASK=np.ones(TEMPLATES['aim_cancel'].shape[:2],dtype=np.uint8)
_AIM_MASK[36:112,75:245]=0
_AIM_MASK3=cv2.merge([_AIM_MASK,_AIM_MASK,_AIM_MASK])


def score(frame,name,box,scales=(1.0,)):
    x1,y1,x2,y2=box
    area=frame[y1:y2,x1:x2]
    template=TEMPLATES[name]
    best=0.0
    for s in scales:
        t=template if s==1.0 else cv2.resize(template,None,fx=s,fy=s,interpolation=cv2.INTER_AREA if s<1 else cv2.INTER_LINEAR)
        if area.shape[0]<t.shape[0] or area.shape[1]<t.shape[1]: continue
        val=float(cv2.matchTemplate(area,t,cv2.TM_CCOEFF_NORMED).max())
        if val>best: best=val
    return best


def locate(frame,name,box,scales=(1.0,)):
    x1,y1,x2,y2=box
    area=frame[y1:y2,x1:x2]
    template=TEMPLATES[name]
    best=(-1.0,(x1,y1))
    for s in scales:
        t=template if s==1.0 else cv2.resize(template,None,fx=s,fy=s,interpolation=cv2.INTER_AREA if s<1 else cv2.INTER_LINEAR)
        if area.shape[0]<t.shape[0] or area.shape[1]<t.shape[1]: continue
        result=cv2.matchTemplate(area,t,cv2.TM_CCOEFF_NORMED)
        _,value,_,(x,y)=cv2.minMaxLoc(result)
        if value>best[0]:
            best=(float(value),(x1+x+t.shape[1]//2,y1+y+t.shape[0]//2))
    return best


def _detect_titlebar_height(image):
    h,w=image.shape[:2]
    if h<50 or w<400: return 0
    mid=image[:45,int(w*0.15):int(w*0.80),:]
    row_std=mid.std(axis=(1,2))
    row_diff=np.abs(np.diff(mid.mean(axis=(1,2))))
    for y in range(20,min(42,h-1)):
        if row_std[y]<12.0 and (row_diff[y]>8.0 or row_std[y+1]>15.0):
            return y+1
    client_w=w-2 if (w-2)%16==0 else w
    tb_geom=h-round(client_w*9/16)-(1 if (w-2)%16==0 else 0)
    if 20<=tb_geom<=42:
        return tb_geom
    return 0


def normalized(image):
    h,w=image.shape[:2]
    tb=_detect_titlebar_height(image)
    if tb>0 and abs(w/max(1,h-tb)-(16.0/9.0))<0.05 and h-tb>=700:
        top_bar=cv2.resize(image[:tb,:],(SIZE[0],38),interpolation=cv2.INTER_AREA)
        client_1080=cv2.resize(image[tb:,:],(SIZE[0],1080),interpolation=cv2.INTER_AREA)
        return np.vstack([top_bar,client_1080])[:SIZE[1],:SIZE[0]].copy()
    # The live game can extend 40 px below the desktop while its 1919×1079
    # visible content stays at the top-left, matching the supplied screenshots.
    if 1919<=w<=1930 and 1079<=h<=1130:
        return image[:1079,:1919].copy()
    return cv2.resize(image,SIZE,interpolation=cv2.INTER_AREA)


def energy(frame):
    hsv=cv2.cvtColor(frame[999:1012,1350:1870],cv2.COLOR_BGR2HSV)
    filled=[]
    for i in range(10):
        x=30+53*i
        patch=hsv[3:8,x-3:x+4]
        filled.append(float(np.mean((patch[:,:,1]<125)&(patch[:,:,2]>210))))
    # Partly filling a segment is not a whole energy point.
    value=0
    for amount in filled:
        if amount<.45: break
        value+=1
    return value, [round(x,2) for x in filled]


def auto_enabled(frame):
    """Return the AUTO toggle state, or None while the battle UI is obscured."""
    hsv=cv2.cvtColor(frame[1040:1050,1370:1400],cv2.COLOR_BGR2HSV)
    saturation=float(np.median(hsv[:,:,1]))
    brightness=float(np.median(hsv[:,:,2]))
    if brightness<200: return None
    if saturation>150: return True
    if saturation<60: return False
    return None


def _locate_close_loot(frame):
    hsv=cv2.cvtColor(frame[55:135,1740:1915],cv2.COLOR_BGR2HSV)
    ys,xs=np.where((hsv[:,:,0]>=80)&(hsv[:,:,0]<=110)&(hsv[:,:,1]>120)&(hsv[:,:,2]>180))
    if len(xs)>=20:
        return (int(round(xs.mean()))+1740,int(round(ys.mean()))+55)
    return POINTS['close_loot']


def observe_frame(image):
    f=normalized(image)
    scales=(0.95,1.0,1.05)
    fail_title=score(f,'failed_title',(25,50,520,160),scales)
    retry_score,retry_center=locate(f,'retry_button',(1440,890,1715,1075),scales)
    if fail_title>.82 and retry_score>.78:
        return {'state':'failed','frame':f,'retry_center':retry_center}
    if score(f,'quest_clear',(15,40,660,240),scales)>.86:
        return {'state':'won','frame':f}
    quest_title=max(
        score(f,'quest_title',(820,55,1110,145),scales),
        score(f,'quest_title_zh',(820,55,1110,145),scales),
    )
    sortie_score,sortie_center=locate(f,'sortie_button',(1080,880,1460,1075),scales)
    if quest_title>.78 and sortie_score>.78:
        return {'state':'quest','frame':f,'sortie_center':sortie_center,
                'quest_title_score':round(quest_title,3),'sortie_score':round(sortie_score,3)}
    loot=inspect_loot(f)
    if loot.panel_header_score>.82 and loot.panel_label_score>.82:
        return {'state':'loot','frame':f,'loot':loot}
    aim_score=score(f,'aim_cancel',(1535,875,1880,1069),scales)
    if aim_score<=.78:
        aim_area=f[875:1069,1535:1880]
        t_aim=TEMPLATES['aim_cancel']
        if aim_area.shape[0]>=t_aim.shape[0] and aim_area.shape[1]>=t_aim.shape[1]:
            masked_val=float(cv2.matchTemplate(aim_area,t_aim,cv2.TM_CCOEFF_NORMED,mask=_AIM_MASK3).max())
            if masked_val>.86:
                aim_score=masked_val
    if aim_score>.78:
        return {'state':'aim','frame':f}
    battle=max(
        score(f,'battle_title',(20,45,490,130),scales),
        score(f,'battle_title_zh',(20,45,490,130),scales),
        score(f,'battle_title_suffix',(200,45,490,130),scales),
    )
    chest=score(f,'chest_button',(1560,45,1760,150),scales)
    if battle>.78 and chest>.75:
        z=score(f,'zero_digit',(1687,78,1731,116))
        count=0 if z>.9 else (1 if z<.83 else None)
        power,segments=energy(f)
        # The crystal must be lit as well as the gauge having four full units.
        crystal=f[845:900,1565:1630]
        bright=float((cv2.cvtColor(crystal,cv2.COLOR_BGR2GRAY)>125).mean())
        return {'state':'battle','frame':f,'loot_count':count,'zero_score':round(z,3),
                'energy':power,'segments':segments,'fc_ready':power>=4 and bright>.20,
                'fc_brightness':round(bright,3),'auto_enabled':auto_enabled(f)}
    explore_score=score(f,'explore_header',(130,50,330,135),scales)
    start_score,start_center=locate(f,'quest_start_button',(30,780,1850,900),scales)
    if explore_score>.78 and start_score>.78:
        card_jp,card_jp_pt=locate(f,'battle_title',(20,585,1900,655),scales)
        card_zh,card_zh_pt=locate(f,'battle_title_zh',(20,585,1900,655),scales)
        card_score,card_pt=(card_zh,card_zh_pt) if card_zh>=card_jp else (card_jp,card_jp_pt)
        target_start=None
        if card_score>.72:
            bx1=max(20,card_pt[0]-220);bx2=min(1900,card_pt[0]+220)
            exp_glyph=TEMPLATES['battle_title_suffix'][12:42,8:62]
            exp_area=f[590:650,bx1:bx2]
            exp_sc=float(cv2.matchTemplate(exp_area,exp_glyph,cv2.TM_CCOEFF_NORMED).max()) if exp_area.shape[1]>=exp_glyph.shape[1] else 0.0
            btn_sc,btn_pt=locate(f,'quest_start_button',(bx1,780,bx2,900),scales)
            if exp_sc>.84 and btn_sc>.75:
                target_start=btn_pt
        return {'state':'quest_list','frame':f,'start_center':target_start or start_center,
                'card_matched':target_start is not None,'card_score':round(card_score,3)}
    return {'state':'unknown','frame':f,'battle_score':round(battle,3),'chest_score':round(chest,3)}


class Runner:
    def __init__(self,args):
        self.args=args
        self.win=GameWindow('ドットアビスX')
        self.dir=RESOURCE_ROOT/'runs'/'green_farm'/datetime.now().strftime('%Y%m%d-%H%M%S')
        self.dir.mkdir(parents=True,exist_ok=True)
        self.logfile=(self.dir/'events.jsonl').open('w',encoding='utf-8')
        self.policy=GreenFarmPolicy(first_drop_wait_seconds=8)
        self.started=None
        self.retry_count=0
        self.last_retry_at=None
        self.last_state=None
        self.state_since=time.monotonic()
        self.panel_first=None
        self.loot_scrolls=0
        self.last_thumb_bottom=None
        self.last_close_loot_at=None
        self.unknown_since=None
        self.last_log=None
        self.auto_seen_since=None
        self.auto_seen_state=None
        self.last_auto_click_at=None
        self.auto_unknown_since=None
        self.raw_size=None

    def _reset_battle_state(self):
        self.panel_first=None
        self.loot_scrolls=0
        self.last_thumb_bottom=None
        self.last_close_loot_at=None

    def ensure_auto(self, enabled, desired, now):
        """Toggle only after a stable observation and verify the next frame."""
        if enabled is None:
            self.auto_seen_state=None
            self.auto_seen_since=None
            return False
        if enabled!=self.auto_seen_state:
            self.auto_seen_state=enabled
            self.auto_seen_since=now
        if enabled==desired:
            return True
        if (now-self.auto_seen_since>=1.2 and
                (self.last_auto_click_at is None or now-self.last_auto_click_at>=3)):
            self.log('auto_toggle',from_state=enabled,to_state=desired)
            self.click('auto')
            self.last_auto_click_at=time.monotonic()
            self.auto_seen_state=None
            self.auto_seen_since=None
        return False

    def stopped_by_user(self):
        return stop_requested() or (self.args.stop_file is not None and self.args.stop_file.exists())

    def log(self,event,**data):
        item={'at':datetime.now().isoformat(timespec='seconds'),'event':event,**data}
        print(json.dumps(item,ensure_ascii=False),flush=True)
        self.logfile.write(json.dumps(item,ensure_ascii=False)+'\n');self.logfile.flush()

    def shot(self,label,image):
        path=self.dir/f'{datetime.now().strftime("%H%M%S")}-{label}.png'
        cv2.imencode('.png',image)[1].tofile(str(path))
        self.log('screenshot',label=label,path=str(path))

    def capture(self):
        image=self.win.capture()
        self.raw_size=(image.shape[1],image.shape[0],_detect_titlebar_height(image))
        obs=observe_frame(image)
        state=obs['state']
        if state!=self.last_state:
            self.log('state',state=state,details={k:v for k,v in obs.items() if k not in ('frame','loot')})
            self.last_state=state;self.state_since=time.monotonic()
            self.shot(state,image)
        return image,obs

    def _to_win_point(self,x,y):
        w,h,tb=self.raw_size if len(self.raw_size)==3 else (*self.raw_size,0)
        if tb>0 and abs(w/max(1,h-tb)-(16.0/9.0))<0.05 and h-tb>=700:
            raw_x=x*w/SIZE[0]
            raw_y=(y*tb/38.0) if y<38 else (tb+(y-38)*(h-tb)/1080.0)
            return (raw_x*1470/w,raw_y*864/h)
        elif 1919<=w<=1930 and 1079<=h<=1130:
            return (x*1470/w,y*864/h)
        else:
            return (x*1470/SIZE[0],y*864/SIZE[1])

    def click(self,name,point=None):
        if self.stopped_by_user(): raise RuntimeError('用户停止')
        base_pt=point or POINTS[name]
        x,y=_jitter_point(name,base_pt)
        self.log('click',button=name,point=(x,y),base_point=tuple(base_pt))
        self.win.click(self._to_win_point(x,y))

    def scroll_loot(self,lo):
        if self.stopped_by_user(): raise RuntimeError('用户停止')
        sx,sy=_jitter_point('loot_scroll',(960,580))
        win_pt=self._to_win_point(sx,sy)
        wheel_stuck=(self.loot_scrolls>=1 and self.last_thumb_bottom is not None
                     and lo.thumb_bottom is not None and lo.thumb_bottom-self.last_thumb_bottom<25)
        for _ in range(6):
            self.win.scroll(win_pt,-120)
            time.sleep(0.03)
        if wheel_stuck and lo.thumb_top is not None and lo.thumb_bottom is not None:
            ty=max(240,min(940,(lo.thumb_top+lo.thumb_bottom)//2))
            start_pt=self._to_win_point(1763+random.randint(-2,2),ty)
            end_pt=self._to_win_point(1763+random.randint(-2,2),985+random.randint(-8,8))
            self.win.drag(start_pt,end_pt,duration=0.25)
        self.last_thumb_bottom=lo.thumb_bottom
        self.log('loot_scroll',page=self.loot_scrolls+1,point=(sx,sy),
                 thumb_top=lo.thumb_top,thumb_bottom=lo.thumb_bottom,drag_fallback=wheel_stuck)
        time.sleep(0.35)

    def cast(self):
        self.click('fc')
        start=time.monotonic();spent=False
        while time.monotonic()-start<3:
            if self.stopped_by_user(): raise RuntimeError('用户停止')
            time.sleep(.35)
            image,obs=self.capture()
            if obs['state']=='aim':
                self.log('fc_aim_seen')
                self.click('fc_confirm')
                return
            if obs['state']=='battle' and obs['energy'] is not None and obs['energy']<4:
                spent=True
        if spent:
            self.log('fc_spent_without_aim')
            return
        self.shot('fc-unverified',image)
        raise RuntimeError('FC 选择后未确认瞄准态或扣能量，停止以免误点')

    def run(self):
        if self.args.delay: time.sleep(self.args.delay)
        image,obs=self.capture()
        if not self.args.run:
            self.log('observe_only',state=obs['state'])
            return
        if obs['state']=='quest':
            self.click('sortie',obs['sortie_center'])
            self._reset_battle_state()
            self.started=time.monotonic()
        elif obs['state']=='quest_list' and obs.get('card_matched'):
            self.log('quest_list_enter',point=obs['start_center'],card_score=obs.get('card_score'))
            self.click('quest_start',obs['start_center'])
            for _ in range(15):
                if self.stopped_by_user(): raise RuntimeError('用户停止')
                time.sleep(0.5)
                image,obs=self.capture()
                if obs['state']=='quest':
                    self.click('sortie',obs['sortie_center'])
                    self._reset_battle_state()
                    self.started=time.monotonic()
                    break
            else:
                raise RuntimeError('从探索任务列表点击开始后未进入任务详情页')
        elif self.args.resume_battle and obs['state']=='battle':
            self.log('resume_battle',reason='从当前战斗画面接管首轮观察')
            self._reset_battle_state()
            self.started=time.monotonic()-8
        elif obs['state']=='failed':
            self.click('retry',obs['retry_center'])
            self._reset_battle_state()
            self.last_retry_at=time.monotonic()
            self.started=time.monotonic()
        elif self.args.resume_loot and obs['state']=='loot':
            self.policy.phase='checking'
            self._reset_battle_state()
            self.started=time.monotonic()-10
            self.log('resume_loot',reason='接管已经打开的战利品面板')
        elif self.args.resume_aim and obs['state']=='aim':
            self.started=time.monotonic()-10
            self.policy.phase='after_first_fc'
            self.policy.fc_sent=True
            self.policy.first_fc_clicked_at=9
            self.policy.first_fc_energy_before=4
            self.click('fc_confirm')
            self.log('resume_aim',reason='完成已打开的FC确认')
        else:
            raise RuntimeError('预期任务详情或失败页；其他画面须显式使用 --resume-battle / --resume-loot / --resume-aim')
        if self.args.stop_after_sortie:
            time.sleep(3)
            self.capture()
            self.log('test_complete',reason='出击后停下校准战斗界面')
            return
        while True:
            if self.stopped_by_user(): raise RuntimeError('用户停止')
            if time.monotonic()-self.started>self.args.max_seconds:
                raise RuntimeError('达到测试时限，已停止')
            time.sleep(.6)
            image,obs=self.capture()
            state=obs['state']; now=time.monotonic()
            if state=='unknown':
                if self.unknown_since is None:self.unknown_since=now
                if now-self.unknown_since>18:
                    self.shot('unknown-stop',image)
                    raise RuntimeError('画面超过18秒无法识别，已停止')
                continue
            self.unknown_since=None
            if state=='aim':
                self.shot('unexpected-aim',image)
                raise RuntimeError('意外停在FC瞄准画面')
            if state=='quest':
                if now-self.state_since>12: raise RuntimeError('点击出击后仍在任务页')
                continue
            if state=='failed':
                # The failed page can remain visible briefly after a click. Do
                # not count or click it again while the transition is pending.
                if self.last_retry_at is not None and now-self.last_retry_at<6:
                    continue
                self.log('failed',retry_count=self.retry_count)
                if self.policy.keep_run:
                    self.shot('green-found-but-failed',image)
                    self.log('test_complete',reason='检出绿衣后战斗失败；已停止，不自动重试')
                    return
                if self.retry_count>=self.args.max_retries:
                    self.log('test_complete',reason='失败结算已验证')
                    return
                self.retry_count+=1
                self.policy=GreenFarmPolicy(first_drop_wait_seconds=8)
                self._reset_battle_state()
                self.click('retry',obs['retry_center'])
                self.last_retry_at=time.monotonic()
                self.started=time.monotonic()
                continue
            if state=='won':
                self.shot('victory-review',image)
                self.log('test_complete',reason='已到胜利结算，请人工确认绿衣实得')
                return
            if state=='loot':
                if self.policy.phase in ('lose','finish'):
                    if self.last_close_loot_at is None or now-self.last_close_loot_at>=1.2:
                        close_pt=_locate_close_loot(obs['frame'])
                        self.log('loot_reclose',phase=self.policy.phase,point=close_pt)
                        self.click('close_loot',close_pt)
                        self.last_close_loot_at=time.monotonic()
                    continue
                if self.policy.phase in ('opening','after_first_fc'):
                    self.policy.phase='checking'
                lo=obs['loot']
                self.log('loot_scan',scroll_page=self.loot_scrolls,**asdict(lo))
                if lo.status=='uncertain' or (lo.status=='found' and self.args.on_found=='pause'):
                    self.shot('loot-review',image)
                    raise RuntimeError('看到绿衣或相似图标；保留面板供人工确认')
                if self.panel_first is None:
                    self.panel_first=(now,lo.target_score)
                    continue
                wait_needed=1.0 if self.loot_scrolls>0 else 1.5
                if now-self.panel_first[0]<wait_needed: continue
                if abs(lo.target_score-self.panel_first[1])>.12:
                    self.shot('loot-unstable',image)
                    raise RuntimeError('战利品列表不稳定，暂停确认')
                if lo.status=='absent_visible' and lo.can_scroll_down and self.loot_scrolls<4:
                    self.shot(f'loot-page{self.loot_scrolls+1}-absent',image)
                    self.scroll_loot(lo)
                    self.loot_scrolls+=1
                    self.panel_first=None
                    continue
                action=self.policy.decide(FarmObservation(now-self.started,1,False,
                    panel_verdict=lo.status,panel_complete=True))
                if action!='close_loot': raise RuntimeError(f'意外决策 {action}')
                self.shot('loot-'+lo.status,image)
                self.click('close_loot',_locate_close_loot(obs['frame']))
                self.last_close_loot_at=time.monotonic()
                self.panel_first=None
                self.log('loot_decision',next_phase=self.policy.phase,scroll_pages=self.loot_scrolls+1)
                continue
            if state=='battle':
                if obs['auto_enabled'] is None:
                    if self.auto_unknown_since is None: self.auto_unknown_since=now
                    elif now-self.auto_unknown_since>10:
                        self.shot('auto-ambiguous',image)
                        raise RuntimeError('AUTO 状态连续 10 秒无法判断，已停止')
                else:
                    self.auto_unknown_since=None
                if self.policy.phase=='finish' and self.args.on_found=='auto':
                    if self.ensure_auto(obs['auto_enabled'],True,now):
                        if self.last_log!=('auto',True):
                            self.log('decision',phase='finish',action='wait_for_victory',auto_enabled=True)
                            self.last_log=('auto',True)
                    continue
                if not self.ensure_auto(obs['auto_enabled'],False,now):
                    continue
                if obs['loot_count'] is None:
                    if now-self.state_since>10:
                        self.shot('loot-count-ambiguous',image)
                        raise RuntimeError('宝箱计数不明确')
                    continue
                action=self.policy.decide(FarmObservation(
                    now-self.started,obs['loot_count'],obs['fc_ready'],obs['energy']))
                snap=(self.policy.phase,action,obs['loot_count'],obs['energy'],obs['fc_ready'])
                if snap!=self.last_log:
                    self.log('decision',phase=snap[0],action=snap[1],loot_count=snap[2],
                             energy=snap[3],fc_ready=snap[4],zero_score=obs['zero_score'])
                    self.last_log=snap
                if action=='open_loot': self.click('chest')
                elif action in ('cast_fc_once','cast_fc'): self.cast()
                elif action=='pause_for_review':
                    self.shot('policy-review',image)
                    raise RuntimeError('FC 点击未被能量变化确认')
                elif action=='settle':
                    self.shot('settle-review',image)
                    return


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observe',action='store_true',help='只观察并保存截图')
    p.add_argument('--run',action='store_true',help='启用鼠标点击')
    p.add_argument('--delay',type=float,default=2)
    p.add_argument('--max-seconds',type=float,default=180)
    p.add_argument('--max-retries',type=int,default=999)
    p.add_argument('--stop-after-sortie',action='store_true',help='测试出击后截图并退出')
    p.add_argument('--resume-battle',action='store_true',help='从已开始的战斗接管')
    p.add_argument('--resume-loot',action='store_true',help='从已打开的战利品页接管')
    p.add_argument('--resume-aim',action='store_true',help='从已打开的FC确认页接管')
    p.add_argument('--on-found',choices=('pause','auto'),default='pause',help='检出绿衣后暂停，或开启 AUTO 打到结算')
    p.add_argument('--continue-on-found',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--parent-owns-lock',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--stop-file',type=Path,help='桌面入口用于停止当前运行的信号文件')
    args=p.parse_args(argv)
    if args.run==args.observe: p.error('请选择 --observe 或 --run')
    if args.continue_on_found: args.on_found='auto'
    from contextlib import nullcontext
    with (nullcontext() if args.parent_owns_lock else SingleInstance()):
        runner=Runner(args)
        try: runner.run()
        except Exception as e:
            runner.log('stopped',reason=str(e))
            raise
        finally: runner.logfile.close()

if __name__=='__main__': main()
