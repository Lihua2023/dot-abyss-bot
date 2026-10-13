"""Build fixed UI anchors from captured 1470x864 game-window screenshots."""
import json
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parent
# name: sample, crop, search ROI. Crops exclude changing numbers and portraits.
SPECS={
 'exploration_failed_title':('exploration_failed_1920',(620,225,856,295),(595,205,880,315)),
 'lost_signal_title':('lost_signal_confirm_1920',(610,165,865,199),(585,145,890,220)),
 'lost_signal_decline':('lost_signal_confirm_1920',(566,673,675,701),(535,650,705,725)),
 'erosion_notice80_body':('erosion_notice80_1920',(550,385,910,420),(525,365,935,440)),
 'erosion_notice80_next':('erosion_notice80_1920',(651,660,827,692),(625,640,855,715)),
 'entrance_tap_pattern':('entrance_1920_after_return',(712,294,801,337),(660,265,845,365)),
 'entrance_ticket_pattern':('entrance_1920_after_return',(716,543,747,563),(680,520,800,590)),
 'shop_close_x':('shop35_today',(1392,52,1431,90),(1360,35,1455,110)),
 'main_menu_auto_icon':('map_menu_accidental',(122,232,200,300),(100,210,220,320)),
 'main_menu_help_icon':('map_menu_accidental',(124,342,197,410),(100,320,220,430)),
 'main_menu_close':('map_menu_accidental',(1361,140,1396,175),(1330,120,1425,195)),
 'map_floor_label_wide':('map32_resolution_current',(67,119,112,141),(30,105,125,154)),
 'code_decline_wide':('code_reward_1920_capacity37',(437,776,588,806),(405,740,620,854)),
 'shop_bag_symbol':('shop35_today',(1065,210,1127,290),(790,190,1160,360)),
 'erosion_warning_body':('event_erosion_warning',(410,375,953,400),(390,350,990,420)),
 'erosion_warning_cancel':('event_erosion_warning',(420,567,681,596),(386,550,725,615)),
 'event_special_word':('event_three_special_jp',(313,619,350,640),(70,565,1395,680)),
 'event_erosion_word':('event_four_cold',(155,634,211,656),(70,565,1395,680)),
 'event_erosion_up':('event_four_cold',(245,634,282,656),(70,565,1395,680)),
 'event_code_effect':('event_four_cold',(1175,591,1329,611),(70,565,1395,680)),
 'network_title':('network_timeout',(596,72,874,104),(560,50,930,122)),
 'network_body':('network_timeout',(550,397,902,429),(520,375,940,447)),
 'network_retry':('network_timeout',(649,763,826,800),(620,747,856,818)),
 'transport_title':('transport40',(460,57,1008,86),(425,40,1040,99)),
 'transport_cancel':('transport40',(794,746,956,783),(757,733,991,801)),
 'transport_list':('transport_today',(255,337,410,361),(238,320,437,380)),
 'transport_selected_mark':('transport_selected_today',(320,421,380,440),(260,395,1180,685)),
 'transport_skip_item':('transport40',(311,612,390,656),(260,395,1180,700)),
 'boss_continue_title':('boss_continue40',(583,110,889,151),(548,89,930,169)),
 'boss_continue_button':('boss_continue40',(893,678,1047,711),(865,660,1085,724)),
 'boss_return_button':('boss_continue40',(661,678,806,711),(620,660,850,724)),
 'return_confirm_message':('return_confirm40',(605,373,863,400),(570,354,903,416)),
 'return_confirm_button':('return_confirm40',(796,569,905,597),(760,550,944,615)),
 'return_score_heading':('return_score40',(691,129,781,151),(660,114,805,168)),
 'return_score_label':('return_score40',(681,375,790,399),(649,353,825,419)),
 'return_score_skip':('return_score40',(1344,52,1414,83),(1318,35,1445,100)),
 'return_score_next':('return_score40',(645,628,827,656),(620,610,850,675)),
 'return_items_heading':('return_points40',(639,128,830,151),(610,115,860,164)),
 'return_bonus_heading':('return_points40',(640,469,831,490),(610,455,861,504)),
 'transport_empty':('transport40',(529,202,572,245),(488,161,980,285)),
 'entrance_records':('entrance_today',(1255,133,1342,158),(1220,115,1370,171)),
 'entrance_keys':('entrance_today',(575,167,754,189),(548,149,780,208)),
 'checkpoint_heading':('checkpoint_today',(639,104,830,132),(610,86,860,149)),
 'checkpoint_card':('checkpoint_today',(854,219,1075,274),(825,201,1100,291)),
 'action_header':('event_music',(557,57,915,88),(530,37,952,105)),
 'recovery_purify':('recovery_options',(283,485,357,519),(244,460,395,542)),
 'recovery_rest':('recovery_options',(698,485,772,519),(650,460,820,542)),
 'action_confirm':('recovery_selected',(637,762,831,802),(620,746,850,818)),
 'event_result_next':('event_music_result',(650,576,821,607),(620,563,851,625)),
 'event_result_bar':('event_music_result',(5,323,400,338),(0,311,430,350)),
 'item_reward_next':('event_item_reward',(650,618,821,647),(620,604,851,666)),
 'item_reward_title':('event_item_reward',(615,249,854,300),(580,228,890,320)),
 'shop_anchor':('shop39',(1256,176,1395,324),(1208,132,1438,340)),
 'shop_key_label':('shop35_today',(1276,348,1375,370),(1250,333,1400,387)),
 'shop_price_coin':('shop39',(1031,741,1055,767),(998,724,1080,786)),
 'shop_confirm_title':('shop_code_confirm',(648,157,824,188),(610,140,857,205)),
 'shop_buy':('shop_code_confirm',(823,681,882,711),(746,665,960,725)),
 'shop_sold':('shop_sold_out',(1025,566,1165,597),(995,535,1205,622)),
 'resume':('entrance_resume40',(670,584,850,630),(630,556,897,650)),
 'resume_yellow':('entrance_resume_today',(670,584,850,630),(630,556,897,650)),
 'erosion_zero':('map35',(1414,153,1436,177),(1390,145,1455,185)),
 'formation_title':('formation',(123,56,185,94),(100,40,220,112)),
 'formation_title_jp':('formation_watermark_jp',(123,56,185,94),(100,40,220,112)),
 'sortie':('formation',(1277,778,1404,815),(1200,750,1460,844)),
 'skip_title':('skip_confirm',(645,264,824,301),(610,245,860,315)),
 'no_skip':('skip_confirm',(468,571,570,598),(420,550,620,620)),
 'key_title':('key_confirm',(612,133,858,169),(565,115,890,183)),
 'use_key':('key_confirm',(823,700,881,730),(745,685,960,748)),
 'party_warning':('party_confirm',(517,291,953,319),(480,270,1000,340)),
 'challenge':('party_confirm',(823,634,879,665),(748,620,958,680)),
 'code_header':('code_select',(643,101,843,130),(620,85,866,145)),
 'reroll':('code_select',(648,733,801,763),(620,720,826,780)),
 'code_decline':('code_select',(434,746,585,781),(410,720,605,810)),
 'receive_enabled':('code_selected',(854,729,1025,800),(845,720,1035,810)),
 'code_confirm':('code_received',(649,777,823,808),(600,754,900,825)),
 'code_received_message':('code_received',(536,202,942,230),(510,187,970,245)),
 'reward_title':('code_received',(651,124,821,162),(610,100,875,180)),
 'result_next':('battle_result',(1306,760,1433,808),(1285,745,1456,829)),
 'quest_clear':('battle_result',(27,54,370,103),(10,35,440,125)),
 'battle_auto':('battle',(1050,798,1173,820),(1030,785,1185,835)),
 'battle_speed':('battle',(1205,798,1330,820),(1188,785,1343,835)),
 'battle_menu':('battle_watermark',(1380,66,1410,92),(1340,44,1455,116)),
 'battle_clock':('battle_watermark',(1350,118,1371,139),(1320,105,1400,157)),
 'map_title':('map31',(126,56,185,95),(103,40,205,112)),
 'map_floor_label':('map31',(43,122,92,146),(20,110,110,156)),
 'route_arrow':('map31',(696,325,772,367),(150,180,1300,555)),
 'route_arrow_edge':('map32_right_edge',(1313,327,1391,372),(35,195,1460,550)),
 'node_elite_text':('map32_today',(299,572,345,593),(0,400,1300,800)),
 'node_battle_text':('map_move_today',(298,509,348,534),(0,400,1300,800)),
 'node_chest_text':('map_chest_label',(710,640,759,666),(0,400,1300,864)),
 'node_event_text':('map33_event',(1095,570,1201,598),(0,400,1470,864)),
 'node_recovery_text':('map34_recovery_shop',(500,570,557,598),(0,400,1470,864)),
 'node_shop_text':('map34_recovery_shop',(886,570,996,598),(0,400,1470,864)),
 'chest_title':('chest_options79',(566,54,905,90),(535,35,935,106)),
 'chest_key_cost':('chest_options79',(274,473,360,528),(245,453,396,547)),
 'chest_animation_skip':('chest_animation79',(1328,51,1452,89),(1300,36,1469,104)),
}

def main():
    folder=ROOT/'assets'/'templates'
    folder.mkdir(parents=True,exist_ok=True)
    manifest={}
    for name,(sample,box,roi) in SPECS.items():
        image=Image.open(ROOT/'samples'/f'{sample}.png').convert('RGB')
        image=image.resize((1470,864))
        image.crop(box).save(folder/f'{name}.png')
        manifest[name]={'file':f'{name}.png','roi':roi,'sample':sample,'crop':box}
    # This user reference is a single card crop, not a full window screenshot.
    name='preferred_erosion_code_title'
    box=(174,274,361,306)
    Image.open(ROOT/'samples/preferred_erosion_code_card.png').convert('RGB').crop(box).save(folder/f'{name}.png')
    manifest[name]={'file':f'{name}.png','roi':[175,416,1300,470],
                    'sample':'preferred_erosion_code_card','crop':box}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Built {len(manifest)} templates')

if __name__=='__main__': main()
