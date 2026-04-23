"""
Minimal PCANBasic Python wrapper for local runtime.

This module provides the subset used by test/dogleg/tool.py:
- constants: PCAN_USBBUS1, PCAN_BAUD_1M, PCAN_ERROR_OK, PCAN_ERROR_QRCVEMPTY
- message types: PCAN_MESSAGE_STANDARD, PCAN_MESSAGE_EXTENDED (.value style)
- structs: TPCANMsg, TPCANTimestamp
- class: PCANBasic with Initialize/Uninitialize/Read/Write/GetErrorText
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from ctypes import byref

# Keep ctypes scalar aliases compatible with `from PCANBasic import *` callers.
c_ubyte = ctypes.c_ubyte


# Channel / bitrate constants (subset)
PCAN_USBBUS1 = 0x51
PCAN_BAUD_1M = 0x0014

# Status constants (subset)
PCAN_ERROR_OK = 0x00000
PCAN_ERROR_QRCVEMPTY = 0x00020

# Message type constants (tool.py expects `.value`)
PCAN_MESSAGE_STANDARD = ctypes.c_ubyte(0x00)
PCAN_MESSAGE_EXTENDED = ctypes.c_ubyte(0x02)


class TPCANMsg(ctypes.Structure):
    _fields_ = [
        ("ID", ctypes.c_uint),
        ("MSGTYPE", ctypes.c_ubyte),
        ("LEN", ctypes.c_ubyte),
        ("DATA", ctypes.c_ubyte * 8),
    ]


class TPCANTimestamp(ctypes.Structure):
    _fields_ = [
        ("millis", ctypes.c_uint),
        ("millis_overflow", ctypes.c_ushort),
        ("micros", ctypes.c_ushort),
    ]


def _load_pcan_dll() -> ctypes.WinDLL:
    module_dir = Path(__file__).resolve().parent
    candidates = [
        str(module_dir / "PCANBasic.dll"),
        str(module_dir.parent / "PCANBasic.dll"),
        str(module_dir.parent.parent / "PCANBasic.dll"),
        "PCANBasic.dll",
        r"C:\Windows\System32\PCANBasic.dll",
        r"C:\Windows\SysWOW64\PCANBasic.dll",
        r"C:\Program Files\PEAK-System\PCAN-Basic\PCANBasic.dll",
        r"C:\Program Files\PEAK-System\PCAN-Basic API\PCANBasic.dll",
        r"C:\Program Files (x86)\PEAK-System\PCAN-Basic\PCANBasic.dll",
        r"C:\Program Files (x86)\PEAK-System\PCAN-Basic API\PCANBasic.dll",
    ]
    for dll_path in candidates:
        if os.path.isabs(dll_path) and not os.path.exists(dll_path):
            continue
        try:
            return ctypes.WinDLL(dll_path)
        except OSError:
            continue
    raise OSError("Unable to load PCANBasic.dll from known locations")


class PCANBasic:
    def __init__(self):
        self._dll = _load_pcan_dll()

        self._dll.CAN_Initialize.argtypes = [
            ctypes.c_ushort,
            ctypes.c_ushort,
            ctypes.c_uint,
            ctypes.c_ushort,
            ctypes.c_ushort,
        ]
        self._dll.CAN_Initialize.restype = ctypes.c_uint

        self._dll.CAN_Uninitialize.argtypes = [ctypes.c_ushort]
        self._dll.CAN_Uninitialize.restype = ctypes.c_uint

        self._dll.CAN_Read.argtypes = [
            ctypes.c_ushort,
            ctypes.POINTER(TPCANMsg),
            ctypes.POINTER(TPCANTimestamp),
        ]
        self._dll.CAN_Read.restype = ctypes.c_uint

        self._dll.CAN_Write.argtypes = [ctypes.c_ushort, ctypes.POINTER(TPCANMsg)]
        self._dll.CAN_Write.restype = ctypes.c_uint

        self._dll.CAN_GetErrorText.argtypes = [ctypes.c_uint, ctypes.c_ushort, ctypes.c_char_p]
        self._dll.CAN_GetErrorText.restype = ctypes.c_uint

    def Initialize(self, channel, bitrate, hwtype=0, ioport=0, interrupt=0):
        return int(self._dll.CAN_Initialize(channel, bitrate, hwtype, ioport, interrupt))

    def Uninitialize(self, channel):
        return int(self._dll.CAN_Uninitialize(channel))

    def Read(self, channel):
        msg = TPCANMsg()
        timestamp = TPCANTimestamp()
        status = int(self._dll.CAN_Read(channel, byref(msg), byref(timestamp)))
        return status, msg, timestamp

    def Write(self, channel, msg):
        return int(self._dll.CAN_Write(channel, byref(msg)))

    def GetErrorText(self, error, language):
        # Official API expects >= 256 chars for safety.
        text_buf = ctypes.create_string_buffer(256)
        status = int(self._dll.CAN_GetErrorText(int(error), int(language), text_buf))
        return status, bytes(text_buf.value)
