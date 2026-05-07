"""
在 Windows 上尽量将当前前台线程键盘布局切到美式英语（00000409），便于扫描 SN 时输入字母数字。

非 Windows 或 API 失败时静默忽略（Qt 的 ImhLatinOnly 仍保留）。
"""

from __future__ import annotations

import sys


def activate_english_keyboard_layout() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        KLF_ACTIVATE = 0x1
        # US English (QWERTY)，与多数扫码枪输出一致
        hkl = user32.LoadKeyboardLayoutW("00000409", KLF_ACTIVATE)
        if hkl:
            user32.ActivateKeyboardLayout(hkl, 0)
    except Exception:
        pass
