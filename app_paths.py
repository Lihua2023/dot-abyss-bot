"""Shared resource and writable-data paths for source and frozen builds."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import math

FROZEN = bool(getattr(sys, 'frozen', False))
RESOURCE_ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent


def data_root():
    override = os.environ.get('DOTABYSS_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if not FROZEN:
        return RESOURCE_ROOT
    local = os.environ.get('LOCALAPPDATA')
    if not local:
        raise RuntimeError('无法定位 LocalAppData，请指定 --data-dir')
    return Path(local) / 'DotAbyss'


def default_config_path():
    return data_root() / 'config.json'


def ensure_config():
    destination = default_config_path()
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        original = RESOURCE_ROOT / 'config.default.json'
        # Exclusive creation prevents simultaneous first starts overwriting settings.
        try:
            with destination.open('x', encoding='utf-8') as stream:
                stream.write(original.read_text(encoding='utf-8'))
        except FileExistsError:
            pass
    return destination


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(config, dict):
        raise ValueError('配置文件必须是 JSON 对象')
    if config.get('schema_version', 1) != 1:
        raise ValueError('配置版本不兼容，请备份后使用此版本的默认配置')
    for key in ('window_title', 'account_id'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f'{key} 必须是非空文本')
    account = config['account_id']
    if any(c in account for c in '/\\:<>"|?*') or account in ('.', '..') or account.endswith((' ', '.')):
        raise ValueError('账号代号不能包含路径或 Windows 文件名保留字符')
    for key in ('checkpoint', 'floors_per_round', 'max_rounds', 'max_key_confirmations'):
        if type(config.get(key)) is not int or config[key] < 1:
            raise ValueError(f'{key} 必须是正整数')
    for key in ('max_minutes', 'poll_seconds', 'stall_recovery_seconds', 'unknown_timeout_seconds', 'battle_timeout_seconds'):
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} 必须是有限正数')
    screenshots = config.get('max_screenshots_per_run', 2000)
    if type(screenshots) is not int or not 0 <= screenshots <= 10000:
        raise ValueError('max_screenshots_per_run 必须为 0～10000 的整数')
    return config


def asset_path(value):
    path = Path(value)
    return path if path.is_absolute() else RESOURCE_ROOT / path
