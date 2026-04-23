"""
统一入口：序列编辑器

此模块仅转发导入 views 版本，避免两套实现分叉。
"""

from __future__ import annotations

# 转发导入
from ..views.sequence_editor import SequenceEditor  # noqa: F401



