"""Explicit distribution checks, including real OCR; no capture or input."""
import json
import platform
import struct
import sys
import tkinter as tk
from pathlib import Path

def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main(report_path=None, gui_check=False):
    from abyss_bot import Vision, read_image
    from app_paths import RESOURCE_ROOT
    from launcher import build_config
    from farm_policy import CATEGORIES, ROUTE_NAMES
    from version import VERSION
    require(platform.system()=='Windows', '仅支持 Windows')
    require(sys.version_info[:2]==(3,12), '需要 Python 3.12')
    require(struct.calcsize('P')==8, '需要64位 Python')
    tcl_version=tk.Tcl().eval('info patchlevel')
    if gui_check:
        root=tk.Tk();root.withdraw();root.update();root.destroy()
    config=json.loads((RESOURCE_ROOT/'config.default.json').read_text(encoding='utf-8'))
    vision=Vision(config)
    require(len(vision.templates)>=97, '模板数量不完整')
    for name,(template,roi) in vision.templates.items():
        require(template.size>0 and len(roi)==4, f'模板无效：{name}')
        require(0<=roi[0]<roi[2]<=1470 and 0<=roi[1]<roi[3]<=864, f'ROI 无效：{name}')
    build_config(config,list(CATEGORIES),list(ROUTE_NAMES),'leftmost',30,10,1,5)
    number_image=read_image(RESOURCE_ROOT/'assets/selftest/number.png')
    h,w=number_image.shape[:2]
    number=vision.number(number_image,(0,0,w,h))
    require(number==12345, f'数字 OCR 自检失败：{number!r}')
    text_image=read_image(RESOURCE_ROOT/'assets/selftest/text.png')
    h,w=text_image.shape[:2]
    text=vision.text(text_image,(0,0,w,h))
    require('ABYSS' in text.upper(), f'文本检测/识别自检失败：{text!r}')
    report={'version':VERSION,'python':platform.python_version(),
            'frozen':bool(getattr(sys,'frozen',False)), 'templates':len(vision.templates),
            'tcl':tcl_version,'gui_checked':gui_check,'number':number,'text':text,
            'screen_capture':False,'desktop_input':False,'passed':True}
    if report_path:
        path=Path(report_path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
