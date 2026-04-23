"""
Windows IME / keyboard layout helpers.

Goal:
- Best-effort switch current input language to English (en-US, 0x0409)
- Used at app startup and for SN input dialogs/fields
"""

from __future__ import annotations

import sys


def try_switch_to_english() -> bool:
    """Best-effort switch current input language to English (Windows only).

    Returns:
        True if call path executed successfully (doesn't guarantee system changed),
        False if not supported / failed.
    """
    if not sys.platform.startswith("win"):
        return False

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        # en-US layout: "00000409"
        KLF_ACTIVATE = 0x00000001
        hkl = user32.LoadKeyboardLayoutW("00000409", KLF_ACTIVATE)
        if not hkl:
            return False

        user32.ActivateKeyboardLayout(hkl, 0)

        # 异步广播切换输入语言，避免 SendMessageW(HWND_BROADCAST)
        # 在部分机器上阻塞整个桌面消息循环，导致鼠标/窗口明显卡顿。
        HWND_BROADCAST = 0xFFFF
        WM_INPUTLANGCHANGEREQUEST = 0x0050
        user32.PostMessageW(
            wintypes.HWND(HWND_BROADCAST),
            wintypes.UINT(WM_INPUTLANGCHANGEREQUEST),
            wintypes.WPARAM(0),
            wintypes.LPARAM(hkl),
        )
        return True
    except Exception:
        return False

