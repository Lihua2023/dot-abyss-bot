"""Dot Abyss visual runner. Defaults to observation; --run explicitly enables input.

Unknown screens keep monitoring with recovery snapshots. No game-memory access.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import re
import sys
import time
import queue
import threading
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from farm_policy import FarmSession, CATEGORIES, COLOR_NAMES, choose_event, increases_erosion, normalize_route_priority

from app_paths import RESOURCE_ROOT as ROOT, FROZEN, data_root, default_config_path, load_config, asset_path
from app_runtime import countdown, stop_requested
if not FROZEN and sys.prefix == sys.base_prefix and (ROOT / '.runtime').exists():
    sys.path.insert(0, str(ROOT / '.runtime'))
import cv2
import numpy as np
from PIL import Image, ImageGrab
cv2.setNumThreads(1)

BASE = (1470, 864)

class ScreenshotWriter:
    """Keep disk encoding off the capture/click loop; flush on exit."""
    def __init__(self, max_pending=8, max_files=2000):
        self.jobs=queue.Queue(maxsize=max_pending)
        self.max_files=max_files
        self.accepted=0
        self.dropped=0
        self.worker=threading.Thread(target=self._write,daemon=True)
        self.worker.start()

    def _write(self):
        while True:
            job=self.jobs.get()
            try:
                if job is None:return
                path,raw=job
                ok,encoded=cv2.imencode('.jpg',raw,[cv2.IMWRITE_JPEG_QUALITY,90])
                if not ok:raise OSError('JPEG 编码失败')
                encoded.tofile(str(path))
            except Exception as exc:
                print('截图保存失败：'+str(exc),flush=True)
            finally:self.jobs.task_done()

    def save(self,path,raw):
        if self.accepted>=self.max_files:
            self.dropped+=1
            return
        try:
            self.jobs.put_nowait((path,raw.copy()))
            self.accepted+=1
        except queue.Full:
            self.dropped+=1

    def close(self):
        self.jobs.put(None)
        self.jobs.join()
        if self.dropped:print(f'截图容量保护：跳过 {self.dropped} 张可选截图',flush=True)

@dataclass
class Decision:
    state: str
    action: str = 'wait'
    point: tuple[int, int] | None = None
    reason: str = ''
    floor: int | None = None
    erosion: int | None = None
    category: str | None = None
    points: dict | None = None
    scroll_delta: int = 0

def read_image(path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Cannot read image: {path}')
    return image

def normalized(image):
    return cv2.resize(image, BASE, interpolation=cv2.INTER_AREA)

def supported_window_ratio(width,height):
    # Both historical title-bar-inclusive windows and the game's standard
    # 16:9 preset windows are valid. Keep portrait/ultrawide layouts excluded.
    return width>0 and height>0 and min(abs(width/height-ratio) for ratio in (BASE[0]/BASE[1],16/9))<=.05

def pending_allowed_states(state, expected):
    """A transient page classification must not block a visible option menu."""
    allowed=set(expected)|({'erosion_cancel'}-{state})
    allowed|={'erosion_notice'}-{state}
    allowed|={'lost_signal_decline'}-{state}
    allowed|={'exploration_failed'}-{state}
    # End-of-run screens may directly follow a reward dismissal. They must
    # supersede any old pending action, including a code or shop confirmation.
    allowed |= {'boss_return','boss_return_confirm','return_score','return_score_skip',
                'return_points','return_items','return_result'}-{state}
    if state=='boss_return_confirm':
        allowed.discard('boss_return')  # underlying page can flash during dismissal
    if state not in {'code_select','code_selected','code_received','shop','shop_confirm'}:
        allowed |= {'code_select','code_received','event_result','item_reward','transport',
                    'recovery','recovery_selected','event_skip','event_selected',
                    'chest','chest_selected','chest_skip'}-{state}
    # Reconcile with any recognized actionable page. The origin is excluded:
    # repeated resource confirmations still use their own retry/budget rules.
    allowed |= {'entrance','resume','checkpoint_select','checkpoint_selected',
                'formation','skip_confirm','key_confirm','party_confirm',
                'map','battle','battle_result','boss_continue','code_select',
                'code_selected','code_received','recovery','recovery_selected',
                'event_skip','event_selected','event_result','shop','shop_exit',
                'shop_confirm','item_reward','transport','transport_confirm',
                'chest','chest_selected','chest_skip'}-{state}
    if state in {'skip_confirm','key_confirm','party_confirm'}:
        allowed.discard('formation')  # dismissed modal briefly exposes its backdrop
    return allowed

def stall_recovery_due(now, state_since, pending, last_recovery, config):
    interval=config.get('stall_recovery_seconds',5.0)
    started=pending['at'] if pending else state_since
    return now-started>=interval and now-last_recovery>=interval

def network_retry_delay(attempts, config):
    """Keep reconnecting, with bounded backoff after the fast retry budget."""
    fast=max(1,int(config.get('max_network_retries_per_action',10)))
    base=max(.1,float(config.get('network_retry_cooldown_seconds',.8)))
    return min(10.,base*2**min(4,max(0,(attempts-1)//fast)))

def page_wait_limit(state, config):
    if state=='battle':return config['battle_timeout_seconds']
    if state=='loading':return config.get('loading_timeout_seconds',90)
    return config['unknown_timeout_seconds']

def runtime_decision(decision):
    """A blocked action waits for correction; it must not terminate the runner."""
    if decision.action=='stop' and decision.state!='tickets_empty':
        return Decision(decision.state,reason='等待画面恢复或手动处理：'+decision.reason,
                        floor=decision.floor,erosion=decision.erosion)
    return decision

def overlay_close_ready(decision,now,last_close,close_visible=True):
    # Permit fast retries only with a freshly verified X. Shop text alone can
    # survive the transition even after the map menu becomes clickable.
    is_close=decision.state=='menu_close' or (decision.state=='shop_exit' and decision.point==(1410,73))
    delay=.15 if decision.state=='shop_exit' else .8
    return not is_close or (close_visible and now-last_close>=delay)

def decision_signature(decision):
    point=None if decision.state in {'boss_return_confirm','party_confirm'} else decision.point
    return decision.state,decision.action,point,decision.floor

class Vision:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session
        self.templates = {}
        manifest = asset_path(config.get('template_manifest','assets/templates/manifest.json'))
        if not manifest.exists():
            raise RuntimeError('先运行 python build_templates.py 生成模板')
        for name, item in json.loads(manifest.read_text(encoding='utf-8')).items():
            self.templates[name] = (read_image(manifest.parent / item['file']), item['roi'])
        self.ocr_engine = None
        self.scaled_templates = {}
        self.map_expected = False
        self.last_map_floor = None
        self.last_map_erosion = None
        self.map_wait_started = None
        self.event_choice_cache = None
        self.last_map_keys = None
        self.chest_trial_started = None
        self.event_rejected_x = None
        self.shop_bag_pending = False
        self.shop_bag_rejected = False
        self.shop_purchase_rejected = False
        title=self.templates.get('preferred_erosion_code_title')
        self.preferred_code_titles=[]
        if title:
            gray=cv2.cvtColor(title[0],cv2.COLOR_BGR2GRAY)
            self.preferred_code_titles=[cv2.resize(gray,None,fx=s,fy=s) for s in (.65,.8,1.,1.15,1.3)]
        self.route_priority=normalize_route_priority(config.get('route_priority'))

    def recover_stalled(self, raw, decision, pending=None):
        """Use the current screen, not the old action's expected successor."""
        safe_states={'map','event_skip','event_selected','event_result','recovery',
                     'recovery_selected','shop','shop_exit','battle_result','item_reward',
                     'code_select','code_selected','code_received','transport','chest','chest_skip',
                     'boss_return','boss_return_confirm','return_score','return_score_skip','return_points','return_items','return_result','erosion_cancel','erosion_notice','lost_signal_decline','menu_close'}
        if decision.action=='click' and decision.state in safe_states:
            if pending and pending['state']=='boss_return_confirm' and decision.state=='boss_return':
                if time.monotonic()-pending.get('at',time.monotonic())<self.config.get('stall_recovery_seconds',5):
                    return None
            if decision.state=='shop' and pending and pending['state'] in {'shop','shop_confirm'}:
                return Decision('shop_exit','click',(1410,73),'超时恢复：回到商店，退出避免重复购买')
            return decision
        if decision.state=='shop' and decision.action=='wait':
            return Decision('shop_exit','click',(1410,73),'商店读取失败，立即退出继续推进')
        # Battle, loading, network errors and explicit stop conditions keep
        # their normal handling. Never click blank coordinates on these pages.
        if decision.state not in {'unknown','map'} or decision.action=='stop':
            return None
        im=normalized(raw)
        if self.has(im,'action_header',.75):
            if self.has(im,'shop_price_coin',.8) and (self.has(im,'shop_anchor',.75) or self.has(im,'shop_key_label',.75)):
                return Decision('shop_exit','click',(1410,73),'超时恢复：退出未能识别的商店')
            if self.has(im,'recovery_purify',.65) or self.has(im,'recovery_rest',.75):
                left_selected=self.recovery_left_selected(im)
                if left_selected and self.yellow_button(im,(635,765,831,800)):
                    return Decision('recovery_selected','click',(735,781),'超时恢复：确认左侧净化')
                return Decision('recovery','click',(322,497),'超时恢复：选择左侧净化')
            # The left box is shared by recovery and ordinary event menus.
            # Confirm only after selection; otherwise select left first.
            choices=self.event_options(im,quick_only=True)
            x=choose_event(choices,['special_battle','code','other','skip'])
            if x is None:return Decision('event_skip','click',(1410,73),'超时恢复：关闭均增加侵蚀的事件')
            return Decision('event_skip','click',(x,493),'超时恢复：重新选择安全项，不直接确认旧选项')
        if self.has(im,'map_floor_label',.75) and self.has(im,'map_title',.60):
            floor=self.map_floor_number(im)
            target=self.session.target_floor if self.session else self.config['target_floor']
            if floor is not None and floor<target:
                return self.map_fallback(im,floor)
        return None

    def glowing_platforms(self, im):
        """Next row only; exclude the character row and the fixed sidebar."""
        hsv=cv2.cvtColor(im[410:620,90:1250],cv2.COLOR_BGR2HSV)
        lit=(hsv[:,:,2]>235)&(hsv[:,:,1]<80)
        mask=cv2.morphologyEx(np.uint8(lit)*255,cv2.MORPH_CLOSE,np.ones((9,19),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[cv2.boundingRect(c) for c in contours if cv2.contourArea(c)>1800]
        boxes=[b for b in boxes if b[2]>=85 and b[3]>=40]
        return sorted([(90+x+w//2,410+y+h//2) for x,y,w,h in boxes],key=lambda p:(self.route_rank(im,*p),abs(p[0]-735),p[0]))

    def route_rank(self,im,x,y):
        rect=(max(0,x-130),max(0,y+15),min(1470,x+130),min(864,y+100))
        kind='unknown'
        if self.within(im,'node_elite_text',rect,.82):kind='elite'
        elif self.within(im,'node_battle_text',rect,.82):kind='battle'
        elif 'node_chest_text' in self.templates and self.within(im,'node_chest_text',rect,.82):kind='chest'
        else:
            for candidate in ('event','recovery','shop'):
                name='node_'+candidate+'_text'
                if name in self.templates and self.within(im,name,rect,.82):
                    kind=candidate
                    break
        priority=self.route_priority
        if kind=='recovery' and self.last_map_erosion is not None and self.last_map_erosion>=self.config.get('purify_priority_at',60):
            return -1
        return priority.index(kind) if kind in priority else len(priority)

    def map_fallback(self, im, floor=None, erosion=None):
        if self.map_wait_started is None:
            self.map_wait_started=time.monotonic()
        if time.monotonic()-self.map_wait_started<self.config.get('map_fallback_after_seconds',.6):
            return None
        points=self.glowing_platforms(im)
        if points:
            return Decision('map','click',points[0],'识别失败兜底：直接选择下方发光平台',floor,erosion)
        return None

    def match(self, image, name):
        template, (x1, y1, x2, y2) = self.templates[name]
        roi = image[y1:y2, x1:x2]
        if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
            return 0., (0, 0)
        if name in {'action_header','map_title','map_floor_label','code_header','reward_title','quest_clear','formation_title','formation_title_jp','event_result_next','battle_auto','battle_menu','battle_clock'}:
            roi=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
            template=cv2.cvtColor(template,cv2.COLOR_BGR2GRAY)
        scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, pos = cv2.minMaxLoc(scores)
        best=(float(score),(x1+pos[0]+template.shape[1]//2,y1+pos[1]+template.shape[0]//2))
        # Window chrome and the game's render scale change independently.
        # Retry small local anchors at nearby scales, never a full-frame scan.
        scalable={'code_header','code_decline','code_decline_wide','reroll',
                  'code_received_message','reward_title','code_confirm','action_header',
                  'recovery_purify','recovery_rest','shop_anchor','shop_key_label','shop_price_coin',
                  'shop_confirm_title','transport_title','transport_list',
                  'boss_continue_title','boss_continue_button','boss_return_button',
                  'return_confirm_message','return_confirm_button','return_score_heading',
                  'return_score_label','return_score_skip','return_score_next',
                  'return_items_heading','return_bonus_heading','item_reward_title','item_reward_next',
                  'skip_title','key_title','formation_title','formation_title_jp',
                  'checkpoint_heading','checkpoint_card','quest_clear','chest_title',
                  'main_menu_auto_icon','main_menu_help_icon','main_menu_close','shop_close_x',
                  'entrance_records','entrance_keys','entrance_tap_pattern','entrance_ticket_pattern',
                  'party_warning','challenge','network_title','network_body','network_retry',
                  'erosion_notice80_body','erosion_notice80_next','lost_signal_title','lost_signal_decline','exploration_failed_title'}
        if name in scalable and score<.94:
            if name not in self.scaled_templates:
                self.scaled_templates[name]=[cv2.resize(template,None,fx=s,fy=s) for s in (.96,.94,.98,1.02,1.04,1.06)]
            left,top=max(0,x1-24),max(0,y1-24)
            area=image[top:min(864,y2+32),left:min(1470,x2+24)]
            if template.ndim==2:area=cv2.cvtColor(area,cv2.COLOR_BGR2GRAY)
            for variant in self.scaled_templates[name]:
                if area.shape[0]<variant.shape[0] or area.shape[1]<variant.shape[1]:continue
                _,value,_,location=cv2.minMaxLoc(cv2.matchTemplate(area,variant,cv2.TM_CCOEFF_NORMED))
                if value>best[0]:best=(float(value),(left+location[0]+variant.shape[1]//2,top+location[1]+variant.shape[0]//2))
                if best[0]>=.94:break
        return best

    def has(self, image, name, threshold=None):
        if name=='map_floor_label':
            return max(self.match(image,name)[0],self.match(image,'map_floor_label_wide')[0]) >= (threshold or self.config['template_threshold'])
        return self.match(image, name)[0] >= (threshold or self.config['template_threshold'])

    def map_floor_number(self,im):
        wide=self.match(im,'map_floor_label_wide')[0]>self.match(im,'map_floor_label')[0]
        return self.number(im,(120,116,153,145) if wide else (96,117,129,150))

    def within(self, image, name, rect, threshold=.88):
        template, _ = self.templates[name]
        x1,y1,x2,y2 = rect
        roi=image[max(0,y1):min(864,y2),max(0,x1):min(1470,x2)]
        if roi.shape[0]<template.shape[0] or roi.shape[1]<template.shape[1]:
            return False
        score=cv2.minMaxLoc(cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED))[1]
        if score>=threshold:return True
        if name.startswith('node_'):
            if name not in self.scaled_templates:
                self.scaled_templates[name]=[cv2.resize(template,None,fx=s,fy=s) for s in (.96,.94,.98)]
            for variant in self.scaled_templates[name]:
                if roi.shape[0]>=variant.shape[0] and roi.shape[1]>=variant.shape[1] and cv2.minMaxLoc(cv2.matchTemplate(roi,variant,cv2.TM_CCOEFF_NORMED))[1]>=threshold:
                    return True
        return False

    def text(self, image, rect):
        if self.ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine = RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        x1, y1, x2, y2 = rect
        crop = image[y1:y2, x1:x2]
        crop = cv2.resize(crop, None, fx=2, fy=2)
        result, _ = self.ocr_engine(crop,use_cls=False)
        return ' '.join(str(row[1]) for row in (result or []) if float(row[2]) >= .65)

    def number(self, image, rect):
        if self.ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        x1,y1,x2,y2=rect
        crop=cv2.copyMakeBorder(image[y1:y2,x1:x2],5,5,5,5,cv2.BORDER_REPLICATE)
        result,_=self.ocr_engine.text_rec(crop)
        if not result or float(result[0][1])<.85:
            return None
        text=str(result[0][0]).strip()
        if re.fullmatch(r'\d{1,3}(?:[.．]\d{3})+',text):
            text=text.replace('.','').replace('．','')
        return int(re.sub(r'[\s,，]', '', text)) if re.fullmatch(r'[0-9\s,，]+', text) else None

    def ratio(self, image, rect):
        if self.ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        x1,y1,x2,y2=rect
        crop=cv2.copyMakeBorder(image[y1:y2,x1:x2],4,4,4,4,cv2.BORDER_REPLICATE)
        result,_=self.ocr_engine.text_rec(crop)
        if not result or float(result[0][1])<.8:
            return None
        match=re.fullmatch(r'(\d+)[/／](\d+)',re.sub(r'\s+','',str(result[0][0])))
        return (int(match[1]),int(match[2])) if match else None

    def line(self,image,rect):
        if self.ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr_engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        x1,y1,x2,y2=rect
        result,_=self.ocr_engine.text_rec(image[y1:y2,x1:x2])
        return str(result[0][0]) if result and float(result[0][1])>.6 else ''

    def event_options(self,im,quick_only=False):
        """Locate three/four cards and read only the individual keyword lines."""
        hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
        mask=np.uint8((hsv[:,:,0]>100)&(hsv[:,:,0]<140)&(hsv[:,:,1]>100)&(hsv[:,:,2]>150))*255
        mask[:380]=0
        mask[735:]=0
        contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[]
        for c in contours:
            x,y,w,h=cv2.boundingRect(c)
            if 230<=w<=300 and 240<=h<=330:
                boxes.append((x,y,w,h))
        cards=[]
        for x,y,w,h in sorted(boxes,key=lambda b:b[2],reverse=True):
            centre=x+w//2
            if not any(abs(centre-old[0])<35 for old in cards):
                cards.append((centre,y,y+h))
        cards.sort()
        if len(cards) not in (3,4):
            cards=[(x,411,712) for x in (390,735,1080)]
        # Known bilingual effect words bypass OCR completely. These anchors
        # are below the title, where the actual special-event reward is shown.
        fast=[]
        found_keyword=False
        deadline=time.monotonic()+self.config.get('event_read_timeout_seconds',.4)
        for x,top,bottom in cards:
            if quick_only and time.monotonic()>=deadline:
                fast.extend((c[0],'') for c in cards[len(fast):])
                return fast
            rect=(x-132,top+150,x+132,bottom-20)
            label=''
            if self.within(im,'event_special_word',rect,.85):label+='特殊 '
            if self.within(im,'event_code_effect',rect,.85):label+='代码 '
            if self.within(im,'event_erosion_word',rect,.85) and self.within(im,'event_erosion_up',rect,.85):label+='侵食上昇 '
            found_keyword=found_keyword or bool(label)
            fast.append((x,label))
        if found_keyword or quick_only:return fast
        if self.ocr_engine is None:self.line(im,(260,470,520,525))
        crops=[]
        owners=[]
        def add_line(x,y0,y1):
            row=im[y0:y1,x-128:x+128]
            hsv=cv2.cvtColor(row,cv2.COLOR_BGR2HSV)
            h,s,v=cv2.split(hsv)
            ink=((s<75)&(v>180))|((h<32)&(s>150)&(v>160))|((h>40)&(h<90)&(s>90)&(v>160))
            pixels=cv2.findNonZero(np.uint8(ink))
            if pixels is None:return
            a,b,w,height=cv2.boundingRect(pixels)
            crops.append(row[max(0,b-3):min(row.shape[0],b+height+3),max(0,a-3):min(row.shape[1],a+w+3)])
            owners.append(x)
        for x,top,bottom in cards:
            add_line(x,top+55,top+110)
            y0=top+155
            crop=im[y0:bottom-12,x-128:x+128]
            color=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
            hue,sat,val=cv2.split(color)
            ink=((sat<75)&(val>180))|((hue<32)&(sat>150)&(val>160))|((hue>40)&(hue<90)&(sat>90)&(val>160))
            rows=np.flatnonzero(ink.sum(axis=1)>8)
            groups=np.split(rows,np.where(np.diff(rows)>3)[0]+1)
            for group in groups:
                if len(group)<5:continue
                a,b=int(group[0]),int(group[-1])+1
                if b-a>35:continue
                add_line(x,y0+max(0,a-3),min(bottom-8,y0+b+3))
        texts={c[0]:[] for c in cards}
        if crops:
            results,_=self.ocr_engine.text_rec(crops)
            for owner,result in zip(owners,results):
                if float(result[1])>.55:texts[owner].append(str(result[0]))
        return [(x,' '.join(texts[x])) for x,_,_ in cards]

    def category(self, im, rect):
        x1,y1,x2,y2=rect
        hsv=cv2.cvtColor(im[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        hue=hsv[:,:,0][(hsv[:,:,1]>80)&(hsv[:,:,2]>80)]
        if len(hue)<100:
            return None
        bins={'safe':((hue>=85)&(hue<=115)).mean(),
              'risk':((hue>=125)&(hue<=165)).mean(),
              'impact':((hue>=15)&(hue<=40)).mean(),
              'rush':((hue<=12)|(hue>=170)).mean()}
        name=max(bins,key=bins.get)
        return name if bins[name]>=.3 else None

    def preferred_code(self,im):
        if not self.config.get('prefer_erosion_code',True):return None
        for x in (350,735,1116):
            roi=cv2.cvtColor(im[416:477,x-175:x+175],cv2.COLOR_BGR2GRAY)
            if any(cv2.minMaxLoc(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED))[1]>=.9
                   for t in self.preferred_code_titles if t.shape[0]<=roi.shape[0] and t.shape[1]<=roi.shape[1]):
                return x
        return None

    def bag_symbol(self,im,rect):
        x1,y1,x2,y2=rect
        roi=im[y1:y2,x1:x2]
        template=self.templates['shop_bag_symbol'][0]
        for scale in (1.,.8,.9):
            t=cv2.resize(template,None,fx=scale,fy=scale)
            if roi.shape[0]>=t.shape[0] and roi.shape[1]>=t.shape[1] and cv2.minMaxLoc(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED))[1]>=.85:return True
        return False

    def gold_bag_frame(self,im,rect):
        x1,y1,x2,y2=rect
        hsv=cv2.cvtColor(im[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        mask=np.zeros(hsv.shape[:2],dtype=bool)
        mask[:8,:]=True;mask[-8:,:]=True;mask[:,:8]=True;mask[:,-8:]=True
        gold=(hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>100)&(hsv[:,:,2]>150)
        return gold[mask].mean()>.2

    def yellow_button(self, im, rect):
        x1,y1,x2,y2=rect
        hsv=cv2.cvtColor(im[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        return ((hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>150)&(hsv[:,:,2]>160)).mean()>.4

    def recovery_left_selected(self,im):
        # The left edge shifts with title-bar and preset scaling. Require a
        # long cyan vertical frame, excluding the blue illustration inside.
        hsv=cv2.cvtColor(im[380:650,130:210],cv2.COLOR_BGR2HSV)
        cyan=(hsv[:,:,0]>75)&(hsv[:,:,0]<105)&(hsv[:,:,1]>100)&(hsv[:,:,2]>180)
        return bool(cyan.mean(axis=0).max()>.65)

    def shop_close_visible(self,raw):
        # Validate the X itself, not fading shop text behind the map menu.
        return self.has(normalized(raw),'shop_close_x',.92)

    def entrance_patterns_visible(self,im):
        return ('entrance_tap_pattern' in self.templates
                and self.has(im,'entrance_tap_pattern',.88)
                and self.has(im,'entrance_ticket_pattern',.88))

    def code_receive_point(self,im):
        x1,y1,x2,y2=840,715,1050,850
        hsv=cv2.cvtColor(im[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        mask=np.uint8((hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>150)&(hsv[:,:,2]>160))*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        boxes=[cv2.boundingRect(c) for c in contours if cv2.contourArea(c)>1500]
        boxes=[b for b in boxes if b[2]>100 and b[3]>20]
        if not boxes:return None
        x,y,w,h=max(boxes,key=lambda b:b[2]*b[3])
        return x1+x+w//2,y1+y+h//2

    def checkpoint_rows(self, im):
        if self.ocr_engine is None:self.line(im,(870,300,1060,420))
        crop=cv2.resize(im[287:548,850:1105],None,fx=2,fy=2)
        result,_=self.ocr_engine(crop,use_cls=False)
        rows={}
        for box,label,confidence in result or []:
            match=re.fullmatch(r'\s*(\d{1,3})\s*[FfＦ]\s*',str(label))
            if match and float(confidence)>=.8:
                floor=int(match[1])
                if floor in range(10,101,10):
                    rows[floor]=(850+int(np.mean([p[0] for p in box])/2),287+int(np.mean([p[1] for p in box])/2))
        return rows

    def total_number(self,im,rect):
        # Keep room for thousands, but trim empty space for the digit recognizer.
        x1,y1,x2,y2=rect
        hsv=cv2.cvtColor(im[y1:y2,x1:x2],cv2.COLOR_BGR2HSV)
        mask=np.uint8((hsv[:,:,1]<80)&(hsv[:,:,2]>190))*255
        pixels=cv2.findNonZero(mask)
        if pixels is None or len(pixels)<8:return None
        x,y,w,h=cv2.boundingRect(pixels)
        return self.number(im,(max(x1,x1+x-2),max(y1,y1+y-2),min(x2,x1+x+w+2),min(y2,y1+y+h+2)))

    def calibrated_screen(self, im):
        # Additional account/UI layouts are opt-in and require two sampled anchors.
        for screen in self.config.get('extra_screens', []):
            anchors=screen.get('anchors',[])
            if len(anchors)<2 or not all(a in self.templates and self.has(im,a) for a in anchors):
                continue
            state=screen['state']
            if state=='return_result':
                regions=screen.get('point_regions',{})
                if set(regions)!=set(CATEGORIES) or 'floor_region' not in screen:
                    return Decision(state,'stop',reason='结算点数及完成层数区域尚未校准')
                points={k:self.number(im,regions[k]) for k in CATEGORIES}
                floor=self.number(im,screen['floor_region'])
                if floor is None or any(v is None for v in points.values()):
                    return Decision(state,'stop',reason='结算累计点数或层数无法可靠读取')
                return Decision(state,'click',tuple(screen['point']),'核对结算并返回入口',floor,points=points)
            if state in {'entrance','checkpoint_select','checkpoint_selected'}:
                return Decision(state,'click',tuple(screen['point']),'使用已校准的检查点入口')
        return None

    def plan(self, raw):
        im = normalized(raw)
        action_menu=self.has(im,'action_header',.8)
        if not action_menu and not self.has(im,'erosion_warning_body',.85):
            self.event_choice_cache=None
            self.event_rejected_x=None
        chest_menu='chest_title' in self.templates and self.has(im,'chest_title',.85)
        if not chest_menu:
            self.chest_trial_started=None
        # Modal states take priority over the page behind them.
        if self.has(im,'network_title',.85) and self.has(im,'network_body',.88) and (self.has(im,'network_retry',.88) or self.yellow_button(im,(630,760,838,800))):
            return Decision('network_retry','click',(735,780),'通信超时，重试原请求')
        if ('main_menu_close' in self.templates and self.has(im,'main_menu_auto_icon',.88)
                and self.has(im,'main_menu_help_icon',.88) and self.has(im,'main_menu_close',.88)):
            return Decision('menu_close','click',self.match(im,'main_menu_close')[1],'关闭误开的地图菜单，继续刷取')
        if self.has(im,'erosion_warning_body',.85) and self.has(im,'erosion_warning_cancel',.85):
            borders=[]
            for x in (390,735,1080):
                border=cv2.cvtColor(im[410:710,x-146:x-133],cv2.COLOR_BGR2HSV)
                strength=((border[:,:,0]>75)&(border[:,:,0]<105)&(border[:,:,1]>100)&(border[:,:,2]>90)).mean()
                borders.append((strength,x))
            strength,x=max(borders)
            if strength>.05:self.event_rejected_x=x
            self.event_choice_cache=None
            return Decision('erosion_cancel','click',(600,585),'侵蚀超过100%警告：取消危险选项')
        if ('erosion_notice80_body' in self.templates and self.has(im,'erosion_notice80_body',.88)
                and self.has(im,'erosion_notice80_next',.88)):
            return Decision('erosion_notice','click',self.match(im,'erosion_notice80_next')[1],
                            '确认当前侵蚀80%提示，继续流程；不确认超过100%的危险选项')
        if ('lost_signal_title' in self.templates and self.has(im,'lost_signal_title',.88)
                and self.has(im,'lost_signal_decline',.88)):
            return Decision('lost_signal_decline','click',self.match(im,'lost_signal_decline')[1],
                            '失败后不使用防丢失道具，关闭并继续结算')
        if ('exploration_failed_title' in self.templates and self.has(im,'exploration_failed_title',.88)
                and self.has(im,'erosion_notice80_next',.88)):
            return Decision('exploration_failed','click',self.match(im,'erosion_notice80_next')[1],
                            '关闭探索失败提示，清理结算后重开；不计完成轮数')
        if self.has(im,'return_confirm_message',.88) and self.has(im,'return_confirm_button',.88):
            return Decision('boss_return_confirm','click',self.match(im,'return_confirm_button')[1],'确认归还领取探索奖励')
        if self.has(im,'return_score_heading',.88) and self.has(im,'return_score_label',.88):
            # The return action already records the verified target floor.
            # Score/level digits are optional display data, never a click gate.
            skip_score,skip_point=self.match(im,'return_score_skip')
            if skip_score>=.85:
                return Decision('return_score_skip','click',skip_point,'立即跳过结算动画')
            next_score,next_point=self.match(im,'return_score_next')
            if next_score>=.85:
                return Decision('return_score','click',next_point,'归还结算直接下一页，不读取结算数字')
            return Decision('return_score',reason='等待结算下一页或跳过按钮显示')
        if self.has(im,'return_items_heading',.88) and self.has(im,'return_bonus_heading',.88):
            return Decision('return_points','click',(1375,795),'奖励结算直接下一页，不读取累计点数')
        if self.has(im,'checkpoint_heading',.88) and self.has(im,'checkpoint_card',.88):
            checkpoint=self.config['checkpoint']
            if self.yellow_button(im,(800,763,978,797)):
                if checkpoint<=30:
                    selected=self.number(im,(869,604,900,637))
                else:
                    match=re.search(r'(\d{1,3})\s*[FfＦ]',self.line(im,(865,604,1105,638)))
                    selected=int(match[1]) if match else None
                if selected==checkpoint:
                    return Decision('checkpoint_selected','click',(891,781),'已核对检查点，立即确认')
            rows=self.checkpoint_rows(im)
            if checkpoint in rows:
                return Decision('checkpoint_select','click',rows[checkpoint],'按层数文字选择配置的检查点')
            if rows:
                delta=3 if checkpoint<min(rows) else -3
                return Decision('checkpoint_select','scroll',(975,470),'滚动查找已解锁检查点',scroll_delta=delta)
            return Decision('checkpoint_select','stop',reason='无法读取已解锁检查点列表')
        entrance_text=self.has(im,'entrance_records',.88) and self.has(im,'entrance_keys',.88)
        entrance_patterns=False if entrance_text else self.entrance_patterns_visible(im)
        if entrance_text or entrance_patterns:
            if self.has(im,'resume_yellow',.85) or self.has(im,'resume',.85):
                return Decision('resume','click',(750,610),'立即恢复已有探索')
            if self.number(im,(966,188,999,216))==0:
                return Decision('tickets_empty','stop',reason='深渊门票已用完')
            return Decision('entrance','click',(750,610),
                            '入口图案兜底：直接点击传送门' if entrance_patterns else '从检查点开始下一轮')
        calibrated=self.calibrated_screen(im)
        if calibrated:
            return calibrated
        if self.has(im,'transport_title',.85) and self.has(im,'transport_list',.85):
            if self.config.get('transport_policy','skip')=='skip':
                return Decision('transport','click',(874,766),'跳过物品带回，继续刷代码')
            empty=sum(self.within(im,'transport_empty',(x-55,170,x+55,278),.88) for x in (550,734,918))
            if self.config.get('transport_fast',True):
                if empty<3 and self.yellow_button(im,(1020,750,1200,785)):
                    return Decision('transport_confirm','click',(1112,765),'立即确认带回奖励')
                score,point=self.match(im,'transport_skip_item')
                if score>.82:
                    return Decision('transport','click',point,'优先带回SKIP券，立即确认')
            if empty==0 and self.yellow_button(im,(1020,750,1200,785)):
                return Decision('transport_confirm','click',(1112,765),'确认将选中奖励送回据点')
            # Select an observed item card, never cancel a populated inventory.
            for y in (480,634):
                for x in (350,502,653,804,955,1107):
                    border=cv2.cvtColor(im[y-58:y+58,x-62:x-50],cv2.COLOR_BGR2HSV)
                    selected_border=((border[:,:,0]>75)&(border[:,:,0]<105)&(border[:,:,1]>100)&(border[:,:,2]>140)).mean()>.25
                    if selected_border:
                        continue
                    if self.within(im,'transport_selected_mark',(x-48,y-72,x+48,y-32),.82):
                        continue
                    hsv=cv2.cvtColor(im[y-54:y+54,x-54:x+54],cv2.COLOR_BGR2HSV)
                    if ((hsv[:,:,1]>100)&(hsv[:,:,2]>100)).mean()>.08:
                        return Decision('transport','click',(x,y),'选择奖励带回据点')
            if empty<3 and self.yellow_button(im,(1020,750,1200,785)):
                return Decision('transport_confirm','click',(1112,765),'确认带回现有奖励')
            return Decision('transport','click',(874,766),'没有可带回物品，关闭空列表')
        # The heading sparkles during entry. Two static, distinct buttons are
        # also sufficient to identify this panel while its heading animates.
        if self.has(im,'boss_continue_button',.9) and (self.has(im,'boss_continue_title') or self.has(im,'boss_return_button',.9)):
            next_floor=self.number(im,(731,211,760,239))
            if next_floor is None:
                return Decision('boss_continue','stop',reason='下一层数字无法可靠读取')
            completed=next_floor-1
            target=self.session.target_floor if self.session else self.config['target_floor']
            if completed>=target:
                return Decision('boss_return','click',(735,693),'已到目标层，归还领取',completed)
            if self.number(im,(924,566,981,609))==0:
                return Decision('tickets_empty','stop',reason='继续探索所需深渊门票已用完')
            return Decision('boss_continue','click',(971,693),'未到目标层，继续探索',completed)
        if self.has(im,'shop_confirm_title',.85) and self.yellow_button(im,(760,679,945,712)):
            balance=self.number(im,(829,610,904,648))
            after=self.number(im,(1050,610,1110,648))
            if self.shop_bag_pending:
                bag=self.bag_symbol(im,(367,250,464,355))
                gold=self.gold_bag_frame(im,(362,244,477,360))
                if bag and gold and balance is not None and after is not None and balance>=300 and balance-after==300:
                    return Decision('shop_confirm','click',(853,694),'购买已核对的300币金色装备袋')
                self.shop_bag_rejected=True
                return Decision('shop_exit','click',(615,694),'金袋商品或扣款无法核对，取消购买')
            # Buy only a visually identified code, never equipment or a premium purchase.
            icon=im[250:343,367:464]
            hsv=cv2.cvtColor(icon,cv2.COLOR_BGR2HSV)
            colored=(hsv[:,:,1]>100)&(hsv[:,:,2]>100)
            if colored.mean()<.12:
                self.shop_purchase_rejected=True
                return Decision('shop_exit','click',(615,694),'无法确认代码商品，取消购买并离店')
            balance=self.number(im,(829,610,904,648))
            after=self.number(im,(1050,610,1110,648))
            if balance is None or after is None or not 0<balance-after<=self.config.get('max_shop_code_cost',100):
                self.shop_purchase_rejected=True
                return Decision('shop_exit','click',(615,694),'价格或余额无法核对，取消购买并离店')
            return Decision('shop_confirm','click',(853,694),'购买已选深渊代码')
        if self.has(im,'item_reward_title') and self.has(im,'item_reward_next'):
            return Decision('item_reward','click',(735,633),'关闭物品奖励')
        result_border=cv2.cvtColor(im[317:340,:],cv2.COLOR_BGR2HSV)
        pink_border=((result_border[:,:,0]>125)&(result_border[:,:,0]<165)&(result_border[:,:,1]>50)&(result_border[:,:,2]>230))[:,100:1370].mean(axis=1).max()>.85
        lower_border=cv2.cvtColor(im[550:578,:],cv2.COLOR_BGR2HSV)
        pink_lower=((lower_border[:,:,0]>125)&(lower_border[:,:,0]<165)&(lower_border[:,:,1]>50)&(lower_border[:,:,2]>230))[:,100:1370].mean(axis=1).max()>.85
        if ((self.has(im,'event_result_bar',.85) or pink_border) and self.has(im,'event_result_next',.80)) or (pink_border and pink_lower and not self.has(im,'action_header',.8)):
            return Decision('event_result','click',(1000,700),'点击空白，立即关闭事件结果')
        if self.has(im, 'skip_title',.85):
            return Decision('skip_confirm', 'click', (520, 585), '正常探索，不使用跳过券')
        if self.has(im, 'key_title',.88):
            tickets=self.number(im,(1124,291,1174,328))
            if tickets==0:
                return Decision('tickets_empty','stop',reason='深渊门票已用完')
            if not self.yellow_button(im,(760,696,945,733)):
                return Decision('key_confirm',reason='钥匙确认弹窗出现中，等待按钮可用')
            found=self.ratio(im,(710,525,759,557))
            multiplier=found[0] if found and found[1]==3 else None
            if multiplier is None:
                # After the daily bonus is used the slider may disappear.
                # Verify both fixed 1x labels instead of waiting for a 1/3.
                score=self.number(im,(872,350,899,387))
                drops=self.number(im,(872,392,899,432))
                if score==1 and drops==1:multiplier=1
                else:return Decision('key_confirm',reason='等待门票倍率数字清晰')
            if multiplier != 1:
                return Decision('key_confirm', 'stop', reason='未确认钥匙倍率为1，禁止消耗')
            return Decision('key_confirm', 'click', (850, 715), '只使用1把钥匙')
        if self.has(im, 'party_warning',.88) and self.has(im, 'challenge',.88):
            return Decision('party_confirm', 'click', (850, 650), '使用已选编队')
        if self.has(im, 'code_received_message') and self.has(im, 'reward_title'):
            return Decision('code_received', 'click', (735, 793), '确认代码已领取')
        if chest_menu:
            if self.chest_trial_started is None:self.chest_trial_started=time.monotonic()
            def selected_card(x):
                border=cv2.cvtColor(im[380:650,x-179:x-164],cv2.COLOR_BGR2HSV)
                return ((border[:,:,0]>75)&(border[:,:,0]<105)&(border[:,:,1]>100)&(border[:,:,2]>180)).mean()>.25
            left_selected=selected_card(322)
            hp_selected=selected_card(735)
            if (left_selected or hp_selected) and self.yellow_button(im,(635,765,831,800)):
                return Decision('chest_selected','click',(735,781),'确认钥匙或扣血开启，绝不选增加侵蚀')
            if self.last_map_keys==0 or (time.monotonic()-self.chest_trial_started>.8 and not self.yellow_button(im,(635,765,831,800))):
                return Decision('chest','click',(735,497),'钥匙不可用，选择扣血开启宝箱')
            return Decision('chest','click',(322,497),'宝箱优先使用钥匙')
        if 'chest_animation_skip' in self.templates and self.has(im,'chest_animation_skip',.85) and self.has(im,'map_floor_label',.75):
            return Decision('chest_skip','click',(1385,68),'立即跳过宝箱动画')
        if self.has(im,'action_header',.8) and (self.has(im,'recovery_purify',.70) or self.has(im,'recovery_rest',.88)):
            left_selected=self.recovery_left_selected(im)
            if left_selected and self.yellow_button(im,(635,765,831,800)):
                return Decision('recovery_selected','click',(735,781),'确认恢复选项')
            # User prefers a fast run; purify prevents erosion accumulating across floors.
            return Decision('recovery','click',(322,497),'选择净化，侵蚀降低30')
        if self.has(im,'action_header',.8) and (self.has(im,'shop_anchor',.85) or self.has(im,'shop_key_label',.85)) and self.has(im,'shop_price_coin',.85):
            self.shop_bag_pending=False
            if self.shop_purchase_rejected:
                return Decision('shop_exit','click',(1410,73),'已取消无法核对的购买，直接离店')
            balance=self.total_number(im,(1268,47,1346,89))
            if balance is None:
                return Decision('shop_exit','click',(1410,73),'商店余额无法读取，立即退出')
            if balance>=300 and not self.shop_bag_rejected:
                for x in (867,1096):
                    if self.within(im,'shop_sold',(x-103,200,x+103,310)):continue
                    if (self.gold_bag_frame(im,(x-72,182,x+72,319)) and
                        self.bag_symbol(im,(x-60,195,x+60,305)) and
                        self.number(im,(x-26,403,x+65,444))==300):
                        self.shop_bag_pending=True
                        return Decision('shop','click',(x,250),'余额足够，购买300币金色装备袋')
            for x in (1325,1096):
                if self.within(im,'shop_sold',(x-103,535,x+103,622)):
                    continue
                price=self.number(im,(x-26,736,x+65,780))
                # Bottom-middle/right slots are the code offers seen in the user's shop.
                if price is not None and 0<price<=balance and price<=self.config.get('max_shop_code_cost',100):
                    return Decision('shop','click',(x,582),'优先购买右下代码')
            return Decision('shop_exit','click',(1410,73),'代码已售罄或余额不足，退出')
        if self.has(im,'action_header',.8):
            if self.event_choice_cache is None:
                # Runtime uses bounded template matching only. Unknown text
                # falls back immediately; full OCR is reserved for diagnostics.
                choices=self.event_options(im,quick_only=True)
                if self.event_rejected_x is not None:
                    choices=[(x,text+' 侵食上昇' if abs(x-self.event_rejected_x)<30 else text) for x,text in choices]
                x=choose_event(choices,['special_battle','code','other','skip'])
                self.event_choice_cache=(x,choices)
            x,_=self.event_choice_cache
            if x is None:
                return Decision('event_skip','click',(1410,73),'事件选项均增加侵蚀，关闭选项页')
            border=cv2.cvtColor(im[410:710,max(0,x-146):max(1,x-133)],cv2.COLOR_BGR2HSV)
            selected=((border[:,:,0]>75)&(border[:,:,0]<105)&(border[:,:,1]>100)&(border[:,:,2]>170)).mean()>.10
            if selected and self.yellow_button(im,(635,765,831,800)):
                return Decision('event_selected','click',(735,781),'确认已核对的安全事件选项')
            return Decision('event_skip','click',(x,493),'事件优先含特殊的选项，再选代码；排除增加侵蚀')
        decline_ready=self.has(im,'code_decline',.88) or self.has(im,'code_decline_wide',.88)
        if self.has(im, 'code_header',.88) and (decline_ready or self.has(im,'reroll',.9)):
            count = self.ratio(im, (675, 141, 813, 181))
            # Capacity changes with research; it is not an account-independent constant.
            valid_count=count and 1<=count[1]<=999 and 0<=count[0]<=count[1]
            if valid_count and count[0] >= count[1]:
                if decline_ready:
                    point=max((self.match(im,n) for n in ('code_decline','code_decline_wide')),key=lambda item:item[0])[1]
                    return Decision('code_decline','click',point,'代码已满，放弃新代码保持推进')
                return Decision('code_full', 'stop', reason='代码替换页尚未采集，保存现场')
            receive_point=self.code_receive_point(im)
            receive_ready=receive_point is not None
            preferred=self.preferred_code(im)
            if preferred is not None:
                border=cv2.cvtColor(im[250:590,preferred-186:preferred-174],cv2.COLOR_BGR2HSV)
                selected=((border[:,:,0]>75)&(border[:,:,0]<105)&(border[:,:,1]>100)&(border[:,:,2]>170)).mean()>.15
                if not selected or not receive_ready:
                    return Decision('code_select','click',(preferred,390),'优先选择不可侵犯・真，降低侵蚀增长',category='safe')
            if receive_ready:
                return Decision('code_selected', 'click', receive_point, '领取已选代码')
            # User's fast fallback: leftmost; no total point data required to run.
            if self.config.get('code_selection','leftmost')=='leftmost':
                category=self.category(im,(287,276,393,387))
                return Decision('code_select','click',(350,390),'选择最左代码',category=category)
            # Color order uses pixel hue, independent of accumulated points.
            cards = [(350, (287, 276, 393, 387)), (735, (670, 276, 776, 387)),
                     (1116, (1053, 276, 1159, 387))]
            candidates = []
            for x, rect in cards:
                color=self.category(im,rect)
                if color is None:
                    continue
                candidates.append((x,color))
            if not candidates:
                return Decision('code_select','click',(350,390),'颜色识别失败，快速选择最左代码')
            if self.session:
                x,color=self.session.choose(candidates)
            else:
                priority=self.config.get('code_color_priority',['impact','risk','safe','rush'])
                x,color=min(candidates,key=lambda item:(priority.index(item[1]),item[0]))
            return Decision('code_select', 'click', (x, 390), f'按配置选择{COLOR_NAMES[color]}代码',category=color)
        next_lit=(cv2.cvtColor(im[760:808,1306:1433],cv2.COLOR_BGR2HSV)[:,:,2]>205).mean()>.4
        if next_lit and self.has(im,'quest_clear',.88):
            return Decision('battle_result', 'click', (1368, 784), '战斗成功后返回地图')
        # Desktop watermarks can cover the speed button. The menu and clock
        # provide two independent battle anchors outside that affected area.
        if self.has(im, 'battle_auto',.85) and (self.has(im, 'battle_speed',.85) or
                (self.has(im,'battle_menu',.9) and self.has(im,'battle_clock',.9))):
            return Decision('battle', reason='等待自动战斗结束')
        if self.has(im, 'map_title',.70) and self.has(im, 'map_floor_label',.88):
            self.shop_bag_rejected=False
            self.shop_purchase_rejected=False
            self.map_expected=True
            floor = self.map_floor_number(im)
            erosion = self.number(im, (1360, 150, 1448, 184))
            if erosion is not None:self.last_map_erosion=erosion
            if erosion is None and self.has(im,'erosion_zero',.9):
                erosion=0
            if floor is None:
                target=self.session.target_floor if self.session else self.config['target_floor']
                if self.last_map_floor is not None and self.last_map_floor<target:
                    fallback=self.map_fallback(im,floor,erosion)
                    if fallback:
                        return fallback
                return Decision('map', reason='等待层数清晰；继续检测可达平台', floor=floor, erosion=erosion)
            self.last_map_floor=floor
            self.last_map_keys=self.number(im,(1064,47,1111,86))
            if floor > (self.session.target_floor if self.session else self.config['target_floor']):
                return Decision('map', 'stop', reason='已超过目标层，禁止继续', floor=floor, erosion=erosion)
            if floor == (self.session.target_floor if self.session else self.config['target_floor']):
                return Decision('map', reason='已到目标层，等待Boss归还选择；不再选新节点',floor=floor,erosion=erosion)
            # Large lit platforms in the next row are directly clickable.
            # Prefer their visible centre to an arrow covered by the sidebar.
            hsv=cv2.cvtColor(im[435:602,100:1250],cv2.COLOR_BGR2HSV)
            mask=np.uint8((hsv[:,:,2]>235)&(hsv[:,:,1]<45))*255
            mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,15),np.uint8))
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            boxes=[cv2.boundingRect(c) for c in contours if cv2.contourArea(c)>7000]
            boxes=[b for b in boxes if b[2]>240 and b[3]>60]
            template, _ = self.templates['route_arrow']
            roi = im[195:550, 35:1460]
            scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            # A second sampled glow variant handles the clipped right island.
            edge, _ = self.templates['route_arrow_edge']
            edge_scores=cv2.matchTemplate(roi,edge,cv2.TM_CCOEFF_NORMED)
            # Both crops use the same centre to within two pixels.
            eh,ew=edge_scores.shape
            sh,sw=scores.shape
            h,w=min(eh,sh),min(ew,sw)
            scores[:h,:w]=np.maximum(scores[:h,:w],edge_scores[:h,:w])
            candidates = []
            for _ in range(6):
                _, score, _, pos = cv2.minMaxLoc(scores)
                if score < .87:
                    break
                x = 35+pos[0]+template.shape[1]//2
                y = 195+pos[1]+template.shape[0]//2
                # Only the bright reachable platforms beneath a white arrow are eligible.
                target_y = y+177
                if target_y < 760:
                    rank=self.route_rank(im,x,target_y)
                    # Right-edge islands extend under the fixed sidebar. Click
                    # their visible left half rather than the sidebar icon.
                    click_x=min(x,1230)
                    candidates.append((rank,abs(x-735), click_x, target_y))
                px,py=pos
                scores[max(0,py-50):py+50,max(0,px-80):px+80] = -1
            if not candidates:
                if boxes:
                    x,y,w,h=min(boxes,key=lambda b:(self.route_rank(im,100+b[0]+b[2]//2,435+b[1]+b[3]//2),abs(100+b[0]+b[2]//2-735)))
                    return Decision('map','click',(100+x+w//2,435+y+h//2),'直接选择人物下方高亮平台',floor,erosion)
                fallback=self.map_fallback(im,floor,erosion)
                if fallback:
                    return fallback
                if floor%10==9:
                    # Large boss platforms can extend offscreen and their arrow may be outside.
                    hsv=cv2.cvtColor(im[435:602,:1250],cv2.COLOR_BGR2HSV)
                    mask=np.uint8((hsv[:,:,2]>235)&(hsv[:,:,1]<45))*255
                    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,15),np.uint8))
                    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
                    boxes=[cv2.boundingRect(c) for c in contours if cv2.contourArea(c)>7000]
                    boxes=[b for b in boxes if b[2]>240 and b[3]>60]
                    if len(boxes)==1:
                        x,y,w,h=boxes[0]
                        return Decision('map','click',(max(100,x+w//2),435+y+h//2),'点击唯一高亮Boss平台',floor,erosion)
                return Decision('map', reason='等待可达节点箭头或地图动画', floor=floor, erosion=erosion)
            _, _, x, y = min(candidates)
            self.map_wait_started=None
            return Decision('map', 'click', (x,y), '按配置路线优先级选择可达节点', floor, erosion)
        if self.has(im,'resume') or (self.has(im,'resume_yellow') and self.has(im,'map_title')):
            return Decision('resume','click',(758,604),'恢复原有探索，起点保持30F')
        if (self.has(im, 'formation_title',.85) or self.has(im,'formation_title_jp',.85)) and self.yellow_button(im,(1250,779,1415,810)):
            return Decision('formation', 'click', (1335,794), '使用当前编队出击')
        if self.map_expected and self.has(im,'map_floor_label',.75):
            floor=self.number(im,(96,117,129,150))
            target=self.session.target_floor if self.session else self.config['target_floor']
            if (floor if floor is not None else self.last_map_floor) is not None and (floor if floor is not None else self.last_map_floor)<target:
                fallback=self.map_fallback(im,floor)
                if fallback:
                    return fallback
        loading=re.sub(r'[^A-Z]','',self.line(im,(1170,790,1460,846)).upper())
        if 'NOWLOA' in loading or 'LOADING' in loading:
            return Decision('loading',reason='等待客户端加载；不重复提交原动作')
        return Decision('unknown', reason='当前画面未识别，持续检测并保存等待现场')

class GameWindow:
    def __init__(self, title):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        self.user32=ctypes.windll.user32
        self.user32.GetForegroundWindow.restype=ctypes.c_void_p
        self.user32.GetWindowRect.argtypes=[ctypes.c_void_p, ctypes.c_void_p]
        self.dwm=ctypes.windll.dwmapi
        self.dwm.DwmGetWindowAttribute.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint]
        matches=[]
        callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
        def visit(hwnd,_):
            text=ctypes.create_unicode_buffer(512)
            self.user32.GetWindowTextW(ctypes.c_void_p(hwnd),text,512)
            # Substring match: BepInEx prepends its version to the title.
            if title in text.value and self.user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
                matches.append((hwnd,text.value))
            return True
        self.user32.EnumWindows(callback(visit),0)
        # Prefer the exact title: BepInEx plugins may create extra titled windows
        # in the same process (e.g. a mod GUI), while the main window stays exact.
        exact=[hwnd for hwnd,text in matches if text==title]
        if len(exact)==1:
            self.hwnd=exact[0]
        elif len(matches)==1:
            self.hwnd=matches[0][0]
        else:
            raise RuntimeError(f'必须有唯一游戏窗口，找到{len(matches)}个候选：{[t for _,t in matches]}')
        self.initial_size=None

    def bounds(self):
        rect=(ctypes.c_long*4)()
        # GetWindowRect includes Windows' invisible resize border. Templates use
        # the visible frame, so capture and clicks must share DWM frame bounds.
        if self.dwm.DwmGetWindowAttribute(self.hwnd,9,ctypes.byref(rect),ctypes.sizeof(rect))!=0:
            raise RuntimeError('无法读取可见游戏窗口边界')
        return tuple(rect)

    def capture(self):
        if self.user32.GetForegroundWindow()!=self.hwnd:
            raise RuntimeError('游戏不在前台。请把游戏置于前台后重新启动。')
        if self.user32.IsIconic(ctypes.c_void_p(self.hwnd)):
            raise RuntimeError('游戏已最小化')
        self.rect=self.bounds()
        w,h=self.rect[2]-self.rect[0],self.rect[3]-self.rect[1]
        if self.initial_size is None:
            self.initial_size=(w,h)
        if self.initial_size!=(w,h):
            raise RuntimeError('窗口尺寸变化，请重新校准')
        if not supported_window_ratio(w,h):
            raise RuntimeError(f'窗口比例暂不支持：{w}×{h}；请使用游戏内标准横屏窗口尺寸')
        pil=ImageGrab.grab(bbox=self.rect,all_screens=True)
        return cv2.cvtColor(np.array(pil),cv2.COLOR_RGB2BGR)

    def click(self,point):
        # Recheck foreground immediately before sending input. User-run CLI only.
        if stop_requested():
            raise RuntimeError('F12人工停止')
        if self.user32.GetForegroundWindow()!=self.hwnd:
            raise RuntimeError('点击前焦点发生变化')
        if self.bounds()!=self.rect:
            raise RuntimeError('识别后窗口位置发生变化，停止本次点击')
        import pyautogui
        pyautogui.FAILSAFE=True
        pyautogui.PAUSE=.02
        x,y=point
        l,t,r,b=self.rect
        if not (0<=x<BASE[0] and 0<=y<BASE[1]):
            raise RuntimeError('点击超出游戏窗口')
        try:
            pyautogui.click(l+x*(r-l)/BASE[0],t+y*(b-t)/BASE[1])
        except pyautogui.FailSafeException as exc:
            raise RuntimeError('鼠标位于屏幕角落，触发紧急停止；移开鼠标后手动重新启动') from exc

    def scroll(self,point,delta):
        if stop_requested():
            raise RuntimeError('F12人工停止')
        if self.user32.GetForegroundWindow()!=self.hwnd or self.bounds()!=self.rect:
            raise RuntimeError('滚动前窗口或焦点发生变化')
        import pyautogui
        pyautogui.FAILSAFE=True
        l,t,r,b=self.rect
        try:
            pyautogui.moveTo(l+point[0]*(r-l)/BASE[0],t+point[1]*(b-t)/BASE[1])
            pyautogui.scroll(delta)
        except pyautogui.FailSafeException as exc:
            raise RuntimeError('鼠标角落紧急停止') from exc

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, help='离线分析一张截图，不操作桌面')
    parser.add_argument('--collect', action='store_true', help='只保存一张前台游戏截图')
    parser.add_argument('--run', action='store_true', help='明确启用鼠标操作')
    parser.add_argument('--config', type=Path, default=default_config_path())
    parser.add_argument('--delay', type=float, default=5, help='启动后切换到游戏的等待秒数')
    parser.add_argument('--set-points', nargs=4, type=int, metavar=('SAFE','IMPACT','RUSH','RISK'), help='录入已核对的四类累计点数，不操作桌面')
    args=parser.parse_args(argv)
    config=load_config(args.config)
    if config.get('checkpoint',0)%10 or config.get('floors_per_round',50)%10:
        raise ValueError('检查点与推进层数须为10的倍数')
    config['target_floor']=config['checkpoint']+config.get('floors_per_round',50)
    if config['checkpoint'] not in range(10,101,10) or config.get('floors_per_round',50)<=0 or config['target_floor']>150:
        raise ValueError('检查点须为10～100层，推进层数须大于0，目标层不能超过150')
    account_root=data_root()/'accounts'
    if not FROZEN and data_root()==ROOT:
        account_root=ROOT/'runs'/'accounts'
    ledger=account_root/config.get('account_id','local')/'ledger.json'
    if not ledger.resolve().is_relative_to(account_root.resolve()):
        raise ValueError('账号名称不能包含目录跳转')
    session=FarmSession(config,ledger)
    if args.set_points is not None:
        session.snapshot(dict(zip(CATEGORIES,args.set_points)))
        print('已保存核对后的累计点数：'+str(ledger))
        return
    vision=Vision(config,session)
    if args.image:
        print(json.dumps(asdict(vision.plan(read_image(args.image))),ensure_ascii=False,indent=2))
        return
    if args.run:
        # Load OCR before activating the run so the first visible button does
        # not pay the model's roughly 0.7-second cold start.
        # Warm the recognizer without depending on a private gameplay screenshot.
        vision.number(np.zeros((48,128,3),dtype=np.uint8),(0,0,128,48))
    window=GameWindow(config['window_title'])
    folder=data_root()/'runs'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'run-config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{args.delay}秒后开始；切换到游戏。F7暂停/继续，F12停止；鼠标移到主屏角落停止。',flush=True)
    countdown(args.delay)
    screenshots=ScreenshotWriter(max_files=config.get('max_screenshots_per_run',2000))
    start=time.monotonic()
    keys=0
    retries=0
    next_network_retry=0.
    state_since=start
    last_state=None
    stable=0
    previous_floor=None
    pending=None
    selected_code=None
    action_serial=0
    last_overlay_close=float('-inf')
    round_start=session.data['rounds_completed']
    paused=False
    pause_started=None
    pause_key_down=False
    round_ready=False
    cleanup_return=False
    last_print=0
    last_recovery=0.
    checkpoint_scrolls=0
    focus_since=None
    try:
        while time.monotonic()-start < config['max_minutes']*60:
            if stop_requested():
                raise RuntimeError('F12人工停止')
            pause_key_now=bool(ctypes.windll.user32.GetAsyncKeyState(0x76)&0x8000)
            if pause_key_now and not pause_key_down:
                paused=not paused
                if paused:
                    pause_started=time.monotonic()
                else:
                    elapsed=time.monotonic()-pause_started
                    state_since+=elapsed
                    if pending:
                        pending['at']+=elapsed
                print('暂停中' if paused else '继续',flush=True)
            pause_key_down=pause_key_now
            if paused:
                time.sleep(.1)
                continue
            if window.user32.GetForegroundWindow()!=window.hwnd:
                if focus_since is None:
                    focus_since=time.monotonic()
                    print('游戏失去焦点，暂停点击；回到游戏后继续。',flush=True)
                time.sleep(config['poll_seconds'])
                continue
            if focus_since is not None:
                elapsed=time.monotonic()-focus_since
                state_since+=elapsed
                if pending:
                    pending['at']+=elapsed
                focus_since=None
                stable=0
                print('游戏恢复前台，继续。',flush=True)
            capture_started=time.perf_counter()
            raw=window.capture()
            if args.collect:
                Image.fromarray(cv2.cvtColor(raw,cv2.COLOR_BGR2RGB)).save(folder/'capture.png')
                print(str(folder/'capture.png'))
                break
            recognition_start=time.perf_counter()
            decision=runtime_decision(vision.plan(raw))
            if stop_requested():
                raise RuntimeError('F12人工停止')
            recognition_ms=round((time.perf_counter()-recognition_start)*1000,1)
            now=time.monotonic()
            if args.run and stall_recovery_due(now,state_since,pending,last_recovery,config):
                last_recovery=now
                screenshots.save(folder/f'recovery-{time.time_ns()}-{decision.state}.jpg',raw)
                recovered=vision.recover_stalled(raw,decision,pending)
                if recovered is None:
                    with (folder/'recovery.jsonl').open('a',encoding='utf-8') as f:
                        f.write(json.dumps({'time':time.time(),'event':'recovery_wait',
                            'old_state':pending['state'] if pending else None,
                            'current_state':decision.state,'reason':decision.reason},ensure_ascii=False)+'\n')
                if recovered:
                    with (folder/'recovery.jsonl').open('a',encoding='utf-8') as f:
                        f.write(json.dumps({'time':time.time(),'old_state':pending['state'] if pending else None,
                            'current_state':decision.state,'recovered_state':recovered.state,
                            'point':recovered.point},ensure_ascii=False)+'\n')
                    print('等待超时，按当前画面继续：'+recovered.state,flush=True)
                    decision=recovered
                    pending=None
                    # This frame already identifies the actionable screen.
                    last_state=decision_signature(decision)
                    stable=1
                    state_since=now
            if decision.floor is not None:
                if previous_floor is not None and not (previous_floor <= decision.floor <= previous_floor+1):
                    decision=Decision('map',reason='层数读数不连续，重新识别',erosion=decision.erosion)
                else:
                    previous_floor=decision.floor
            signature=decision_signature(decision)
            changed=signature!=last_state
            if signature==last_state:
                stable+=1
            else:
                stable=1
                last_state=signature
                state_since=time.monotonic()
            required_frames=2 if decision.state in {'boss_return_confirm','party_confirm'} else (1 if decision.state=='erosion_cancel' or decision.state in config.get('fast_states',[]) else 2)
            if (changed and decision.state not in {'unknown','loading'}) or time.monotonic()-last_print>=5:
                print(json.dumps({**asdict(decision),'recognition_ms':recognition_ms},ensure_ascii=False),flush=True)
                last_print=time.monotonic()
            with (folder/'decisions.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'time':time.time(),**asdict(decision),'recognition_ms':recognition_ms},ensure_ascii=False)+'\n')
            if not args.run:
                Image.fromarray(cv2.cvtColor(raw,cv2.COLOR_BGR2RGB)).save(folder/'observe.png')
                break
            if decision.action=='stop':
                raise RuntimeError(decision.reason)
            if decision.action=='scroll' and stable>=required_frames:
                if checkpoint_scrolls>=8:
                    if time.monotonic()-state_since>=config.get('stall_recovery_seconds',5):
                        checkpoint_scrolls=0
                    else:
                        time.sleep(config['poll_seconds'])
                        continue
                window.scroll(decision.point,decision.scroll_delta)
                checkpoint_scrolls+=1
                pending=None
                stable=0
                with (folder/'actions.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({'time':time.time(),'state':decision.state,'action':'scroll',
                        'point':decision.point,'scroll_delta':decision.scroll_delta},ensure_ascii=False)+'\n')
                time.sleep(.2)
                continue
            if decision.state=='network_retry' and stable>=required_frames:
                if now<next_network_retry:
                    time.sleep(config['poll_seconds'])
                    continue
                retries+=1
                window.click(decision.point)
                stable=0
                next_network_retry=time.monotonic()+network_retry_delay(retries,config)
                with (folder/'recovery.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({'time':time.time(),'event':'network_retry','attempt':retries,
                        'next_retry_seconds':network_retry_delay(retries,config)},ensure_ascii=False)+'\n')
                time.sleep(config['poll_seconds'])
                continue
            # Apply page wait limits even while an old action remains pending.
            # Previously the pending branch's continue bypassed this check.
            limit=page_wait_limit(decision.state,config)
            if decision.action=='wait' and time.monotonic()-state_since>limit:
                Image.fromarray(cv2.cvtColor(raw,cv2.COLOR_BGR2RGB)).save(folder/'waiting.png')
                with (folder/'recovery.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({'time':time.time(),'event':'wait_timeout',
                        'state':decision.state,'reason':decision.reason},ensure_ascii=False)+'\n')
                print('等待超时，保存现场并继续识别；画面恢复后自动继续。',flush=True)
                state_since=time.monotonic()
            if pending:
                # Expected postconditions, never replay a resource action on a timeout.
                # These verified overlays can arrive after a transient map frame
                # or an event result. Handle them promptly instead of holding
                # the old action's narrow expected-state list for five minutes.
                allowed=pending_allowed_states(pending['state'],pending['expected'])
                allowed.add('menu_close')
                if decision.state in allowed and stable>=required_frames and not (decision.state=='map' and decision.action=='wait') and not (pending['state']=='transport' and decision.state=='transport' and decision.point==pending['point']):
                    if decision.state=='code_received' and selected_code:
                        session.received(selected_code['id'],selected_code['category'])
                        selected_code=None
                    pending=None
                    retries=0
                elif time.monotonic()-pending['at']>config.get('request_timeout_seconds',300):
                    # Preserve the origin and retry count: clearing it could
                    # submit a key purchase twice. Fresh frames still reconcile
                    # any recognized successor through the allowed-state path.
                    pending['at']=time.monotonic()
                    with (folder/'recovery.jsonl').open('a',encoding='utf-8') as f:
                        f.write(json.dumps({'time':time.time(),'event':'request_timeout',
                            'state':pending['state'],'current_state':decision.state},ensure_ascii=False)+'\n')
                    print('请求等待超时，继续监测当前画面。',flush=True)
                elif (decision.state==pending['state'] and decision.action=='click' and decision.point and pending['point']
                      and (decision.state=='chest' or (decision.state=='map' and decision.floor==pending.get('floor')) or max(abs(a-b) for a,b in zip(decision.point,pending['point']))<=20)
                      and (decision.state in {'erosion_cancel','erosion_notice','lost_signal_decline','exploration_failed','menu_close'} or decision.state in config.get('retry_click_states',[]))
                      and (pending['attempts']<(config.get('map_max_click_attempts',30) if decision.state in {'map','entrance','checkpoint_select'} else config.get('max_click_attempts',3))
                           or decision.state in {'event_skip','event_selected','recovery','recovery_selected','shop_exit'})
                      and time.monotonic()-pending['last_click']>=(.8 if decision.state=='boss_return' else (1.0 if pending['attempts']>=config.get('max_click_attempts',3)
                           and decision.state in {'event_skip','event_selected','recovery','recovery_selected','shop_exit'}
                           else config.get('retry_click_seconds',.4)))):
                    if not overlay_close_ready(decision,time.monotonic(),last_overlay_close):
                        time.sleep(config['poll_seconds'])
                        continue
                    if decision.state=='shop_exit' and decision.point==(1410,73) and not vision.shop_close_visible(window.capture()):
                        time.sleep(config['poll_seconds'])
                        continue
                    window.click(decision.point)
                    if decision.state=='menu_close' or (decision.state=='shop_exit' and decision.point==(1410,73)):
                        last_overlay_close=time.monotonic()
                    pending['point']=decision.point
                    pending['last_click']=time.monotonic()
                    pending['attempts']+=1
                    print('按钮仍可用，补点：'+decision.state,flush=True)
                    time.sleep(config['poll_seconds'])
                    continue
                else:
                    time.sleep(config['poll_seconds'])
                    continue
            if decision.action=='click' and stable>=required_frames:
                if not overlay_close_ready(decision,time.monotonic(),last_overlay_close):
                    time.sleep(config['poll_seconds'])
                    continue
                if decision.state=='shop_exit' and decision.point==(1410,73) and not vision.shop_close_visible(window.capture()):
                    time.sleep(config['poll_seconds'])
                    continue
                if decision.state=='exploration_failed':
                    session.data.pop('pending_return_floor',None)
                    session.save()
                    cleanup_return=True
                if decision.state=='boss_return' and decision.floor is not None:
                    session.data['pending_return_floor']=decision.floor
                    session.save()
                if decision.state=='return_score' and decision.floor is not None:
                    session.data['pending_return_floor']=decision.floor
                    session.save()
                if decision.state=='return_points':
                    completed=session.process_return(f'{folder.name}:round:{session.round_number}',decision.points)
                    round_ready=completed or round_ready
                    cleanup_return=True
                    if not completed and not round_ready:
                        print('已清理旧结算；旧结果不计入本次轮数，回到入口后按配置开刷。',flush=True)
                if decision.state=='return_result':
                    event_id=f'{folder.name}:round:{session.round_number}'
                    try:
                        session.settle(event_id,decision.floor,decision.points)
                        round_ready=True
                    except ValueError as exc:
                        # Optional calibrated accounting cannot block closing
                        # a result page. Unverified results don't count as rounds.
                        cleanup_return=True
                        print('结算记录未通过核对，继续关闭页面：'+str(exc),flush=True)
                if decision.state=='entrance' and (round_ready or cleanup_return):
                    if session.data['rounds_completed']-round_start>=config.get('max_rounds',1):
                        print('已完成设定轮数；结算已记录，返回入口后正常结束。',flush=True)
                        break
                    previous_floor=None
                    vision.last_map_floor=None
                    round_ready=False
                    cleanup_return=False
                if decision.state=='checkpoint_selected' and not config.get('checkpoint_selection_verified',False):
                    print('检查点未校准，等待校准或手动选择，不退出。',flush=True)
                    time.sleep(.5)
                    continue
                if decision.state=='checkpoint_selected':checkpoint_scrolls=0
                number=action_serial
                expected={
                    'entrance':{'checkpoint_select','checkpoint_selected','map','boss_continue','transport'},
                    'checkpoint_select':{'checkpoint_selected'},'checkpoint_selected':{'formation'},
                    'return_result':{'entrance'},
                    'return_points':{'entrance','return_items','return_result'},
                    'formation':{'skip_confirm'}, 'skip_confirm':{'key_confirm'},
                    'key_confirm':{'party_confirm','map','transport','boss_continue'}, 'party_confirm':{'map'},
                    'map':{'battle','code_select','battle_result','recovery','event_skip','event_result','shop','shop_exit','item_reward','boss_continue','transport'},
                    'code_select':{'code_selected'}, 'code_selected':{'code_received'},
                    'code_decline':{'battle_result','map','shop','shop_exit','event_result'},
                    'code_received':{'battle_result','shop','shop_exit','map','event_result'},
                    'battle_result':{'map','transport','boss_continue','boss_return','code_select','code_received','item_reward'},
                    'shop':{'shop_confirm'},'shop_confirm':{'code_received','item_reward','shop','shop_exit'},'shop_exit':{'map','shop'},
                    'menu_close':{'map','shop','shop_exit'},
                    'erosion_notice':{'map','battle','event_skip','recovery','shop','boss_continue'},
                    'lost_signal_decline':{'return_score','return_score_skip','return_points','entrance'},
                    'exploration_failed':{'return_score','return_score_skip','return_points','entrance'},
                    'recovery':{'recovery_selected'},'recovery_selected':{'map'},
                    'chest':{'chest_selected'},'chest_selected':{'chest_skip','item_reward','map'},
                    'chest_skip':{'item_reward','event_result','map'},
                    'event_skip':{'event_selected'},'event_selected':{'map','battle','battle_result','event_result','item_reward','code_select'},
                    'event_result':{'map','battle','battle_result','code_select','item_reward','boss_continue'},'item_reward':{'map','event_result'},
                    'transport':{'transport','transport_confirm','map','boss_continue'},'transport_confirm':{'map','boss_continue'},'boss_continue':{'skip_confirm','key_confirm','map','transport'},
                    'boss_return':{'boss_return_confirm','return_score','return_result'},'boss_return_confirm':{'return_score','return_result'},
                    'return_score':{'return_points','return_items','return_result','entrance'},
                    'return_score_skip':{'return_score','return_points','return_items','return_result','entrance'},
                    'resume':{'map','boss_continue','transport'},
                }[decision.state]
                vision.map_expected='map' in expected or decision.state=='map'
                vision.map_wait_started=None
                action_serial+=1
                if decision.state=='code_select' and decision.category:
                    selected_code={'id':f'{folder.name}:{action_serial}', 'category':decision.category}
                window.click(decision.point)
                if decision.state=='menu_close' or (decision.state=='shop_exit' and decision.point==(1410,73)):
                    last_overlay_close=time.monotonic()
                with (folder/'actions.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps({'time':time.time(),'state':decision.state,'point':decision.point,
                        'floor':decision.floor,'capture_to_click_ms':round((time.perf_counter()-capture_started)*1000,1)},ensure_ascii=False)+'\n')
                # Click first; the background writer encodes the snapshot.
                screenshots.save(folder/f'step-{number:04d}-{decision.state}.jpg',raw)
                retries=0
                pending={'at':time.monotonic(),'last_click':time.monotonic(),'expected':expected,
                         'state':decision.state,'point':decision.point,'floor':decision.floor,'attempts':1}
                stable=0
            time.sleep(config['poll_seconds'])
        else:
            raise RuntimeError('达到运行时长上限')
    except (RuntimeError, ValueError, KeyboardInterrupt) as exc:
        if 'raw' in locals():
            Image.fromarray(cv2.cvtColor(raw,cv2.COLOR_BGR2RGB)).save(folder/'stopped.png')
        print(f'已停止：{exc}；记录：{folder}',flush=True)
        raise SystemExit(130 if isinstance(exc,KeyboardInterrupt) else 1)
    finally:
        screenshots.close()

if __name__=='__main__':
    main()
