"""Public entry point. Offline commands never capture or operate the game."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback

from app_paths import data_root, ensure_config, RESOURCE_ROOT
from app_runtime import SingleInstance
from version import VERSION


def main(argv=None):
    parser = argparse.ArgumentParser(description='Dot Abyss 本地识图脚本；F7 暂停，F12 停止。')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--data-dir', type=Path, help='自定义配置、账本和日志目录')
    sub = parser.add_subparsers(dest='command')
    for name in ('settings', 'run', 'observe'):
        mode = sub.add_parser(name)
        mode.add_argument('--config', type=Path)
        if name != 'settings':
            mode.add_argument('--delay', type=float, default=8)
    sub.add_parser('doctor', help='只检查环境，不截图、不点击')
    smoke = sub.add_parser('self-test', help='包内离线自检，不访问游戏')
    smoke.add_argument('--report', type=Path)
    smoke.add_argument('--gui-check', action='store_true', help='创建并关闭隐藏 Tk 窗口')
    replay = sub.add_parser('offline-replay', help='外部截图集回放，不访问游戏')
    replay.add_argument('--samples-dir', type=Path, required=True)
    replay.add_argument('--report', type=Path, required=True)
    analyze = sub.add_parser('analyze', help='离线分析文件，不访问桌面')
    analyze.add_argument('--image', type=Path, required=True)
    analyze.add_argument('--config', type=Path)
    sub.add_parser('reset-config', help='备份用户配置并恢复发行默认值')
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ['DOTABYSS_DATA_DIR'] = str(args.data_dir.resolve())
    command = args.command or 'settings'
    if command == 'self-test':
        from release_smoke import main as smoke_main
        return smoke_main(report_path=args.report, gui_check=args.gui_check)
    if command == 'offline-replay':
        from verify_offline import main as replay_main
        return replay_main(sample_dir=args.samples_dir, report_path=args.report) or 0
    if command == 'reset-config':
        with SingleInstance():
            path = data_root() / 'config.json'
            if path.exists():
                backup = path.with_name('config.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
                path.rename(backup)
                print('旧配置已备份：' + str(backup))
            print('已恢复：' + str(ensure_config()))
        return 0
    if command == 'doctor':
        ensure_config()
        from environment_check import main as doctor_main
        return doctor_main()
    if command == 'analyze':
        from abyss_bot import main as analyze_main
        return analyze_main(['--image', str(args.image), '--config', str(args.config or RESOURCE_ROOT/'config.default.json')]) or 0
    with SingleInstance():
        config = getattr(args, 'config', None) or ensure_config()
        print(f'Dot Abyss {VERSION}\n用户数据：{data_root()}', flush=True)
        if command == 'settings':
            from launcher import main as settings_main
            return settings_main(['--config', str(config)]) or 0
        from abyss_bot import main as run_main
        options = ['--config', str(config), '--delay', str(args.delay)]
        if command == 'run':
            options.append('--run')
        return run_main(options) or 0


def entry():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        return main()
    except KeyboardInterrupt:
        print('用户已停止。', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'无法继续：{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        try:
            folder = data_root() / 'runs'
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ('error-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
            path.write_text(traceback.format_exc(), encoding='utf-8')
            print(f'详细错误保存在：{path}\n配置损坏可执行 DotAbyss.exe reset-config，旧配置会备份。', file=sys.stderr)
        except OSError:
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    raise SystemExit(entry())
