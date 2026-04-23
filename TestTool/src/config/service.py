"""
YAML-backed configuration service with load/save and basic validation.
"""

from __future__ import annotations

import os
import logging
from typing import Optional, Callable, List

import yaml
from pydantic import ValidationError

from .models import RootConfig


logger = logging.getLogger(__name__)


class ConfigService:
    """Provide load/save/validate operations for application config.

    Parameters
    ----------
    path: str
        YAML file path for the configuration.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._config: Optional[RootConfig] = None
        self._listeners: List[Callable[[RootConfig], None]] = []

    @property
    def path(self) -> str:
        return self._path

    @property
    def config(self) -> RootConfig:
        if self._config is None:
            raise RuntimeError("Configuration not loaded")
        return self._config

    def load(self) -> RootConfig:
        if not os.path.exists(self._path):
            logger.warning("Config file not found, creating default: %s", self._path)
            self._config = RootConfig()
            return self._config
        with open(self._path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        try:
            # 使用model_validate替代parse_obj（Pydantic v2兼容）
            if hasattr(RootConfig, 'model_validate'):
                self._config = RootConfig.model_validate(data)
            else:
                self._config = RootConfig.parse_obj(data)
        except ValidationError as e:
            logger.error("Invalid configuration: %s", e)
            raise
        return self._config

    def save(self, config: Optional[RootConfig] = None) -> None:
        if config is not None:
            self._config = config
        if self._config is None:
            raise RuntimeError("No configuration to save")
        
        # 确保配置文件所在目录存在
        config_dir = os.path.dirname(self._path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
            logger.info("Created config directory: %s", config_dir)
        
        # 使用model_dump替代dict（Pydantic v2兼容）
        if hasattr(self._config, 'model_dump'):
            data = self._config.model_dump(by_alias=False)
        else:
            data = self._config.dict(by_alias=False)
            
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        logger.info("Configuration saved: %s", self._path)
        self._notify_listeners()

    # ---- events ----------------------------------------------------------
    def add_listener(self, callback: Callable[[RootConfig], None]) -> None:
        """Subscribe to config change events.

        Parameters
        ----------
        callback: Callable[[RootConfig], None]
            Function called after successful save with the latest config.
        """
        self._listeners.append(callback)

    def _notify_listeners(self) -> None:
        if self._config is None:
            return
        for cb in list(self._listeners):
            try:
                cb(self._config)
            except Exception as e:  # noqa: BLE001
                logger.error("Config listener error: %s", e)


