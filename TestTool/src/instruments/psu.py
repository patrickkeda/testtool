"""
电源类仪器实现

提供电源控制的具体实现，支持VISA和TCP接口。
"""
import time
import logging
from typing import Optional
from .base import PowerSupplyInstrument


class VisaPowerSupply(PowerSupplyInstrument):
    """基于VISA的电源控制"""
    
    def __init__(self, instrument_id: str, resource: str, timeout_ms: int = 3000):
        super().__init__(instrument_id, resource, timeout_ms)
        self._visa_resource = None
    
    def connect(self) -> bool:
        """连接VISA电源"""
        try:
            import pyvisa
            rm = pyvisa.ResourceManager()
            self._visa_resource = rm.open_resource(self.resource)
            self._visa_resource.timeout = self.timeout_ms
            self._connected = True
            self.log_info(f"VISA电源连接成功: {self.resource}")
            return True
        except Exception as e:
            self.log_error(f"VISA电源连接失败: {e}")
            return False
    
    def disconnect(self) -> None:
        """断开VISA连接"""
        if self._visa_resource:
            try:
                self._visa_resource.close()
                self.log_info("VISA电源连接已断开")
            except Exception as e:
                self.log_error(f"断开VISA连接时出错: {e}")
            finally:
                self._visa_resource = None
                self._connected = False
    
    def reset(self) -> bool:
        """重置电源"""
        if not self._connected:
            return False
        
        try:
            self._visa_resource.write("*RST")
            time.sleep(0.1)
            self.log_info("电源已重置")
            return True
        except Exception as e:
            self.log_error(f"重置电源失败: {e}")
            return False
    
    def set_voltage(self, voltage: float, channel: int = 1) -> bool:
        """设置电压"""
        if not self._connected:
            return False
        
        try:
            cmd = f"SOUR{channel}:VOLT {voltage:.6f}"
            self._visa_resource.write(cmd)
            self.log_info(f"设置通道{channel}电压: {voltage}V")
            return True
        except Exception as e:
            self.log_error(f"设置电压失败: {e}")
            return False
    
    def set_current_limit(self, current: float, channel: int = 1) -> bool:
        """设置电流限制"""
        if not self._connected:
            return False
        
        try:
            cmd = f"SOUR{channel}:CURR {current:.6f}"
            self._visa_resource.write(cmd)
            self.log_info(f"设置通道{channel}电流限制: {current}A")
            return True
        except Exception as e:
            self.log_error(f"设置电流限制失败: {e}")
            return False
    
    def set_output(self, enabled: bool, channel: int = 1) -> bool:
        """设置输出开关"""
        if not self._connected:
            return False
        
        try:
            state = "ON" if enabled else "OFF"
            cmd = f"OUTP{channel} {state}"
            self._visa_resource.write(cmd)
            self.log_info(f"设置通道{channel}输出: {state}")
            return True
        except Exception as e:
            self.log_error(f"设置输出开关失败: {e}")
            return False
    
    def measure_voltage(self, channel: int = 1) -> float:
        """测量电压"""
        if not self._connected:
            return 0.0
        
        try:
            cmd = f"MEAS:VOLT? CH{channel}"
            response = self._visa_resource.query(cmd)
            voltage = float(response.strip())
            self.log_debug(f"测量通道{channel}电压: {voltage}V")
            return voltage
        except Exception as e:
            self.log_error(f"测量电压失败: {e}")
            return 0.0
    
    def measure_current(self, channel: int = 1) -> float:
        """测量电流"""
        if not self._connected:
            return 0.0
        
        try:
            cmd = f"MEAS:CURR? CH{channel}"
            response = self._visa_resource.query(cmd)
            current = float(response.strip())
            self.log_debug(f"测量通道{channel}电流: {current}A")
            return current
        except Exception as e:
            self.log_error(f"测量电流失败: {e}")
            return 0.0
    
    def measure_power(self, channel: int = 1) -> float:
        """测量功率"""
        if not self._connected:
            return 0.0
        
        try:
            cmd = f"MEAS:POW? CH{channel}"
            response = self._visa_resource.query(cmd)
            power = float(response.strip())
            self.log_debug(f"测量通道{channel}功率: {power}W")
            return power
        except Exception as e:
            self.log_error(f"测量功率失败: {e}")
            return 0.0


