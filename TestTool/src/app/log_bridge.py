"""
Qt logging bridge: a logging.Handler that emits records via Qt signals.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal


class QtLogSignalHandler(QObject, logging.Handler):
    """Logging handler that forwards log records to Qt via signals."""

    sig_log = Signal(str, int)

    def __init__(self, level: int = logging.INFO, parent: Optional[QObject] = None) -> None:
        QObject.__init__(self, parent)
        logging.Handler.__init__(self, level=level)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # noqa: BLE001 - keep handler robust
            msg = record.getMessage()
        
        # 检查信号源是否仍然有效
        try:
            self.sig_log.emit(msg, record.levelno)
        except RuntimeError:
            # 信号源已被删除，忽略此错误
            pass


