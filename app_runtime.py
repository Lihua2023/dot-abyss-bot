"""Process exclusion and cancellation helpers; never sends desktop input."""
from __future__ import annotations

import ctypes
import time


class SingleInstance:
    def __enter__(self):
        kernel = ctypes.windll.kernel32
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetLastError.restype = ctypes.c_ulong
        self.handle = kernel.CreateMutexW(None, False, r'Local\DotAbyssRunner-v1')
        if not self.handle:
            raise ctypes.WinError()
        if kernel.GetLastError() == 183:
            kernel.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError('已有一个设置或运行窗口，请使用现有窗口；禁止同时运行多个脚本')
        return self

    def __exit__(self, *_):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def stop_requested():
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x7B) & 0x8000)


def countdown(seconds):
    end = time.monotonic() + max(0, seconds)
    while time.monotonic() < end:
        if stop_requested():
            raise RuntimeError('F12 取消启动')
        time.sleep(min(.05, max(0, end - time.monotonic())))
