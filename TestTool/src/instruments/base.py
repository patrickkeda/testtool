"""
仪器基类模块

定义仪器控制的通用接口和基类。
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Union
import logging


class IInstrument(ABC):
    """仪器控制接口"""
    
    @abstractmethod
    def connect(self) -> bool:
        """连接仪器"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """检查连接状态"""
        pass
    
    @abstractmethod
    def reset(self) -> bool:
        """重置仪器"""
        pass
    
    @abstractmethod
    def get_id(self) -> str:
        """获取仪器标识"""
        pass


class IPowerSupply(IInstrument):
    """电源接口"""
    @abstractmethod
    def set_voltage(self, voltage: float):
        """设置输出电压"""
        pass

    @abstractmethod
    def set_current_limit(self, limit: float):
        """设置电流限制"""
        pass

    @abstractmethod
    def set_output(self, enabled: bool):
        """设置输出开关"""
        pass

    @abstractmethod
    def measure_voltage(self) -> float:
        """测量电压"""
        pass

    @abstractmethod
    def measure_current(self) -> float:
        """测量电流"""
        pass


class BaseInstrument(IInstrument):
    """仪器基类"""
    
    def __init__(self, instrument_id: str, resource: str, timeout_ms: int = 3000):
        """
        初始化仪器
        
        Args:
            instrument_id: 仪器标识
            resource: 资源字符串（如VISA资源或TCP地址）
            timeout_ms: 超时时间（毫秒）
        """
        self.instrument_id = instrument_id
        self.resource = resource
        self.timeout_ms = timeout_ms
        self.logger = logging.getLogger(f"Instrument.{instrument_id}")
        self._connected = False
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self._connected
    
    def get_id(self) -> str:
        """获取仪器标识"""
        return self.instrument_id
    
    def log_info(self, message: str):
        """记录信息日志"""
        self.logger.info(f"{self.instrument_id}: {message}")
    
    def log_error(self, message: str, error: Exception = None):
        """记录错误日志"""
        if error:
            self.logger.error(f"{self.instrument_id}: {message} - {error}")
        else:
            self.logger.error(f"{self.instrument_id}: {message}")
    
    def log_debug(self, message: str):
        """记录调试日志"""
        self.logger.debug(f"{self.instrument_id}: {message}")


class PowerSupplyInstrument(BaseInstrument):
    """电源类仪器基类"""
    
    @abstractmethod
    def set_voltage(self, voltage: float, channel: int = 1) -> bool:
        """设置电压"""
        pass
    
    @abstractmethod
    def set_current_limit(self, current: float, channel: int = 1) -> bool:
        """设置电流限制"""
        pass
    
    @abstractmethod
    def set_output(self, enabled: bool, channel: int = 1) -> bool:
        """设置输出开关"""
        pass
    
    @abstractmethod
    def measure_voltage(self, channel: int = 1) -> float:
        """测量电压"""
        pass
    
    @abstractmethod
    def measure_current(self, channel: int = 1) -> float:
        """测量电流"""
        pass
    
    @abstractmethod
    def measure_power(self, channel: int = 1) -> float:
        """测量功率"""
        pass


class MultimeterInstrument(BaseInstrument):
    """万用表类仪器基类"""
    
    @abstractmethod
    def measure_voltage_dc(self, channel: int = 1) -> float:
        """测量直流电压"""
        pass
    
    @abstractmethod
    def measure_voltage_ac(self, channel: int = 1) -> float:
        """测量交流电压"""
        pass
    
    @abstractmethod
    def measure_current_dc(self, channel: int = 1) -> float:
        """测量直流电流"""
        pass
    
    @abstractmethod
    def measure_current_ac(self, channel: int = 1) -> float:
        """测量交流电流"""
        pass
    
    @abstractmethod
    def measure_resistance(self, channel: int = 1) -> float:
        """测量电阻"""
        pass
    
    @abstractmethod
    def measure_frequency(self, channel: int = 1) -> float:
        """测量频率"""
        pass


class OscilloscopeInstrument(BaseInstrument):
    """示波器类仪器基类"""
    
    @abstractmethod
    def set_timebase(self, time_per_div: float) -> bool:
        """设置时基"""
        pass
    
    @abstractmethod
    def set_voltage_scale(self, channel: int, volts_per_div: float) -> bool:
        """设置电压刻度"""
        pass
    
    @abstractmethod
    def set_trigger(self, source: int, level: float) -> bool:
        """设置触发"""
        pass
    
    @abstractmethod
    def measure_voltage_peak_to_peak(self, channel: int) -> float:
        """测量峰峰值电压"""
        pass
    
    @abstractmethod
    def measure_frequency(self, channel: int) -> float:
        """测量频率"""
        pass
    
    @abstractmethod
    def measure_period(self, channel: int) -> float:
        """测量周期"""
        pass
