"""Supervised depth-10 green-coat farm. F12 stops; uncertain screens stop safely.

Run with --observe to save one screenshot without input. --run enables clicks.
"""
from __future__ import annotations

import argparse
import json
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
TEMPLATES={name:cv2.imdecode(np.fromfile(str(ASSETS/f'{name}.png'),dtype=np.uint8),cv2.IMREAD_COLOR)
           for name in ('battle_title','chest_button','zero_digit','failed_title','retry_button',
                        'quest_title','sortie_button','aim_cancel')}
TEMPLATES['quest_clear']=cv2.resize(
    cv2.imdecode(np.fromfile(str(RESOURCE_ROOT/'assets'/'templates'/'quest_clear.png'),dtype=np.uint8),cv2.IMREAD_COLOR),
    None,fx=1919/1470,fy=1919/1470,interpolation=cv2.INTER_NEAREST)


def score(frame,name,box):
    x1,y1,x2,y2=box
    area=frame[y1:y2,x1:x2]
    template=TEMPLATES[name]
    if area.shape[0]<template.shape[0] or area.shape[1]<template.shape[1]: return 0.0
    return float(cv2.matchTemplate(area,template,cv2.TM_CCOEFF_NORMED).max())


def locate(frame,name,box):
    x1,y1,x2,y2=box
    template=TEMPLATES[name]
    result=cv2.matchTemplate(frame[y1:y2,x1:x2],template,cv2.TM_CCOEFF_NORMED)
    _,value,_,(x,y)=cv2.minMaxLoc(result)
    return float(value),(x1+x+template.shape[1]//2,y1+y+template.shape[0]//2)


def normalized(image):
    h,w=image.shape[:2]
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


def observe_frame(image):
    f=normalized(image)
    fail_title=score(f,'failed_title',(25,60,510,150))
    retry_score,retry_center=locate(f,'retry_button',(1450,900,1705,1075))
    if fail_title>.82 and retry_score>.78:
        return {'state':'failed','frame':f,'retry_center':retry_center}
    if score(f,'quest_clear',(15,45,650,230))>.86:
        return {'state':'won','frame':f}
    quest_title=score(f,'quest_title',(830,65,1100,140))
    sortie_score,sortie_center=locate(f,'sortie_button',(1090,890,1450,1070))
    if quest_title>.78 and sortie_score>.78:
        return {'state':'quest','frame':f,'sortie_center':sortie_center}
    loot=inspect_loot(f)
    if loot.panel_header_score>.82 and loot.panel_label_score>.82:
        return {'state':'loot','frame':f,'loot':loot}
    if score(f,'aim_cancel',(1535,875,1880,1069))>.78:
        return {'state':'aim','frame':f}
    battle=score(f,'battle_title',(25,55,480,125))
    chest=score(f,'chest_button',(1570,50,1750,145))
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
        self.unknown_since=None
        self.last_log=None
        self.auto_seen_since=None
        self.auto_seen_state=None
        self.last_auto_click_at=None
        self.auto_unknown_since=None
        self.raw_size=None

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
        self.raw_size=(image.shape[1],image.shape[0])
        obs=observe_frame(image)
        state=obs['state']
        if state!=self.last_state:
            self.log('state',state=state,details={k:v for k,v in obs.items() if k not in ('frame','loot')})
            self.last_state=state;self.state_since=time.monotonic()
            self.shot(state,image)
        return image,obs

    def click(self,name,point=None):
        if self.stopped_by_user(): raise RuntimeError('用户停止')
        x,y=point or POINTS[name]
        self.log('click',button=name,point=(x,y))
        w,h=self.raw_size
        if 1919<=w<=1930 and 1079<=h<=1130:
            self.win.click((x*1470/w,y*864/h))
        else:
            self.win.click((x*1470/SIZE[0],y*864/SIZE[1]))

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
            self.started=time.monotonic()
        elif self.args.resume_battle and obs['state']=='battle':
            self.log('resume_battle',reason='从当前战斗画面接管首轮观察')
            self.started=time.monotonic()-8
        elif obs['state']=='failed':
            self.click('retry',obs['retry_center'])
            self.last_retry_at=time.monotonic()
            self.started=time.monotonic()
        elif self.args.resume_loot and obs['state']=='loot':
            self.policy.phase='checking'
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
                if self.last_retry_at is not None and now-self.last_retry_at<4:
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
                self.click('retry',obs['retry_center'])
                self.last_retry_at=time.monotonic()
                self.started=time.monotonic()
                continue
            if state=='won':
                self.shot('victory-review',image)
                self.log('test_complete',reason='已到胜利结算，请人工确认绿衣实得')
                return
            if state=='loot':
                lo=obs['loot']
                self.log('loot_scan',**asdict(lo))
                if lo.status=='uncertain' or (lo.status=='found' and self.args.on_found=='pause'):
                    self.shot('loot-review',image)
                    raise RuntimeError('看到绿衣或相似图标；保留面板供人工确认')
                if self.panel_first is None:
                    self.panel_first=(now,lo.target_score)
                    continue
                if now-self.panel_first[0]<1.5: continue
                if abs(lo.target_score-self.panel_first[1])>.12:
                    self.shot('loot-unstable',image)
                    raise RuntimeError('战利品列表不稳定，暂停确认')
                action=self.policy.decide(FarmObservation(now-self.started,1,False,
                    panel_verdict=lo.status,panel_complete=True))
                if action!='close_loot': raise RuntimeError(f'意外决策 {action}')
                self.shot('loot-'+lo.status,image)
                self.click('close_loot')
                self.panel_first=None
                self.log('loot_decision',next_phase=self.policy.phase)
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
