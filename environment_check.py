"""Local-only environment report. No screen capture, input or uploads."""
import json
import platform
import struct
import sys
from pathlib import Path
from version import VERSION
from app_paths import RESOURCE_ROOT as ROOT, data_root, default_config_path, load_config


def main():
    report={'version':VERSION,'os':platform.system(),'os_release':platform.release(),
            'machine':platform.machine(),'python':platform.python_version(),
            'python_bits':struct.calcsize('P')*8,'capture_mode':'visible game window bounds',
            'screenshots_uploaded':False,'checks':{}}
    problems=[]
    if platform.system()!='Windows':problems.append('仅支持Windows客户端')
    if sys.version_info[:2]!=(3,12) or struct.calcsize('P')!=8:problems.append('需要Python 3.12 x64')
    try:
        from abyss_bot import Vision, GameWindow, supported_window_ratio
        config=load_config(default_config_path())
        report['checks']['templates']=len(Vision(config).templates)
        try:
            window=GameWindow(config['window_title'])
            l,t,r,b=window.bounds()
            report['window']={'width':r-l,'height':b-t,
                'supported_ratio':supported_window_ratio(r-l,b-t),
                'foreground':window.user32.GetForegroundWindow()==window.hwnd,
                'minimized':bool(window.user32.IsIconic(window.hwnd))}
            import ctypes
            dpi=window.user32.GetDpiForWindow(ctypes.c_void_p(window.hwnd))
            report['window']['dpi']=dpi
            report['window']['scaling_percent']=round(dpi/96*100) if dpi else None
            if not report['window']['supported_ratio']:problems.append('窗口比例尚未适配')
            if report['window']['minimized']:problems.append('请恢复游戏窗口')
        except (RuntimeError,AttributeError) as exc:
            problems.append(str(exc))
    except Exception as exc:
        problems.append(f'{type(exc).__name__}: {exc}')
    report['problems']=problems
    folder=data_root()/'runs';folder.mkdir(parents=True,exist_ok=True)
    path=folder/'environment.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('本地报告保存于数据目录 runs/environment.json；仅保存在本机，反馈前请检查内容。')
    return 1 if problems else 0

if __name__=='__main__':raise SystemExit(main())
