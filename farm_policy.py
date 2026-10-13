"""Account-local point ledger and verified-round lifecycle, with no UI dependencies."""
from __future__ import annotations
import json
from pathlib import Path

CATEGORIES = ('safe', 'impact', 'rush', 'risk')
COLOR_NAMES={'impact':'黄','risk':'紫','safe':'蓝','rush':'红'}
ROUTE_NAMES={'elite':'强敌','battle':'普通战斗','event':'事件','recovery':'恢复','shop':'商店','chest':'宝箱'}

def normalize_route_priority(priority=None):
    result=[]
    for kind in priority or ROUTE_NAMES:
        for item in (('event','recovery','shop') if kind=='other' else (kind,)):
            if item in ROUTE_NAMES and item not in result:result.append(item)
    return result+[kind for kind in ROUTE_NAMES if kind not in result]

def increases_erosion(text):
    text=text.replace(' ','')
    return any(w in text for w in ('侵蚀','侵蝕','侵食','浸食','浸蚀','浸蝕')) and any(w in text for w in ('增加','上升','増加','上昇','+','＋'))

def event_kind(text):
    if any(w in text for w in ('特殊','强敌','強敵')):
        return 'special_battle'
    if any(w in text for w in ('代码','代碼','コード')):
        return 'code'
    if any(w in text for w in ('离开','離開','離れる','立ち去','何もしない','跳过','見送','無視')):
        return 'skip'
    return 'other'

def choose_event(options, priority):
    """Options (x, text); exclude explicit erosion increases before ranking."""
    eligible=[(x,text) for x,text in options if not increases_erosion(text)]
    if not eligible:
        return None
    return min(eligible,key=lambda item:(priority.index(event_kind(item[1])) if event_kind(item[1]) in priority else len(priority),item[0]))[0]

class FarmSession:
    def __init__(self, config, ledger_path):
        self.config = config
        self.path = Path(ledger_path)
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'account': config.get('account_id', 'local'), 'points': None,
            'settlements': [], 'received': [], 'rounds_completed': 0,
        }
        if self.data['account'] != config.get('account_id', 'local'):
            raise ValueError('统计文件属于其他账号，请使用独立账号配置')
        self.round_number = int(self.data['rounds_completed']) + 1
        self.target_floor = int(config['checkpoint']) + int(config.get('floors_per_round', 50))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.path)

    def snapshot(self, points):
        if set(points) != set(CATEGORIES) or any(type(v) is not int or v < 0 for v in points.values()):
            raise ValueError('点数必须包含 safe/impact/rush/risk 四个非负整数')
        self.data['points'] = dict(points)
        self.save()

    def process_return(self,event_id,points=None):
        """Drain old result pages without counting them toward this run's goal."""
        returned=self.data.get('pending_return_floor')
        completed=False
        if returned==self.target_floor:
            completed=self.settle(event_id,returned,points)
        elif points is not None:
            self.snapshot(points)
        self.data.pop('pending_return_floor',None)
        self.save()
        return completed

    def choose(self, candidates):
        """Candidates: (x, category), selected by color order or leftmost."""
        if not candidates:
            raise ValueError('没有候选代码')
        if self.config.get('code_selection')=='color_priority':
            priority=self.config.get('code_color_priority',['impact','risk','safe','rush'])
            return min(candidates,key=lambda item:(priority.index(item[1]) if item[1] in priority else len(priority),item[0]))
        return min(candidates, key=lambda item: item[0])

    def received(self, event_id, category):
        if category not in CATEGORIES or any(e['id'] == event_id for e in self.data['received']):
            return False
        self.data['received'].append({'id': event_id, 'category': category, 'round': self.round_number})
        self.save()
        return True

    def settle(self, event_id, completed_floor, points):
        if any(e['id'] == event_id for e in self.data['settlements']):
            return False
        if completed_floor != self.target_floor:
            raise ValueError('结算层数与目标不一致，禁止开始下一轮')
        before = self.data['points']
        # Research consumes the displayed balances between runs. A decrease
        # does not invalidate a verified completed floor or block UI cleanup.
        balance_decreased=before is not None and points is not None and any(points[k]<before[k] for k in CATEGORIES)
        if points is not None:self.snapshot(points)
        self.data['settlements'].append({'id': event_id, 'round': self.round_number,
            'floor': completed_floor, 'points': dict(points) if points is not None else None,
            'delta': None if before is None or points is None or balance_decreased else {k: points[k]-before[k] for k in CATEGORIES},
            'balance_decreased':balance_decreased})
        self.data['rounds_completed'] += 1
        self.round_number += 1
        self.save()
        return True