class TcpPowerSupply(PowerSupplyInstrument):
    """基于TCP的电源控制"""
    
    def __init__(self, instrument_id: str, host: str, port: int, timeout_ms: int = 3000):
        super().__init__(instrument_id, f"TCPIP::{host}::{port}::SOCKET", timeout_ms)
        self.host = host
        self.port = port
        self._socket = None
    
    def connect(self) -> bool:
        """连接TCP电源"""
        try:
            import socket
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout_ms / 1000.0)
            self._socket.connect((self.host, self.port))
            self._connected = True
            self.log_info(f"TCP电源连接成功: {self.host}:{self.port}")
            return True
        except Exception as e:
            self.log_error(f"TCP电源连接失败: {e}")
            return False
    
    def disconnect(self) -> None:
        """断开TCP连接"""
        if self._socket:
            try:
                self._socket.close()
                self.log_info("TCP电源连接已断开")
            except Exception as e:
                self.log_error(f"断开TCP连接时出错: {e}")
            finally:
                self._socket = None
                self._connected = False
    
    def reset(self) -> bool:
        """重置电源"""
        if not self._connected:
            return False
        
        try:
            self._send_command("*RST")
            time.sleep(0.1)
            self.log_info("电源已重置")
            return True
        except Exception as e:
            self.log_error(f"重置电源失败: {e}")
            return False
    
    def set_voltage(self, voltage: float, channel: int = 1) -> bool:
        """设置电压"""
        if not self._connected:
            return False
        
        try:
            cmd = f"SOUR{channel}:VOLT {voltage:.6f}"
            self._send_command(cmd)
            self.log_info(f"设置通道{channel}电压: {voltage}V")
            return True
        except Exception as e:
            self.log_error(f"设置电压失败: {e}")
            return False
    
    def set_current_limit(self, current: float, channel: int = 1) -> bool:
        """设置电流限制"""
        if not self._connected:
            return False
        
        try:
            cmd = f"SOUR{channel}:CURR {current:.6f}"
            self._send_command(cmd)
            self.log_info(f"设置通道{channel}电流限制: {current}A")
            return True
        except Exception as e:
            self.log_error(f"设置电流限制失败: {e}")
            return False
    
    def set_output(self, enabled: bool, channel: int = 1) -> bool:
        """设置输出开关"""
        if not self._connected:
            return False
        
        try:
            state = "ON" if enabled else "OFF"
            cmd = f"OUTP{channel} {state}"
            self._send_command(cmd)
            self.log_info(f"设置通道{channel}输出: {state}")
            return True
        except Exception as e:
            self.log_error(f"设置输出开关失败: {e}")
            return False
    
    def measure_voltage(self, channel: int = 1) -> float:
        """测量电压"""
        if not self._connected:
            return 0.0
        
        try:
            cmd = f"MEAS:VOLT? CH{channel}"
            response = self._send_query(cmd)
            voltage = float(response.strip())
            self.log_debug(f"测量通道{channel}电压: {voltage}V")
            return voltage
        except Exception as e:
            self.log_error(f"测量电压失败: {e}")
            return 0.0
    
    def measure_current(self, channel: int = 1) -> float:
        """测量电流"""
        if not self._connected:
            return 0.0
        
        try:
            cmd = f"MEAS:CURR? CH{channel}"
            response = self._send_query(cmd)
            current = float(response.strip())
            self.log_debug(f"测量通道{channel}电流: {current}A")
            return current
        except Exception as e:
            self.log_error(f"测量电流失败: {e}")
            return 0.0
    
    def measure_power(self, channel: int = 1) -> float:
        """测量功率"""
        if not self._connected:
            return 0.0
        
        try:
            cmd = f"MEAS:POW? CH{channel}"
            response = self._send_query(cmd)
            power = float(response.strip())
            self.log_debug(f"测量通道{channel}功率: {power}W")
            return power
        except Exception as e:
            self.log_error(f"测量功率失败: {e}")
            return 0.0
    
    def _send_command(self, command: str) -> None:
        """发送命令"""
        if not self._socket:
            raise ConnectionError("TCP连接未建立")
        
        cmd_bytes = (command + "\n").encode('utf-8')
        self._socket.send(cmd_bytes)
    
    def _send_query(self, command: str) -> str:
        """发送查询命令并返回响应"""
        if not self._socket:
            raise ConnectionError("TCP连接未建立")
        
        cmd_bytes = (command + "\n").encode('utf-8')
        self._socket.send(cmd_bytes)
        
        response = b""
        while True:
            data = self._socket.recv(1024)
            if not data:
                break
            response += data
            if b"\n" in response:
                break
        
        return response.decode('utf-8').strip()


def create_power_supply(instrument_id: str, interface_type: str, 
                       resource: str = None, host: str = None, port: int = None,
                       timeout_ms: int = 3000) -> PowerSupplyInstrument:
    """
    创建电源实例
    
    Args:
        instrument_id: 仪器标识
        interface_type: 接口类型 (visa/tcp)
        resource: VISA资源字符串
        host: TCP主机地址
        port: TCP端口
        timeout_ms: 超时时间
    
    Returns:
        PowerSupplyInstrument: 电源实例
    """
    if interface_type.lower() == "visa":
        if not resource:
            raise ValueError("VISA接口需要提供resource参数")
        return VisaPowerSupply(instrument_id, resource, timeout_ms)
    
    elif interface_type.lower() == "tcp":
        if not host or not port:
            raise ValueError("TCP接口需要提供host和port参数")
        return TcpPowerSupply(instrument_id, host, port, timeout_ms)
    
    else:
        raise ValueError(f"不支持的接口类型: {interface_type}")
