"""
Simple i18n helper with in-process dictionaries and runtime language switch.

This is a lightweight fallback before real Qt .ts/.qm resources are added.
"""

from __future__ import annotations

from typing import Dict


_TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en_US": {
        "app.title": "TestTool HMI",
        "toolbar.start": "Start",
        "toolbar.pause": "Pause",
        "toolbar.stop": "Stop",
        "toolbar.lang.zh": "中文",
        "toolbar.lang.en": "English",
        "panel.current_step": "Current Step",
        "panel.status": "Status",
        "panel.sn": "SN",
        "panel.retries": "Retries",
        "panel.expect": "Expect",
        "panel.meas": "Meas",
        "panel.plot": "Plot",
        "panel.actions.start": "Start",
        "panel.actions.pause": "Pause",
        "panel.actions.resume": "Resume",
        "panel.actions.stop": "Stop",
        "panel.actions.skip": "Skip",
        "seq.header.step": "Step",
        "seq.header.status": "Status",
        "alerts.started": "[Info] HMI started",
        "config.title": "Port Configuration",
        "config.portA": "Port A",
        "config.portB": "Port B",
        "config.serial": "Serial",
        "config.tcp": "TCP",
        "config.enabled": "Enabled",
        "config.btn.save": "Save",
        "config.btn.reset": "Reset",
        "config.btn.import": "Import",
        "config.btn.export": "Export",
        "config.btn.validate": "Validate",
        "menu.file": "File",
        "menu.file.new": "New",
        "menu.file.open": "Open",
        "menu.file.save": "Save",
        "menu.file.exit": "Exit",
        "menu.config": "Config",
        "menu.config.general": "General",
        "menu.config.ports": "Ports",
        "menu.config.instruments": "Instruments",
        "menu.config.mes": "MES",
        "menu.config.version": "Version",
        "menu.language": "Language",
        "menu.language.chinese": "中文",
        "menu.language.english": "English",
        "menu.info": "Info",
        "menu.info.about": "About",
        "menu.info.manual": "Manual",
        "menu.info.logs": "Logs",
    },
    "zh_CN": {
        "app.title": "测试工具人机界面",
        "toolbar.start": "开始",
        "toolbar.pause": "暂停",
        "toolbar.stop": "停止",
        "toolbar.lang.zh": "中文",
        "toolbar.lang.en": "English",
        "panel.current_step": "当前步骤",
        "panel.status": "状态",
        "panel.sn": "序列号",
        "panel.retries": "重试次数",
        "panel.expect": "期望",
        "panel.meas": "实测",
        "panel.plot": "曲线",
        "panel.actions.start": "开始",
        "panel.actions.pause": "暂停",
        "panel.actions.resume": "继续",
        "panel.actions.stop": "停止",
        "panel.actions.skip": "跳过",
        "seq.header.step": "步骤",
        "seq.header.status": "状态",
        "alerts.started": "[信息] 界面已启动",
        "config.title": "端口配置",
        "config.portA": "端口A",
        "config.portB": "端口B",
        "config.serial": "串口",
        "config.tcp": "TCP",
        "config.enabled": "启用",
        "config.btn.save": "保存",
        "config.btn.reset": "重置",
        "config.btn.import": "导入",
        "config.btn.export": "导出",
        "config.btn.validate": "验证",
        "menu.file": "文件",
        "menu.file.new": "新建",
        "menu.file.open": "打开",
        "menu.file.save": "保存",
        "menu.file.exit": "退出",
        "menu.config": "配置",
        "menu.config.general": "常规",
        "menu.config.ports": "端口",
        "menu.config.instruments": "仪器",
        "menu.config.mes": "MES",
        "menu.config.version": "版本",
        "menu.language": "语言",
        "menu.language.chinese": "中文",
        "menu.language.english": "English",
        "menu.info": "信息",
        "menu.info.about": "关于",
        "menu.info.manual": "手册",
        "menu.info.logs": "日志",
    },
}


class I18n:
    """In-memory translation manager.

    Parameters
    ----------
    locale: str
        Initial locale code, e.g., "en_US" or "zh_CN".
    """

    def __init__(self, locale: str = "en_US") -> None:
        self._locale = locale if locale in _TRANSLATIONS else "en_US"

    @property
    def locale(self) -> str:
        return self._locale

    def set_locale(self, locale: str) -> None:
        if locale in _TRANSLATIONS:
            self._locale = locale

    def t(self, key: str) -> str:
        """Translate a key based on current locale, fallback to en_US or key.

        Parameters
        ----------
        key: str
            Translation key.

        Returns
        -------
        str
            Translated string.
        """
        table = _TRANSLATIONS.get(self._locale, {})
        if key in table:
            return table[key]
        # fallback to English
        return _TRANSLATIONS.get("en_US", {}).get(key, key)


