"""
测试运行上下文模块

提供测试步骤执行时的上下文环境，包括设备实例、状态管理、日志等。
"""
import time
import logging
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, field


@dataclass
class Context:
    """
    测试运行上下文
    
    包含测试执行过程中需要的所有资源：
    - 设备实例（UUT、治具、仪表）
    - 会话状态（SN、测试数据等）
    - 日志记录器
    - 工具方法
    """
    
    # 设备实例
    uut: Optional[Any] = None                    # UUT通讯实例
    fixture: Optional[Any] = None               # 治具控制实例
    instruments: Dict[str, Any] = field(default_factory=dict)  # 仪表实例字典
    
    # 会话状态
    state: Dict[str, Any] = field(default_factory=dict)       # 会话状态数据
    
    # 日志记录器
    logger: Optional[logging.Logger] = None     # 测试日志记录器
    
    # 端口信息
    port: str = "Unknown"                       # 当前测试端口
    
    # 端口配置引用
    _port_config: Optional[Dict[str, Any]] = None  # 端口配置数据
    
    # 通信驱动管理（用于工程服务等）
    _comm_drivers: Dict[str, Any] = field(default_factory=dict)  # 通信驱动字典
    
    def __post_init__(self):
        """初始化后处理"""
        if self.logger is None:
            self.logger = logging.getLogger(f"Test.{self.port}")
    
    def set_port_config(self, config: Dict[str, Any]) -> None:
        """设置端口配置"""
        self._port_config = config
    
    def get_port_config(self, port: Optional[str] = None) -> Dict[str, Any]:
        """获取端口配置"""
        if self._port_config is not None:
            return self._port_config
        return {}
    
    def set_sn(self, sn: str) -> None:
        """设置产品序列号"""
        self.state["sn"] = sn
        self.logger.info(f"设置SN: {sn}")
    
    def get_sn(self) -> str:
        """获取产品序列号"""
        return self.state.get("sn", "NULL")
    
    def set_data(self, key: str, value: Any) -> None:
        """设置会话数据"""
        self.state[key] = value
        self.logger.debug(f"设置数据 {key}: {value}")
    
    def get_data(self, key: str, default: Any = None) -> Any:
        """获取会话数据"""
        return self.state.get(key, default)
    
    def sleep_ms(self, ms: int) -> None:
        """休眠指定毫秒数"""
        if ms > 0:
            time.sleep(ms / 1000.0)
    
    def log_info(self, message: str) -> None:
        """记录信息日志"""
        self.logger.info(message)
    
    def log_debug(self, message: str) -> None:
        """记录调试日志"""
        self.logger.debug(message)
    
    def log_warning(self, message: str) -> None:
        """记录警告日志"""
        self.logger.warning(message)
    
    def log_error(self, message: str, exc_info: bool = False) -> None:
        """记录错误日志
        
        Args:
            message: 日志信息
            exc_info: 是否附带异常栈信息
        """
        try:
            self.logger.error(message, exc_info=exc_info)
        except Exception:
            # 回退，避免日志调用再次抛错
            self.logger.error(message)
    
    def has_instrument(self, instrument_id: str) -> bool:
        """检查是否有指定仪表"""
        return instrument_id in self.instruments
    
    def get_instrument(self, instrument_id: str) -> Any:
        """获取指定仪表实例"""
        if instrument_id not in self.instruments:
            raise KeyError(f"仪表 {instrument_id} 不存在")
        return self.instruments[instrument_id]
    
    def add_instrument(self, instrument_id: str, instrument: Any) -> None:
        """添加仪表实例"""
        self.instruments[instrument_id] = instrument
        self.log_info(f"添加仪表 {instrument_id}: {type(instrument).__name__}")
    
    def remove_instrument(self, instrument_id: str) -> None:
        """移除仪表实例"""
        if instrument_id in self.instruments:
            del self.instruments[instrument_id]
            self.log_info(f"移除仪表 {instrument_id}")
    
    def clear_state(self) -> None:
        """清空会话状态"""
        self.state.clear()
        self.log_info("清空会话状态")
    
    # 状态管理方法（兼容性别名）
    def set_state(self, key: str, value: Any) -> None:
        """设置状态值（等同于 set_data）"""
        self.set_data(key, value)
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """获取状态值（等同于 get_data）"""
        return self.get_data(key, default)
    
    def remove_state(self, key: str) -> None:
        """移除状态值"""
        if key in self.state:
            del self.state[key]
            self.logger.debug(f"移除状态 {key}")
    
    # 通信驱动管理方法
    def set_comm_driver(self, driver_name: str, driver: Any) -> None:
        """设置通信驱动"""
        self._comm_drivers[driver_name] = driver
        self.log_info(f"设置通信驱动: {driver_name}")
    
    def get_comm_driver(self, driver_name: str) -> Optional[Any]:
        """获取通信驱动"""
        return self._comm_drivers.get(driver_name)
    
    def remove_comm_driver(self, driver_name: str) -> None:
        """移除通信驱动"""
        if driver_name in self._comm_drivers:
            del self._comm_drivers[driver_name]
            self.log_info(f"移除通信驱动: {driver_name}")
    
    def has_comm_driver(self, driver_name: str) -> bool:
        """检查是否有指定通信驱动"""
        return driver_name in self._comm_drivers
    
    def set_result(self, step_id: str, result: Any) -> None:
        """设置步骤执行结果
        
        Args:
            step_id: 步骤ID
            result: 步骤结果（StepResult 对象或字典）
        """
        # 存储步骤结果，使用 {step_id}_result 作为键
        self.set_data(f"{step_id}_result", result)
        # 同时存储步骤ID，方便查找
        self.set_data(step_id, result)
        self.logger.debug(f"设置步骤结果: {step_id}")
    
    def get_result(self, step_id: str, default: Any = None) -> Any:
        """获取步骤执行结果
        
        Args:
            step_id: 步骤ID
            default: 默认值
            
        Returns:
            步骤结果
        """
        # 优先通过 {step_id}_result 获取
        result = self.get_data(f"{step_id}_result")
        if result is None:
            # 如果不存在，尝试直接通过 step_id 获取
            result = self.get_data(step_id, default)
        return result
    
    def get_summary(self) -> Dict[str, Any]:
        """获取上下文摘要信息"""
        return {
            "port": self.port,
            "sn": self.get_sn(),
            "instruments": list(self.instruments.keys()),
            "state_keys": list(self.state.keys()),
            "has_uut": self.uut is not None,
            "has_fixture": self.fixture is not None,
        }


def create_context(port: str, 
                  uut: Optional[Any] = None,
                  fixture: Optional[Any] = None,
                  instruments: Optional[Dict[str, Any]] = None,
                  logger: Optional[logging.Logger] = None) -> Context:
    """
    创建测试上下文实例
    
    Args:
        port: 测试端口名称
        uut: UUT通讯实例
        fixture: 治具控制实例
        instruments: 仪表实例字典
        logger: 日志记录器
    
    Returns:
        Context: 配置好的上下文实例
    """
    context = Context(
        port=port,
        uut=uut,
        fixture=fixture,
        instruments=instruments or {},
        logger=logger
    )
    
    if logger:
        logger.info(f"创建测试上下文: {port}")
        logger.debug(f"上下文摘要: {context.get_summary()}")
    
    return context