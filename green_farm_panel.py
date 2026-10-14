"""Reusable green-coat tab with settings separate from abyss config."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from app_paths import FROZEN, RESOURCE_ROOT, data_root

PYTHON = Path(sys.executable).with_name('python.exe')
SCRIPT = RESOURCE_ROOT / 'green_farm.py'
SETTINGS = data_root() / 'green_farm_settings.json'
LOG_ROOT = data_root() / 'runs' / 'green_farm'


class GreenFarmPanel:
    def __init__(self, root, parent, *, parent_owns_lock=False):
        self.root, self.parent = root, parent
        self.parent_owns_lock = parent_owns_lock
        self.process = self.output = self.stop_file = self.last_log = self.mode = None
        try:
            saved = json.loads(SETTINGS.read_text(encoding='utf-8'))
            if not isinstance(saved, dict): saved = {}
        except (OSError, ValueError):
            saved = {}
        self.retries = tk.StringVar(master=root, value=str(saved.get('max_retries', 999)))
        self.limit = tk.StringVar(master=root, value=str(saved.get('max_seconds', 180)))
        found = saved.get('on_found', 'pause')
        self.on_found = tk.StringVar(master=root, value=found if found in ('pause', 'auto') else 'pause')
        self.status = tk.StringVar(master=root, value='准备就绪。请先阅读“刷绿衣前必看”。')
        self.build()

    def build(self):
        body = ttk.Frame(self.parent, padding=22)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='绿衣刷取 · 探索深度 10', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(body, text='点开始后 8 秒内切回游戏。F12 可随时停止。').pack(anchor='w', pady=(8, 18))
        options = ttk.Frame(body); options.pack(fill='x')
        ttk.Label(options, text='最多失败重试').grid(row=0, column=0, sticky='w')
        ttk.Entry(options, textvariable=self.retries, width=9).grid(row=0, column=1, padx=(8, 28))
        ttk.Label(options, text='每局上限（秒）').grid(row=0, column=2, sticky='w')
        ttk.Entry(options, textvariable=self.limit, width=9).grid(row=0, column=3, padx=8)
        outcome = ttk.LabelFrame(body, text='识别到绿衣以后', padding=12)
        outcome.pack(fill='x', pady=(20, 8))
        ttk.Radiobutton(outcome, text='暂停，保留战利品界面', variable=self.on_found, value='pause').pack(anchor='w')
        ttk.Radiobutton(outcome, text='打开 AUTO，等到胜利结算后停止', variable=self.on_found, value='auto').pack(anchor='w', pady=(8, 0))
        ttk.Label(body, text='AUTO 通关分支尚未用真实绿衣掉落实机验证；胜利页不会继续点击。',
                  wraplength=530, foreground='#555555').pack(anchor='w', pady=(6, 0))
        ttk.Label(body, text='开局仍先关闭 AUTO、检查首波掉落；必要时攒 4 能量放一次 FC。',
                  wraplength=530, foreground='#555555').pack(anchor='w', pady=(5, 0))
        buttons = ttk.Frame(body); buttons.pack(fill='x', pady=(22, 8))
        self.start_button = ttk.Button(buttons, text='开始刷取', command=lambda: self.start(False))
        self.start_button.pack(side='left')
        self.observe_button = ttk.Button(buttons, text='只检查画面', command=lambda: self.start(True))
        self.observe_button.pack(side='left', padx=8)
        ttk.Button(buttons, text='保存设置', command=self.save_settings).pack(side='left')
        ttk.Button(buttons, text='打开日志', command=self.open_logs).pack(side='left', padx=8)
        self.stop_button = ttk.Button(buttons, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='right')
        ttk.Separator(body).pack(fill='x', pady=(12, 12))
        ttk.Label(body, textvariable=self.status, wraplength=530, foreground='#333333').pack(anchor='w')
        preview_path = RESOURCE_ROOT / 'assets' / 'green_ui' / '宝箱关卡列表.png'
        if preview_path.exists():
            with Image.open(preview_path) as source:
                chest = source.crop((1230, 285, 1620, 575))
                chest.thumbnail((330, 245), Image.Resampling.LANCZOS)
                self.chest_preview = ImageTk.PhotoImage(chest, master=self.root)
            ttk.Label(body, image=self.chest_preview).pack(pady=(24, 5))
            ttk.Label(body, text='宝箱关卡图标参考；实际请选择掉落列表含森林披风的第五层宝箱房。',
                      wraplength=530, foreground='#555555').pack()

    def valid_options(self):
        try:
            retries, seconds = int(self.retries.get()), int(self.limit.get())
        except ValueError as exc:
            raise ValueError('重试次数和每局上限必须是整数') from exc
        if not 0 <= retries <= 9999 or not 30 <= seconds <= 3600:
            raise ValueError('重试次数须为 0～9999；每局上限须为 30～3600 秒')
        if not FROZEN and (not PYTHON.exists() or not SCRIPT.exists()):
            raise FileNotFoundError('找不到脚本或 Python 运行环境，请保留整个项目文件夹')
        return retries, seconds

    def save_settings(self):
        try:
            retries, seconds = self.valid_options()
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            temp = SETTINGS.with_suffix('.tmp')
            temp.write_text(json.dumps({'max_retries': retries, 'max_seconds': seconds,
                                        'on_found': self.on_found.get()}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(SETTINGS)
        except (ValueError, OSError) as exc:
            messagebox.showerror('设置未保存', str(exc), parent=self.root)
            return False
        self.status.set('绿衣设置已单独保存。')
        return True

    def start(self, observe):
        if self.process and self.process.poll() is None: return
        try:
            retries, seconds = self.valid_options()
            if not self.save_settings(): return
            from abyss_bot import GameWindow
            GameWindow('ドットアビスX')
        except Exception as exc:
            messagebox.showerror('无法启动', str(exc), parent=self.root)
            return
        self.mode = 'observe' if observe else 'run'
        self.status.set('8 秒后开始识别，请切回游戏窗口。')
        self.root.iconify()
        self.root.after(250, lambda: self.launch(retries, seconds))

    def launch(self, retries, seconds):
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        self.last_log = LOG_ROOT / f'入口-{stamp}.log'
        self.stop_file = LOG_ROOT / f'入口-{stamp}.stop'
        args = ([str(sys.executable), 'green-run'] if FROZEN else [str(PYTHON), str(SCRIPT)])
        args += ['--' + self.mode, '--delay', '8']
        if self.parent_owns_lock: args.append('--parent-owns-lock')
        if self.mode == 'run':
            args += ['--max-retries', str(retries), '--max-seconds', str(seconds),
                     '--on-found', self.on_found.get(), '--stop-file', str(self.stop_file)]
        try:
            self.output = self.last_log.open('w', encoding='utf-8')
            child_env = os.environ.copy()
            child_env['PYTHONIOENCODING'] = 'utf-8'
            self.process = subprocess.Popen(args, cwd=str(RESOURCE_ROOT), stdout=self.output,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW, env=child_env)
        except Exception as exc:
            if self.output: self.output.close(); self.output = None
            self.root.deiconify()
            messagebox.showerror('启动失败', str(exc), parent=self.root)
            return
        self.start_button.configure(state='disabled')
        self.observe_button.configure(state='disabled')
        self.stop_button.configure(state='normal' if self.mode == 'run' else 'disabled')
        self.status.set('脚本已启动；请保持游戏在前台。F12 可停止。')
        self.root.after(1000, self.poll)

    def poll(self):
        if self.process is None: return
        code = self.process.poll()
        if code is None:
            self.root.after(1000, self.poll)
            return
        if self.output: self.output.close(); self.output = None
        self.start_button.configure(state='normal')
        self.observe_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        message = f'脚本已结束（代码 {code}）。日志：{self.last_log.name}'
        try:
            lines = self.last_log.read_text(encoding='utf-8', errors='replace').splitlines()
            for line in reversed(lines):
                if '"event": "stopped"' in line or '"event": "test_complete"' in line or '"event": "observe_only"' in line:
                    event = json.loads(line)
                    message = f'{event.get("reason") or event.get("state") or message}。日志：{self.last_log.name}'
                    break
        except (OSError, ValueError): pass
        self.status.set(message)
        self.root.deiconify()
        self.root.lift()

    def stop(self):
        if self.process and self.process.poll() is None and self.stop_file:
            self.stop_file.write_text('stop\n', encoding='utf-8')
            self.status.set('已请求停止，等待脚本结束……')

    def open_logs(self):
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        os.startfile(str(LOG_ROOT))

    def close_requested(self):
        if self.process and self.process.poll() is None:
            self.stop()
            self.root.iconify()
            return False
        return True
