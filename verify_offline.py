"""Replay recorded screens and exercise round/account rules without desktop input."""
import json
import tempfile
from pathlib import Path
from abyss_bot import ROOT, Vision, Decision, read_image, normalized, pending_allowed_states, stall_recovery_due, network_retry_delay, page_wait_limit, runtime_decision
import numpy as np
from farm_policy import FarmSession, choose_event, increases_erosion, normalize_route_priority
from launcher import build_config
from abyss_bot import supported_window_ratio, overlay_close_ready, decision_signature

def main(sample_dir=None, report_path=None):
    SAMPLES=Path(sample_dir) if sample_dir else ROOT/'samples'
    assert decision_signature(Decision('boss_return_confirm','click',(847,583)))==decision_signature(Decision('boss_return_confirm','click',(848,584)))
    assert decision_signature(Decision('map','click',(538,525)))!=decision_signature(Decision('map','click',(931,525)))
    closing=Decision('shop_exit','click',(1410,73))
    assert not overlay_close_ready(closing,10.1,10)
    assert overlay_close_ready(closing,10.2,10)
    assert not overlay_close_ready(closing,11,10,close_visible=False)
    assert overlay_close_ready(Decision('map','click',(538,527)),10.01,10)
    assert overlay_close_ready(Decision('shop_exit','click',(615,694)),10.01,10)
    for width,height in ((1280,720),(1600,900),(1920,1080),(2560,1440),(1536,864),(1838,1081),(1282,759),(1922,1119)):
        assert supported_window_ratio(width,height)
    assert not supported_window_ratio(1080,1920)
    assert not supported_window_ratio(2560,1080)
    config=json.loads((ROOT/'config.default.json').read_text(encoding='utf-8'))
    # Replay fixtures have fixed goals; user launch settings may change freely.
    config.update(checkpoint=30,floors_per_round=50,target_floor=80,stall_recovery_seconds=5,
                  route_priority=['elite','battle','event','recovery','shop','chest'])
    config['code_selection']='leftmost'  # recorded fixtures use the original left-card strategy
    cases={
        'map_menu_accidental':('menu_close','click',None),
        'map_after_shop36':('map','click',36),
        'network_timeout':('network_retry','click',None),
        'recovery_resolution_test':('recovery','click',None),
        'recovery_selected_resolution':('recovery_selected','click',None),
        'entrance_resolution_current':('resume','click',None),
        'entrance_1920_after_return':('entrance','click',None),
        'party_confirm_1920':('party_confirm','click',None),
        'return_confirm_1920_stable':('boss_return_confirm','click',None),
        'network_timeout_1920_live':('network_retry','click',None),
        'shop_confirm_1920_unreadable':('shop_exit','click',None),
        'erosion_notice80_1920':('erosion_notice','click',None),
        'lost_signal_confirm_1920':('lost_signal_decline','click',None),
        'exploration_failed_1920':('exploration_failed','click',None),
        'map32_resolution_current':('map','click',32),
        'formation':('formation','click',None),
        'formation_watermark_jp':('formation','click',None),
        'network_timeout_reward':('network_retry','click',None),
        'code_select_second':('code_select','click',None),
        'code_reward_scaled_20261013':('code_select','click',None),
        'code_reward_scaled_runtime':('code_select','click',None),
        'code_reward_1920_capacity37':('code_select','click',None),
        'elite_code_select':('code_select','click',None),
        'boss_code_reward':('code_select','click',None),
        'code_selected':('code_selected','click',None),
        'code_received':('code_received','click',None),
        'elite_battle':('battle','wait',None),
        'battle_watermark':('battle','wait',None),
        'code_reward_variant40':('code_select','click',None),
        'elite_result':('battle_result','click',None),
        'elite_result37':('loading','wait',None),
        'boss_result':('battle_result','click',None),
        'map_start30':('map','click',30),
        'map32_elite':('map','click',32),
        'map33_event':('map','click',33),
        'map39_boss_edge':('map','click',39),
        'map59_side_boss':('map','click',59),
        'event_river':('event_skip','click',None),
        'event_three_special_jp':('event_skip','click',None),
        'event_four_cold':('event_skip','click',None),
        'event_erosion_warning':('erosion_cancel','click',None),
        'event_nest_wrong_selected':('event_skip','click',None),
        'event_nest_left_selected':('event_selected','click',None),
        'event_river_result':('event_result','click',None),
        'event_result37_full':('event_result','click',None),
        'runtime_map_false_event':('map','wait',42),
        'shop39':('shop','click',None),
        'shop45_middle':('shop','click',None),
        'shop45_runtime':('shop','click',None),
        'shop35_today':('shop','click',None),
        'shop_confirm35_today':('shop_confirm','click',None),
        'shop_sold_out':('shop_exit','click',None),
        'recovery_selected':('recovery_selected','click',None),
        'transport40':('transport','click',None),
        'transport_today':('transport','click',None),
        'transport_selected_today':('transport','click',None),
        'transport_full_today':('transport','click',None),
        'boss_continue40':('boss_continue','click',40),
        'boss_return80_runtime':('boss_return','click',80),
        'runtime_code_1':('code_select','click',None),
        'runtime_recovery':('recovery','click',None),
        'recovery75_runtime':('recovery','click',None),
        'runtime_map36':('map','click',36),
        'runtime_result_hover':('battle_result','click',None),
        'network_hover':('network_retry','click',None),
        'event_selected_today':('event_selected','click',None),
        'map32_right_edge':('map','click',32),
        'map31_test20':('map','click',31),
        'key_today':('key_confirm','click',None),
        'key_second_round':('key_confirm','click',None),
        'skip_second_round':('skip_confirm','click',None),
        'checkpoint_today':('checkpoint_select','click',None),
        'checkpoint_selected_today':('checkpoint_selected','click',None),
        'return_confirm40':('boss_return_confirm','click',None),
        'return_score40':('return_score_skip','click',None),
        'return_score_1920_ready':('return_score_skip','click',None),
        'return_points40':('return_points','click',None),
        'return_points_large_totals':('return_points','click',None),
        'return_points80_runtime':('return_points','click',None),
        'return_points_spent':('return_points','click',None),
        'map76_chest_ahead':('map','click',76),
        'map34_recovery_shop':('map','click',34),
        'chest_options79':('chest','click',None),
        'chest_selected79':('chest_selected','click',None),
        'chest_animation79':('chest_skip','click',None),
    }
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        session=FarmSession(config,Path(tmp)/'ledger.json')
        vision=Vision(config,session)
        route_guard=Vision(config,session)
        route_guard.within=lambda im,name,rect,threshold=.88: name=='node_recovery_text'
        route_guard.last_map_erosion=60
        assert route_guard.route_rank(np.zeros((864,1470,3),dtype=np.uint8),735,524)==-1
        route_guard.last_map_erosion=30
        assert route_guard.route_rank(np.zeros((864,1470,3),dtype=np.uint8),735,524)==config['route_priority'].index('recovery')
        assert vision.shop_close_visible(read_image(SAMPLES/'shop35_today.png'))
        assert not vision.shop_close_visible(read_image(SAMPLES/'map_after_shop36.png'))
        assert not vision.shop_close_visible(read_image(SAMPLES/'map_menu_accidental.png'))
        entrance_no_text=normalized(read_image(SAMPLES/'entrance_1920_after_return.png'))
        entrance_no_text[110:210,540:800]=0
        entrance_no_text[110:170,1220:1370]=0
        fallback=vision.plan(entrance_no_text)
        assert fallback.state=='entrance' and fallback.action=='click' and '图案兜底' in fallback.reason
        for name in ('map_after_shop36','map_menu_accidental','network_timeout','shop35_today'):
            assert not vision.entrance_patterns_visible(normalized(read_image(SAMPLES/f'{name}.png')))
        no_digits=Vision(config,session)
        def reject_digit_read(*args,**kwargs):
            raise AssertionError('结算下一页不应读取数字')
        no_digits.number=reject_digit_read
        ready=no_digits.plan(read_image(SAMPLES/'return_score_1920_ready.png'))
        assert ready.state=='return_score_skip' and ready.action=='click'
        assert abs(ready.point[0]-1358)<20 and abs(ready.point[1]-64)<20
        without_skip=normalized(read_image(SAMPLES/'return_score_1920_ready.png'))
        without_skip[30:115,1300:1460]=0
        ready=no_digits.plan(without_skip)
        assert ready.state=='return_score' and ready.action=='click'
        assert abs(ready.point[0]-735)<20 and abs(ready.point[1]-641)<20
        for name, expected in cases.items():
            vision.event_choice_cache=None
            d=vision.plan(read_image(SAMPLES/f'{name}.png'))
            actual=(d.state,d.action,d.floor)
            results.append({'sample':name,'expected':expected,'actual':actual,'pass':actual==expected})
        unknown=vision.plan(np.zeros((864,1470,3),dtype=np.uint8))
        event_vision=Vision(config,session)
        special=event_vision.plan(read_image(SAMPLES/'event_three_special_jp.png'))
        assert special.point[0]<500
        event_vision.event_choice_cache=None
        four=event_vision.plan(read_image(SAMPLES/'event_four_cold.png'))
        assert 500<four.point[0]<620  # left and right both increase erosion
        assert increases_erosion('浸食率20上昇')
        assert choose_event([(1,'普通'),(2,'特殊なイベント開始')],['special_battle','code','other','skip'])==2
        danger_vision=Vision(config)
        danger=danger_vision.plan(read_image(SAMPLES/'event_erosion_warning.png'))
        assert danger.point==(600,585) and danger_vision.event_rejected_x==1080
        assert 'erosion_cancel' in pending_allowed_states('event_selected',{'map'})
        danger= danger_vision.plan(read_image(SAMPLES/'event_nest_wrong_selected.png'))
        assert danger.state=='event_skip' and danger.point[0]<500
        fallback_vision=Vision(dict(config,event_read_timeout_seconds=0))
        fallback=fallback_vision.plan(read_image(SAMPLES/'event_four_cold.png'))
        assert fallback.point[0]<300  # zero read budget immediately chooses left
        assert unknown.state=='unknown' and unknown.point is None
        wide_vision=Vision(config)
        wide=read_image(SAMPLES/'code_reward_1920_capacity37.png')
        assert wide_vision.plan(wide).state=='code_select'
        wide_vision.ratio=lambda *args:(37,37)
        full=wide_vision.plan(wide)
        assert full.state=='code_decline' and full.point[1]>775
        wide_vision.ratio=lambda *args:None
        assert wide_vision.plan(wide).state=='code_select'  # a missed digit must not block selection
        # Same reward page with its receive button shifted within the footer.
        import cv2
        shifted=normalized(read_image(SAMPLES/'code_reward_scaled_20261013.png')).copy()
        assert vision.code_receive_point(shifted) is None  # disabled gray button
        shifted[765:825,865:1020]=(0,210,255)
        received=vision.plan(shifted)
        assert received.state=='code_selected' and 765<received.point[1]<825
        # Inject only the supplied title into real reward screens, covering
        # all slots and an already selected different card.
        import cv2
        priority_vision=Vision(dict(config,code_selection='color_priority',
                                  code_color_priority=['rush','risk','impact','safe']))
        title=priority_vision.templates['preferred_erosion_code_title'][0]
        title=cv2.resize(title,None,fx=.8,fy=.8)
        def preferred_frame(sample,x):
            frame=normalized(read_image(SAMPLES/f'{sample}.png')).copy()
            h,w=title.shape[:2]
            frame[430:430+h,x-w//2:x-w//2+w]=title
            return frame
        for x in (350,735,1116):
            frame=preferred_frame('code_reward_variant40',x)
            decision=priority_vision.plan(frame)
            assert decision.state=='code_select' and decision.point==(x,390)
        frame=preferred_frame('code_selected',735)
        assert priority_vision.plan(frame).point==(735,390)
        frame=preferred_frame('code_selected',350)
        assert priority_vision.plan(frame).state=='code_selected'
        shop_vision=Vision(config)
        shop_frame=read_image(SAMPLES/'shop45_runtime.png')
        assert shop_vision.plan(shop_frame).point==(1096,582)
        shop_vision.total_number=lambda image,rect:None
        assert shop_vision.plan(shop_frame).state=='shop_exit'
        # Existing real shop has a gold bag, but only 120 coins. It must not buy it.
        bag_frame=normalized(read_image(SAMPLES/'shop35_today.png'))
        bag_vision=Vision(config)
        assert bag_vision.plan(bag_frame).point!=(1096,250)
        bag_vision.total_number=lambda *args:300
        assert bag_vision.plan(bag_frame).point==(1096,250)
        confirmation=normalized(read_image(SAMPLES/'shop_confirm35_today.png')).copy()
        confirmation[249:359,363:474]=cv2.resize(bag_frame[182:319,1029:1165],(111,110))
        bag_vision.number=lambda image,rect:300 if rect==(829,610,904,648) else 0
        assert bag_vision.plan(confirmation).state=='shop_confirm'
        bag_vision.number=lambda image,rect:300 if rect==(829,610,904,648) else 1
        assert bag_vision.plan(confirmation).point==(615,694)  # wrong cost is cancelled
        assert bag_vision.shop_bag_rejected
        assert bag_vision.plan(bag_frame).point!=(1096,250)  # do not loop on the failed bag
        # Settlement never invokes number OCR, including unreadable digits.
        no_points_vision=Vision(config)
        no_points_vision.total_number=lambda *args: (_ for _ in ()).throw(AssertionError('settlement OCR called'))
        assert no_points_vision.plan(read_image(SAMPLES/'return_points_large_totals.png')).action=='click'
        returned=vision.plan(read_image(SAMPLES/'boss_return80_runtime.png'))
        animated_return=normalized(read_image(SAMPLES/'boss_return80_runtime.png')).copy()
        animated_return[80:180,540:950]=0
        assert vision.plan(animated_return).state=='boss_return'
        assert returned.point==(735,693)
        assert returned.state in pending_allowed_states('battle_result',{'map'})
        assert returned.state in pending_allowed_states('code_received',{'battle_result'})
        assert vision.recover_stalled(read_image(SAMPLES/'boss_return80_runtime.png'),returned,{'state':'battle_result'}).state=='boss_return'
        assert 'boss_return_confirm' in pending_allowed_states('boss_return',{'return_score'})
        assert 'boss_return' not in pending_allowed_states('boss_return',{'return_score'})
        assert 'boss_return' not in pending_allowed_states('boss_return_confirm',{'return_score'})
        assert vision.recover_stalled(read_image(SAMPLES/'boss_return80_runtime.png'),returned,{'state':'boss_return_confirm'}) is None
        assert vision.recover_stalled(read_image(SAMPLES/'boss_return80_runtime.png'),returned,{'state':'boss_return_confirm','at':0}).state=='boss_return'
        settled=vision.plan(read_image(SAMPLES/'return_points80_runtime.png'))
        assert settled.points is None and settled.action=='click'
        spent=vision.plan(read_image(SAMPLES/'return_points_spent.png'))
        assert spent.points is None and spent.action=='click'
        spent_session=FarmSession(config,Path(tmp)/'spent.json')
        spent_session.snapshot({'impact':1028,'rush':702,'safe':464,'risk':866})
        spent_session.data['pending_return_floor']=80
        assert spent_session.process_return('spent:round',spent.points)
        assert spent_session.data['rounds_completed']==1
        assert spent_session.data['settlements'][-1]['delta'] is None
        assert spent_session.data['settlements'][-1]['points'] is None
        assert not spent_session.process_return('spent:round',spent.points)
        route=vision.plan(read_image(SAMPLES/'map76_chest_ahead.png'))
        assert route.point[0]<700  # strong enemy on left outranks lit ordinary battle on right
        battle_first=Vision(dict(config,route_priority=['battle','elite','other','chest']))
        assert battle_first.plan(read_image(SAMPLES/'map76_chest_ahead.png')).point[0]>700
        shop_first=Vision(dict(config,route_priority=['shop','recovery','event','elite','battle','chest']))
        assert shop_first.plan(read_image(SAMPLES/'map34_recovery_shop.png')).point[0]>700
        assert normalize_route_priority(['chest','other','battle','elite'])==['chest','event','recovery','shop','battle','elite']
        high_checkpoint=Vision(dict(config,checkpoint=100,floors_per_round=50,target_floor=150))
        high_checkpoint.checkpoint_rows=lambda image:{100:(975,450)}
        assert high_checkpoint.plan(read_image(SAMPLES/'checkpoint_today.png')).point==(975,450)
        locked_checkpoint=Vision(dict(config,checkpoint=100,floors_per_round=50,target_floor=150))
        assert locked_checkpoint.plan(read_image(SAMPLES/'checkpoint_today.png')).action=='scroll'
        chest=Vision(config,session)
        chest.last_map_keys=0
        assert chest.plan(read_image(SAMPLES/'chest_options79.png')).point==(735,497)
        chest=Vision(config,session)
        chest.plan(read_image(SAMPLES/'chest_options79.png'))
        chest.chest_trial_started-=1
        assert chest.plan(read_image(SAMPLES/'chest_options79.png')).point==(735,497)
        colors_config=dict(config,code_selection='color_priority',code_color_priority=['impact','risk','safe','rush'])
        color_vision=Vision(colors_config,FarmSession(colors_config,Path(tmp)/'colors.json'))
        chosen=color_vision.plan(read_image(SAMPLES/'code_color_priority77.png'))
        assert chosen.point==(735,390) and chosen.category=='risk'
        d=vision.plan(read_image(SAMPLES/'recovery75_runtime.png'))
        assert d.point==(322,497)  # unselected recovery always chooses left purify
        # An enabled confirm alone must not accept a previously chosen right card.
        recovery_vision=Vision(config,session)
        recovery_vision.yellow_button=lambda image,rect: True
        assert recovery_vision.plan(read_image(SAMPLES/'recovery75_runtime.png')).state=='recovery'
        assert {'recovery','recovery_selected'} <= pending_allowed_states('event_skip',{'event_selected'})
        assert 'event_selected' in pending_allowed_states('recovery',{'recovery_selected'})
        assert 'recovery' not in pending_allowed_states('recovery',{'recovery_selected'})
        assert 'event_skip' in pending_allowed_states('shop',{'shop_confirm'})
        assert 'skip_confirm' in pending_allowed_states('checkpoint_selected',{'formation'})
        assert 'key_confirm' in pending_allowed_states('formation',{'skip_confirm'})
        assert 'formation' not in pending_allowed_states('skip_confirm',{'key_confirm'})
        assert 'key_confirm' not in pending_allowed_states('key_confirm',{'map'})
        key_vision=Vision(config,session)
        key_vision.ratio=lambda image,rect:None
        key_vision.number=lambda image,rect:None
        assert key_vision.plan(read_image(SAMPLES/'key_second_round.png')).action=='wait'
        key_vision.number=lambda image,rect:42 if rect==(1124,291,1174,328) else 1
        assert key_vision.plan(read_image(SAMPLES/'key_second_round.png')).action=='click'
        key_vision.number=lambda image,rect:0
        empty=key_vision.plan(read_image(SAMPLES/'key_second_round.png'))
        assert empty.state=='tickets_empty' and runtime_decision(empty).action=='stop'
        key_vision.number=lambda image,rect:42
        key_vision.ratio=lambda image,rect:(2,3)
        assert key_vision.plan(read_image(SAMPLES/'key_second_round.png')).action=='stop'
        full_vision=Vision(config,session)
        full_vision.ratio=lambda image,rect:(35,35)
        assert full_vision.plan(read_image(SAMPLES/'code_reward_variant40.png')).state=='code_decline'
        assert 'map' in pending_allowed_states('key_confirm',{'party_confirm'})
        assert not stall_recovery_due(14.9,10,None,0,config)
        assert stall_recovery_due(15,10,None,0,config)
        assert not stall_recovery_due(15,0,{'at':14},0,config)
        assert not stall_recovery_due(15,0,{'at':0},14,config)
        assert network_retry_delay(1,config)==.8
        assert network_retry_delay(11,config)==1.6
        assert network_retry_delay(10000,config)==10
        assert page_wait_limit('unknown',config)==config['unknown_timeout_seconds']
        assert page_wait_limit('battle',config)==config['battle_timeout_seconds']
        for state in ('code_full','code_select','boss_continue','key_confirm','shop_confirm','checkpoint_select'):
            blocked=runtime_decision(Decision(state,'stop',reason='不可执行'))
            assert blocked.action=='wait' and blocked.point is None
        assert runtime_decision(Decision('code_selected','click',(940,763))).action=='click'
        high_erosion=Vision(dict(config,erosion_pause_at=0))
        assert high_erosion.plan(read_image(SAMPLES/'map76_chest_ahead.png')).action=='click'
        # A restored reward page supersedes an earlier battle/loading wait.
        assert 'code_select' in pending_allowed_states('map',{'battle'})
        assert 'code_selected' in pending_allowed_states('battle_result',{'map'})
        stale={'state':'event_skip','at':0}
        for name,state in [('recovery75_runtime','recovery'),('event_river','event_skip'),
                           ('shop39','shop'),('map59_side_boss','map')]:
            raw=read_image(SAMPLES/f'{name}.png')
            current=vision.plan(raw)
            recovered=vision.recover_stalled(raw,current,stale)
            assert recovered and recovered.state==state and recovered.action=='click'
        raw=read_image(SAMPLES/'recovery75_runtime.png')
        assert vision.recover_stalled(raw,Decision('unknown'),stale).state=='recovery'
        shop_raw=read_image(SAMPLES/'shop39.png')
        assert vision.recover_stalled(shop_raw,vision.plan(shop_raw),{'state':'shop_confirm'}).state=='shop_exit'
        for state in ('battle','loading','network_retry','code_full'):
            assert vision.recover_stalled(raw,Decision(state),stale) is None
        assert vision.recover_stalled(np.zeros((864,1470,3),dtype=np.uint8),Decision('unknown'),stale) is None
        # Flow fallback can pick among multiple lit platforms without knowing
        # their labels. It waits briefly for the scrolling transition to finish.
        glow=np.zeros((864,1470,3),dtype=np.uint8)
        glow[470:545,200:350]=255
        glow[470:545,900:1050]=255
        fallback_vision=Vision(config,session)
        assert fallback_vision.map_fallback(glow,59) is None
        fallback_vision.map_wait_started-=1
        fallback=fallback_vision.map_fallback(glow,59)
        assert fallback.action=='click' and fallback.point==(975,507)
        d=vision.plan(read_image(SAMPLES/'map32_right_edge.png'))
        assert d.point[0]<=1230  # sidebar must not receive the route click
        d=vision.plan(read_image(SAMPLES/'return_points40.png'))
        assert d.points is None and d.action=='click'
        d=vision.plan(read_image(SAMPLES/'transport_selected_today.png'))
        assert d.point!=(350,480)  # do not toggle an already selected reward
        goal40=dict(config,checkpoint=30,floors_per_round=10,target_floor=40)
        d=Vision(goal40,FarmSession(goal40,Path(tmp)/'short.json')).plan(read_image(SAMPLES/'boss_continue40.png'))
        assert d.state=='boss_return' and d.floor==40
        session.config=dict(config,code_selection='leftmost')
        session.snapshot({'safe':100,'impact':10,'rush':50,'risk':10})
        assert session.choose([(1116,'impact'),(735,'risk'),(350,'safe')])==(350,'safe')
        session.config=dict(config,code_selection='color_priority',code_color_priority=['impact','risk','safe','rush'])
        assert session.choose([(350,'safe'),(735,'risk'),(1116,'impact')])==(1116,'impact')
        assert session.choose([(350,'rush'),(735,'safe')])==(735,'safe')
        priorities=['special_battle','code','skip','other']
        assert choose_event([(390,'代码奖励'),(735,'进入特殊战斗'),(1080,'离开')],priorities)==735
        assert choose_event([(390,'进入特殊战斗 侵蚀率增加10'),(735,'获得代码'),(1080,'离开')],priorities)==735
        assert increases_erosion('侵蝕率が上昇') and not increases_erosion('侵蚀率减少30')
        assert choose_event([(390,'侵蚀率增加10')],priorities) is None
        assert choose_event([(390,''),(735,''),(1080,'')],priorities)==390
        routes=['elite','battle','event','recovery','shop','chest']
        settings=build_config(config,['impact','risk','safe','rush'],routes,'color_priority',30,50,2,5)
        assert settings['target_floor']==80 and settings['max_key_confirmations']>=12
        assert settings['route_priority']==routes and 'event_priority' not in settings
        assert build_config(config,['impact','risk','safe','rush'],routes,'color_priority',100,50,1,5)['target_floor']==150
        try:
            build_config(config,['impact','risk','safe','rush'],routes,'color_priority',100,60,1,5)
        except ValueError:pass
        else:raise AssertionError('target above 150 accepted')
        try:
            build_config(config,['impact']*4,routes,'color_priority',30,50,1,5)
        except ValueError:pass
        else:raise AssertionError('duplicate colors accepted')
        session.config=dict(config,code_selection='leftmost')
        assert session.received('round1:floor31:reward1','safe')
        assert not session.received('round1:floor31:reward1','safe')
        assert session.received('round1:floor32:reward1','safe')  # same event type on a new floor
        assert session.data['points']['safe']==100  # never guess gain from a code
        try:
            session.settle('round1',79,{'safe':120,'impact':30,'rush':60,'risk':25})
        except ValueError:
            pass
        else:
            raise AssertionError('wrong floor accepted')
        assert session.settle('round1',80,{'safe':120,'impact':30,'rush':60,'risk':25})
        assert not session.settle('round1',80,session.data['points'])
        assert session.data['rounds_completed']==1
        assert FarmSession(session.config,session.path).data['rounds_completed']==1
        isolated=FarmSession(dict(config,account_id='another'),Path(tmp)/'another.json')
        assert isolated.data['points'] is None and isolated.data['rounds_completed']==0
        repeat_config=dict(config,checkpoint=30,floors_per_round=10,target_floor=40,max_rounds=2)
        repeat=FarmSession(repeat_config,Path(tmp)/'repeat.json')
        totals={'impact':1015,'rush':661,'safe':451,'risk':866}
        assert not repeat.process_return('old:unknown',totals)
        repeat.data['pending_return_floor']=80
        assert not repeat.process_return('old:80',totals)
        assert repeat.data['rounds_completed']==0
        for n in (1,2):
            repeat.data['pending_return_floor']=40
            assert repeat.process_return(f'new:{n}',totals)
            assert not repeat.process_return(f'new:{n}:retry',totals)
            assert repeat.data['rounds_completed']==n
    report=Path(report_path) if report_path else ROOT/'runs'/'offline-report.json'
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    failed=[r for r in results if not r['pass']]
    print(f'{len(results)-len(failed)}/{len(results)} 截图回放通过；未知页、目标层数、账号隔离、重复事件及点数记账规则通过。')
    for r in failed:
        print(r)
    print(report)
    if failed:
        raise SystemExit(1)

if __name__=='__main__':
    main()
