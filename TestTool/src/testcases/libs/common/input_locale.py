"""
在 Windows 上切换键盘布局：SN 弹窗用英文，关闭后恢复简体中文。

非 Windows 或 API 失败时静默忽略（Qt 的 ImhLatinOnly 仍保留）。
"""

from __future__ import annotations

import sys

_LAYOUT_EN_US = "00000409"
_LAYOUT_ZH_CN = "00000804"


def _activate_layout(layout_id: str, *, broadcast: bool = False) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        KLF_ACTIVATE = 0x1
        hkl = user32.LoadKeyboardLayoutW(layout_id, KLF_ACTIVATE)
        if not hkl:
            return
        user32.ActivateKeyboardLayout(hkl, 0)
        if broadcast:
            HWND_BROADCAST = 0xFFFF
            WM_INPUTLANGCHANGEREQUEST = 0x0050
            user32.PostMessageW(
                wintypes.HWND(HWND_BROADCAST),
                wintypes.UINT(WM_INPUTLANGCHANGEREQUEST),
                wintypes.WPARAM(0),
                wintypes.LPARAM(hkl),
            )
    except Exception:
        pass


def activate_english_keyboard_layout() -> None:
    """美式英语，便于扫码枪输入字母数字。"""
    _activate_layout(_LAYOUT_EN_US)


def activate_chinese_keyboard_layout() -> None:
    """简体中文键盘布局（关闭 SN 对话框后恢复中文输入）。"""
    _activate_layout(_LAYOUT_ZH_CN, broadcast=True)
