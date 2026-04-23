"""
Modbus测试步骤 - 电机控制与数据采集

功能：
1. Modbus TCP连接和断开
2. 写入线圈控制电机
3. 读取寄存器获取电机数据
4. 记录数据到CSV文件
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any
import time
import csv
from datetime import datetime
from pathlib import Path

try:
    from pymodbus.client import ModbusTcpClient
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False
    ModbusTcpClient = None


class ModbusConnectStep(BaseStep):
    """Modbus连接步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        连接Modbus TCP
        
        参数：
        - ip: Modbus服务器IP地址
        - port: Modbus服务器端口（默认502）
        - timeout: 连接超时时间（秒，默认5）
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus库未安装",
                error="请安装pymodbus: pip install pymodbus",
                error_code="MODBUS_ERR_LIB_NOT_FOUND"
            )
        
        try:
            # 解析参数
            ip = self._resolve_str_param(params.get("ip", "192.168.0.22"), ctx)
            port = self._resolve_int_param(params.get("port", 502), ctx, default=502)
            timeout = self._resolve_int_param(params.get("timeout", 5), ctx, default=5)
            
            ctx.log_info(f"正在连接Modbus TCP: {ip}:{port}, 超时: {timeout}秒")
            
            # 创建Modbus客户端
            client = ModbusTcpClient(host=ip, port=port, timeout=timeout)
            
            # 连接
            if client.connect():
                ctx.log_info(f"✓ Modbus TCP连接成功: {ip}:{port}")
                
                # 保存客户端到上下文
                ctx.set_comm_driver("modbus", client)
                ctx.set_state("modbus_connected", True)
                ctx.set_state("modbus_ip", ip)
                ctx.set_state("modbus_port", port)
                
                return StepResult(
                    passed=True,
                    message=f"Modbus连接成功: {ip}:{port}",
                    data={
                        "ip": ip,
                        "port": port,
                        "connected": True
                    }
                )
            else:
                ctx.log_error(f"✗ Modbus TCP连接失败: {ip}:{port}")
                return StepResult(
                    passed=False,
                    message=f"Modbus连接失败: {ip}:{port}",
                    error="连接失败",
                    error_code="MODBUS_ERR_CONNECT_FAILED"
                )
                
        except Exception as e:
            ctx.log_error(f"Modbus连接异常: {e}")
            return StepResult(
                passed=False,
                message=f"Modbus连接异常: {e}",
                error=str(e),
                error_code="MODBUS_ERR_CONNECT_EXCEPTION"
            )
    
    def _resolve_str_param(self, value: Any, ctx: Context) -> str:
        """解析字符串参数并进行变量替换"""
        if isinstance(value, str):
            return self._replace_variables(value, ctx)
        return str(value)
    
    def _resolve_int_param(self, value: Any, ctx: Context, default: int = 0) -> int:
        """解析整数参数，支持变量替换"""
        try:
            if isinstance(value, str):
                value = self._replace_variables(value, ctx)
            return int(value)
        except (ValueError, TypeError):
            ctx.log_warning(f"整数参数解析失败，使用默认值 {default}")
            return default
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """替换文本中的变量引用"""
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            if var_name == "sn":
                value = ctx.get_sn()
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return value
            elif var_name == "port":
                return ctx.port
            else:
                value = ctx.get_data(var_name, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
                else:
                    ctx.log_warning(f"未找到变量: ${{{var_name}}}")
                    return match.group(0)
        
        return re.sub(pattern, replace_var, text)


class ModbusWriteCoilStep(BaseStep):
    """Modbus写入线圈步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        写入Modbus线圈
        
        参数：
        - address: 线圈地址
        - value: 线圈值（True/False）
        - description: 描述（可选）
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus库未安装",
                error="请安装pymodbus: pip install pymodbus",
                error_code="MODBUS_ERR_LIB_NOT_FOUND"
            )
        
        try:
            # 获取Modbus客户端
            client = ctx.get_comm_driver("modbus")
            if not client:
                return StepResult(
                    passed=False,
                    message="Modbus未连接",
                    error="请先执行modbus.connect步骤",
                    error_code="MODBUS_ERR_NOT_CONNECTED"
                )
            
            # 解析参数
            address = self.get_param_int(params, "address", 0)
            value = self.get_param_bool(params, "value", False)
            description = self.get_param_str(params, "description", "")
            # duration_ms参数：如果存在则使用，否则默认为0
            duration_ms = params.get("duration_ms", 0)
            if isinstance(duration_ms, str):
                # 如果是字符串，尝试转换为整数
                try:
                    duration_ms = int(duration_ms)
                except ValueError:
                    duration_ms = 0
            else:
                duration_ms = int(duration_ms) if duration_ms else 0
            
            ctx.log_info(f"写入线圈 {address} = {value} ({description})")
            
            # 写入线圈
            try:
                resp = client.write_coil(address, value)
            except TypeError:
                # 兼容不同版本的pymodbus API
                try:
                    resp = client.write_coil(address=address, value=value)
                except:
                    resp = None
            
            if resp and not resp.isError():
                ctx.log_info(f"✓ 线圈写入成功: {address} = {value}")
                
                # 如果指定了持续时间，保持状态后恢复
                if duration_ms > 0:
                    ctx.log_info(f"保持线圈 {address} = {value} 持续 {duration_ms}ms")
                    ctx.sleep_ms(duration_ms)
                    
                    # 恢复为相反状态
                    release_value = not value
                    try:
                        release_resp = client.write_coil(address, release_value)
                    except TypeError:
                        try:
                            release_resp = client.write_coil(address=address, value=release_value)
                        except:
                            release_resp = None
                    
                    if release_resp and not release_resp.isError():
                        ctx.log_info(f"✓ 线圈恢复成功: {address} = {release_value}")
                    else:
                        ctx.log_warning(f"⚠️  线圈恢复可能未生效: {address}")
                
                return StepResult(
                    passed=True,
                    message=f"线圈写入成功: {address} = {value}" + (f" (持续 {duration_ms}ms)" if duration_ms > 0 else ""),
                    data={
                        "address": address,
                        "value": value,
                        "duration_ms": duration_ms,
                        "description": description
                    }
                )
            else:
                ctx.log_warning(f"⚠️  线圈写入可能未生效: {address}")
                return StepResult(
                    passed=False,
                    message=f"线圈写入失败: {address}",
                    error="写入响应异常",
                    error_code="MODBUS_ERR_WRITE_FAILED"
                )
                
        except Exception as e:
            ctx.log_error(f"写入线圈异常: {e}")
            return StepResult(
                passed=False,
                message=f"写入线圈异常: {e}",
                error=str(e),
                error_code="MODBUS_ERR_WRITE_EXCEPTION"
            )


class ModbusWriteRegisterStep(BaseStep):
    """Modbus写入保持寄存器步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        写入Modbus保持寄存器
        
        参数：
        - address: 寄存器地址（支持4xxxx格式，会自动转换为实际地址）
        - value: 寄存器值（整数）
        - unit_id: 从站地址（可选，默认1）
        - description: 描述（可选）
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus库未安装",
                error="请安装pymodbus: pip install pymodbus",
                error_code="MODBUS_ERR_LIB_NOT_FOUND"
            )
        
        try:
            # 获取Modbus客户端
            client = ctx.get_comm_driver("modbus")
            if not client:
                return StepResult(
                    passed=False,
                    message="Modbus未连接",
                    error="请先执行modbus.connect步骤",
                    error_code="MODBUS_ERR_NOT_CONNECTED"
                )
            
            # 解析参数，支持变量替换
            address_str = str(params.get("address", "0"))
            # 替换变量
            address_str = self._replace_variables(address_str, ctx)
            address = int(address_str)
            
            value_str = str(params.get("value", "0"))
            # 替换变量
            value_str = self._replace_variables(value_str, ctx)
            value = int(value_str)
            
            # 获取unit_id，支持变量替换
            unit_id_val = params.get("unit_id", 1)
            if isinstance(unit_id_val, str):
                unit_id_val = self._replace_variables(unit_id_val, ctx)
            unit_id = int(unit_id_val) if unit_id_val else 1
            
            description = self.get_param_str(params, "description", "")
            
            # 地址转换：如果地址>=40000，说明是显示地址（4xxxx），需要转换为实际地址
            # 根据ModScan文档和Modbus标准：
            # - 4xxxx格式：40001对应实际地址0（Modbus地址从0开始）
            # - 转换公式：实际地址 = 显示地址 - 40001
            # - 例如：41095 -> 41095 - 40001 = 1094
            # 这样实际地址1094对应显示地址41095（1094 + 40001 = 41095）
            # 如果使用 address - 40000，会得到1095，对应显示地址41096（1095 + 40001 = 41096），这是错误的
            actual_address = address
            address_converted = False
            if address >= 40000:
                # 4xxxx格式，转换为实际地址
                # 使用标准转换公式：41095 - 40001 = 1094（对应显示地址41095）
                actual_address = address - 40001
                address_converted = True
                ctx.log_info(f"地址转换: 显示地址 {address} -> 实际地址 {actual_address} (转换公式: address - 40001)")
                ctx.log_info(f"验证: 实际地址 {actual_address} 对应显示地址 {actual_address + 40001}")
            else:
                # 如果地址小于40000，假设已经是实际地址
                actual_address = address
                ctx.log_info(f"使用原始地址（小于40000，假设已是实际地址）: {actual_address}")
            
            ctx.log_info(f"准备写入保持寄存器: 显示地址={address}, 实际地址={actual_address}, 值={value}, unit_id={unit_id}")
            
            # 写入保持寄存器，兼容不同版本的pymodbus API
            # 注意：对于Modbus TCP，unit_id通常包含在MBAP头中
            resp = None
            last_error = None
            
            # 方法1：尝试使用unit参数（新版pymodbus 3.x）
            try:
                ctx.log_debug(f"尝试方法1: write_register({actual_address}, {value}, unit={unit_id})")
                resp = client.write_register(actual_address, value, unit=unit_id)
                if resp and not resp.isError():
                    ctx.log_info(f"✓ 方法1成功: 使用unit参数")
            except Exception as e1:
                last_error = str(e1)
                ctx.log_debug(f"方法1失败: {e1}")
                
                # 方法2：尝试使用device_id参数
                try:
                    ctx.log_debug(f"尝试方法2: write_register({actual_address}, {value}, device_id={unit_id})")
                    resp = client.write_register(actual_address, value, device_id=unit_id)
                    if resp and not resp.isError():
                        ctx.log_info(f"✓ 方法2成功: 使用device_id参数")
                except Exception as e2:
                    last_error = str(e2)
                    ctx.log_debug(f"方法2失败: {e2}")
                    
                    # 方法3：尝试使用命名参数
                    try:
                        ctx.log_debug(f"尝试方法3: write_register(address={actual_address}, value={value}, unit={unit_id})")
                        resp = client.write_register(address=actual_address, value=value, unit=unit_id)
                        if resp and not resp.isError():
                            ctx.log_info(f"✓ 方法3成功: 使用命名参数unit")
                    except Exception as e3:
                        last_error = str(e3)
                        ctx.log_debug(f"方法3失败: {e3}")
                        
                        # 方法4：尝试不使用unit参数（某些TCP实现可能不需要）
                        try:
                            ctx.log_debug(f"尝试方法4: write_register({actual_address}, {value})")
                            resp = client.write_register(actual_address, value)
                            if resp and not resp.isError():
                                ctx.log_info(f"✓ 方法4成功: 不使用unit参数")
                        except Exception as e4:
                            last_error = str(e4)
                            ctx.log_debug(f"方法4失败: {e4}")
                            resp = None
            
            # 检查响应
            if resp:
                if hasattr(resp, 'isError'):
                    if not resp.isError():
                        ctx.log_info(f"✓ Modbus写入响应成功: 地址={actual_address} (显示={address}) = {value}, unit_id={unit_id}")
                        
                        # 等待一小段时间，确保写入生效
                        ctx.sleep_ms(100)
                        
                        # 强制验证写入：读取回寄存器值确认
                        verification_passed = False
                        read_value = None
                        read_error = None
                        try:
                            # 尝试多种读取方式
                            # 注意：对于Modbus TCP，read_holding_registers通常只需要address和count两个位置参数
                            # unit_id通常在连接时设置，或者使用命名参数传递
                            read_resp = None
                            # 方法1：不使用unit参数（Modbus TCP通常不需要）
                            try:
                                ctx.log_debug(f"验证读取方法1: read_holding_registers({actual_address}, 1)")
                                read_resp = client.read_holding_registers(actual_address, 1)
                                if read_resp and not read_resp.isError():
                                    ctx.log_debug(f"✓ 验证读取方法1成功")
                            except Exception as e1:
                                read_error = str(e1)
                                ctx.log_debug(f"验证读取方法1失败: {e1}")
                                # 方法2：使用命名参数address和count
                                try:
                                    ctx.log_debug(f"验证读取方法2: read_holding_registers(address={actual_address}, count=1)")
                                    read_resp = client.read_holding_registers(address=actual_address, count=1)
                                    if read_resp and not read_resp.isError():
                                        ctx.log_debug(f"✓ 验证读取方法2成功")
                                except Exception as e2:
                                    read_error = str(e2)
                                    ctx.log_debug(f"验证读取方法2失败: {e2}")
                                    # 方法3：尝试使用命名参数address和count（不使用unit）
                                    try:
                                        ctx.log_debug(f"验证读取方法3: read_holding_registers(address={actual_address}, count=1)")
                                        read_resp = client.read_holding_registers(address=actual_address, count=1)
                                        if read_resp and not read_resp.isError():
                                            ctx.log_debug(f"✓ 验证读取方法3成功")
                                    except Exception as e3:
                                        read_error = str(e3)
                                        ctx.log_debug(f"验证读取方法3失败: {e3}")
                                        read_resp = None
                            
                            if read_resp and not read_resp.isError() and len(read_resp.registers) > 0:
                                read_value = read_resp.registers[0]
                                if read_value == value:
                                    ctx.log_info(f"✓ 写入验证成功: 读取回的值 {read_value} 与写入值 {value} 一致")
                                    verification_passed = True
                                else:
                                    ctx.log_error(f"✗ 写入验证失败: 写入值={value}, 读取值={read_value}, 地址={actual_address} (显示={address})")
                                    # 如果验证失败，尝试其他地址转换方式
                                    if address_converted and address >= 40000:
                                        # 尝试方式1：address - 40001（某些系统可能使用）
                                        alt_address1 = address - 40001
                                        ctx.log_info(f"尝试备用地址转换方式1: {address} - 40001 = {alt_address1}")
                                        try:
                                            alt_resp1 = client.write_register(alt_address1, value, device_id=unit_id)
                                            if alt_resp1 and not alt_resp1.isError():
                                                ctx.sleep_ms(100)
                                                alt_read_resp1 = client.read_holding_registers(alt_address1, 1)
                                                if alt_read_resp1 and not alt_read_resp1.isError() and len(alt_read_resp1.registers) > 0:
                                                    alt_read_value1 = alt_read_resp1.registers[0]
                                                    ctx.log_info(f"备用地址1 ({alt_address1}) 读取值: {alt_read_value1}")
                                                    if alt_read_value1 == value:
                                                        ctx.log_info(f"✓ 使用备用地址转换方式1成功: {alt_address1} = {value}")
                                                        verification_passed = True
                                                        read_value = alt_read_value1
                                                        actual_address = alt_address1
                                        except Exception as e:
                                            ctx.log_debug(f"备用地址方式1失败: {e}")
                                        
                                        # 如果方式1失败，尝试直接使用原始地址（某些设备可能接受4xxxx格式）
                                        if not verification_passed:
                                            ctx.log_info(f"尝试直接使用原始地址: {address}")
                                            try:
                                                alt_resp2 = client.write_register(address, value, device_id=unit_id)
                                                if alt_resp2 and not alt_resp2.isError():
                                                    ctx.sleep_ms(100)
                                                    alt_read_resp2 = client.read_holding_registers(address, 1)
                                                    if alt_read_resp2 and not alt_read_resp2.isError() and len(alt_read_resp2.registers) > 0:
                                                        alt_read_value2 = alt_read_resp2.registers[0]
                                                        ctx.log_info(f"原始地址 ({address}) 读取值: {alt_read_value2}")
                                                        if alt_read_value2 == value:
                                                            ctx.log_info(f"✓ 使用原始地址成功: {address} = {value}")
                                                            verification_passed = True
                                                            read_value = alt_read_value2
                                                            actual_address = address
                                            except Exception as e:
                                                ctx.log_debug(f"原始地址方式失败: {e}")
                            else:
                                error_detail = f"读取响应异常: {read_resp}" if read_resp else f"读取失败: {read_error}"
                                ctx.log_error(f"✗ 无法读取寄存器进行验证: {error_detail}")
                        except Exception as e:
                            ctx.log_error(f"✗ 写入验证过程异常: {e}")
                            read_error = str(e)
                        
                        # 验证结果处理：
                        # - 如果验证成功（值匹配），步骤通过
                        # - 如果验证读取失败（无法读取），但写入响应成功，步骤通过（记录警告）
                        # - 如果验证读取成功但值不匹配，步骤失败
                        if verification_passed:
                            # 验证成功
                            return StepResult(
                                passed=True,
                                message=f"保持寄存器写入成功并验证: {address} = {value}",
                                data={
                                    "address": address,
                                    "actual_address": actual_address,
                                    "value": value,
                                    "read_value": read_value,
                                    "unit_id": unit_id,
                                    "description": description
                                }
                            )
                        elif read_value is not None and read_value != value:
                            # 读取成功但值不匹配，步骤失败
                            error_msg = f"写入后验证失败: 写入值={value}, 读取值={read_value}, 地址={actual_address} (显示={address})"
                            ctx.log_error(f"✗ {error_msg}")
                            return StepResult(
                                passed=False,
                                message=f"保持寄存器写入验证失败: 地址={address}, 写入={value}, 读取={read_value}",
                                error=error_msg,
                                error_code="MODBUS_ERR_WRITE_VERIFICATION_FAILED",
                                data={
                                    "address": address,
                                    "actual_address": actual_address,
                                    "value": value,
                                    "read_value": read_value,
                                    "unit_id": unit_id,
                                    "description": description
                                }
                            )
                        else:
                            # 无法读取验证，但写入响应成功，步骤通过（记录警告）
                            warning_msg = "无法读取寄存器进行验证"
                            if read_error:
                                warning_msg += f" (错误: {read_error})"
                            ctx.log_warning(f"⚠️  {warning_msg}，但写入响应成功，假设写入已生效")
                            return StepResult(
                                passed=True,
                                message=f"保持寄存器写入成功: {address} = {value} (验证读取失败，但写入响应成功)",
                                data={
                                    "address": address,
                                    "actual_address": actual_address,
                                    "value": value,
                                    "read_value": None,
                                    "read_error": read_error,
                                    "unit_id": unit_id,
                                    "description": description,
                                    "verification_warning": warning_msg
                                }
                            )
                    else:
                        error_msg = f"响应错误: {resp}"
                        ctx.log_error(f"✗ 保持寄存器写入失败: {error_msg}")
                else:
                    # 没有isError方法，假设成功
                    ctx.log_info(f"✓ 保持寄存器写入完成（无错误检查）: 地址={actual_address} (显示={address}) = {value}")
                    return StepResult(
                        passed=True,
                        message=f"保持寄存器写入完成: {address} = {value}",
                        data={
                            "address": address,
                            "actual_address": actual_address,
                            "value": value,
                            "unit_id": unit_id,
                            "description": description
                        }
                    )
            else:
                error_msg = f"无响应，最后错误: {last_error}" if last_error else "无响应"
                ctx.log_error(f"✗ 保持寄存器写入失败: 地址={actual_address} (显示={address}), {error_msg}")
                return StepResult(
                    passed=False,
                    message=f"保持寄存器写入失败: {address}",
                    error=error_msg,
                    error_code="MODBUS_ERR_WRITE_FAILED"
                )
                
        except Exception as e:
            ctx.log_error(f"写入保持寄存器异常: {e}", exc_info=True)
            return StepResult(
                passed=False,
                message=f"写入保持寄存器异常: {e}",
                error=str(e),
                error_code="MODBUS_ERR_WRITE_EXCEPTION"
            )
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """替换文本中的变量引用"""
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            if var_name == "sn":
                value = ctx.get_sn()
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return value
            elif var_name == "port":
                return ctx.port
            elif var_name.startswith("context."):
                # 从上下文状态获取
                key = var_name[8:]  # 去掉 "context." 前缀
                value = ctx.get_data(key, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
            else:
                # 尝试从上下文状态直接获取
                value = ctx.get_data(var_name, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
            ctx.log_warning(f"未找到变量: ${{{var_name}}}")
            return match.group(0)
        
        return re.sub(pattern, replace_var, text)


class ModbusRecordDataStep(BaseStep):
    """Modbus记录数据步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        记录Modbus数据到CSV文件
        
        参数：
        - duration: 记录时长（秒）
        - interval_ms: 记录间隔（毫秒）
        - register_address: 寄存器起始地址（默认100）
        - register_count: 寄存器数量（默认4）
        - coil_address: 线圈起始地址（默认100）
        - coil_count: 线圈数量（默认3）
        - sn: 序列号（用于文件名）
        - output_path: 输出文件路径
        """
        if not PYMODBUS_AVAILABLE:
            return StepResult(
                passed=False,
                message="pymodbus库未安装",
                error="请安装pymodbus: pip install pymodbus",
                error_code="MODBUS_ERR_LIB_NOT_FOUND"
            )
        
        try:
            # 获取Modbus客户端
            client = ctx.get_comm_driver("modbus")
            if not client:
                return StepResult(
                    passed=False,
                    message="Modbus未连接",
                    error="请先执行modbus.connect步骤",
                    error_code="MODBUS_ERR_NOT_CONNECTED"
                )
            
            # 解析参数（支持变量替换）
            duration_val = params.get("duration", 15.0)
            if isinstance(duration_val, str):
                duration_val = self._replace_variables(duration_val, ctx)
            duration = float(duration_val)
            
            interval_ms_val = params.get("interval_ms", 10)
            if isinstance(interval_ms_val, str):
                interval_ms_val = self._replace_variables(interval_ms_val, ctx)
            interval_ms = int(interval_ms_val)
            
            register_address = self.get_param_int(params, "register_address", 100)
            register_count = self.get_param_int(params, "register_count", 4)
            coil_address = self.get_param_int(params, "coil_address", 100)
            coil_count = self.get_param_int(params, "coil_count", 3)
            sn = self._resolve_str_param(params.get("sn", ctx.get_sn()), ctx)
            output_path = self._resolve_str_param(params.get("output_path", f"Result/motor/{sn}.csv"), ctx)
            
            ctx.log_info(f"开始记录数据: 时长={duration}秒, 间隔={interval_ms}ms, SN={sn}")
            
            # 确保输出目录存在
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            ctx.log_info(f"开始记录数据到: {output_path}")
            
            # 记录数据
            records = []
            start_time = time.time()
            interval_sec = interval_ms / 1000.0
            last_record_time = start_time
            
            while (time.time() - start_time) < duration:
                current_time = time.time()
                
                # 检查是否到了记录时间
                if (current_time - last_record_time) >= interval_sec:
                    try:
                        # 读取寄存器（角度、角速度、扭矩、温度）
                        try:
                            regs_resp = client.read_holding_registers(register_address, register_count)
                        except TypeError:
                            regs_resp = client.read_holding_registers(address=register_address, count=register_count)
                        
                        # 读取线圈（使能、停止、运行）
                        try:
                            coils_resp = client.read_coils(coil_address, coil_count)
                        except TypeError:
                            coils_resp = client.read_coils(address=coil_address, count=coil_count)
                        
                        if regs_resp and not regs_resp.isError() and coils_resp and not coils_resp.isError():
                            # 解析寄存器数据
                            registers = regs_resp.registers
                            motor_data = self._parse_motor_data(registers)
                            
                            # 解析线圈数据
                            coils = coils_resp.bits[:coil_count] if hasattr(coils_resp, 'bits') else [False] * coil_count
                            
                            # 创建记录
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                            # 解析线圈：coils[0]=使能, coils[1]=停止, coils[2]=运行
                            enable = coils[0] if len(coils) > 0 else False
                            run = coils[2] if len(coils) > 2 else False
                            
                            record = {
                                '时间戳': timestamp,
                                '角度(°)': motor_data.get('angle', 0.0),
                                '角速度(rad/s)': motor_data.get('velocity', 0.0),
                                '扭矩(Nm)': motor_data.get('torque', 0.0),
                                '温度(℃)': motor_data.get('temperature', 0),
                                '扭矩仪(Nm)': motor_data.get('torque_meter', 0.0),
                                '使能': 1 if enable else 0,
                                '运行': 1 if run else 0
                            }
                            records.append(record)
                            
                            # 每100条记录输出一次进度
                            if len(records) % 100 == 0:
                                elapsed = current_time - start_time
                                ctx.log_info(f"已记录 {len(records)} 条数据 ({elapsed:.1f}秒)")
                            
                            last_record_time = current_time
                            
                    except Exception as e:
                        ctx.log_warning(f"读取数据异常: {e}")
                
                # 短暂休眠，避免CPU占用过高
                time.sleep(min(interval_sec / 10, 0.001))
            
            # 保存到CSV文件
            if records:
                with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=records[0].keys())
                    writer.writeheader()
                    writer.writerows(records)
                
                ctx.log_info(f"✓ 数据记录完成: {len(records)} 条数据已保存到 {output_path}")
                
                return StepResult(
                    passed=True,
                    message=f"数据记录完成: {len(records)} 条数据",
                    data={
                        "record_count": len(records),
                        "duration": duration,
                        "interval_ms": interval_ms,
                        "output_file": str(output_file),
                        "sn": sn
                    }
                )
            else:
                return StepResult(
                    passed=False,
                    message="未记录到任何数据",
                    error="数据记录失败",
                    error_code="MODBUS_ERR_NO_DATA"
                )
                
        except Exception as e:
            ctx.log_error(f"记录数据异常: {e}")
            import traceback
            ctx.log_error(f"异常堆栈: {traceback.format_exc()}")
            return StepResult(
                passed=False,
                message=f"记录数据异常: {e}",
                error=str(e),
                error_code="MODBUS_ERR_RECORD_EXCEPTION"
            )
    
    def _parse_motor_data(self, registers):
        """解析电机数据"""
        try:
            data = {}
            # 处理前3个参数：角度、角速度、扭矩（都放大10倍）
            for i, key in enumerate(['angle', 'velocity', 'torque']):
                if i < len(registers):
                    raw = registers[i]
                    # 转换为带符号整数
                    if raw > 32767:
                        raw = raw - 65536
                    # 所有值都放大10倍，需要除以10
                    data[key] = round(raw / 10.0, 2)
                else:
                    data[key] = 0.0
            
            # 处理温度（第4个参数，地址40104，不放大10倍，不要小数）
            if len(registers) > 3:
                raw = registers[3]
                if raw > 32767:
                    raw = raw - 65536
                data['temperature'] = int(raw)  # 温度不放大10倍，不要小数
            else:
                data['temperature'] = 0
            
            # 处理扭矩仪（第5个参数，地址40105，放大10倍，保留1位小数）
            if len(registers) > 4:
                raw = registers[4]
                if raw > 32767:
                    raw = raw - 65536
                data['torque_meter'] = round(raw / 10.0, 1)  # 扭矩仪放大10倍，保留1位小数
            else:
                data['torque_meter'] = 0.0
            
            return data
        except:
            return {'angle': 0.0, 'velocity': 0.0, 'torque': 0.0, 'temperature': 0, 'torque_meter': 0.0}
    
    def _resolve_str_param(self, value: Any, ctx: Context) -> str:
        """解析字符串参数并进行变量替换"""
        if isinstance(value, str):
            return self._replace_variables(value, ctx)
        return str(value)
    
    def _replace_variables(self, text: str, ctx: Context) -> str:
        """替换文本中的变量引用"""
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace_var(match):
            var_name = match.group(1)
            if var_name == "sn":
                value = ctx.get_sn()
                ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                return value
            elif var_name == "port":
                return ctx.port
            else:
                value = ctx.get_data(var_name, "")
                if value:
                    ctx.log_info(f"替换变量 ${{{var_name}}} = {value}")
                    return str(value)
                else:
                    ctx.log_warning(f"未找到变量: ${{{var_name}}}")
                    return match.group(0)
        
        return re.sub(pattern, replace_var, text)


class ModbusDisconnectStep(BaseStep):
    """Modbus断开连接步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        断开Modbus连接
        """
        try:
            # 获取Modbus客户端
            client = ctx.get_comm_driver("modbus")
            
            if not client:
                ctx.log_info("当前未连接到Modbus")
                return StepResult(
                    passed=True,
                    message="当前未连接到Modbus，无需断开",
                    data={"disconnected": True}
                )
            
            # 断开连接
            client.close()
            
            # 清理状态
            ctx.remove_comm_driver("modbus")
            ctx.set_state("modbus_connected", False)
            ctx.remove_state("modbus_ip")
            ctx.remove_state("modbus_port")
            
            ctx.log_info("Modbus TCP连接已断开")
            
            return StepResult(
                passed=True,
                message="Modbus断开连接成功",
                data={"disconnected": True}
            )
            
        except Exception as e:
            ctx.log_error(f"断开连接异常: {e}")
            # 即使出错也清理状态
            ctx.remove_comm_driver("modbus")
            ctx.set_state("modbus_connected", False)
            return StepResult(
                passed=True,  # 断开连接失败不算测试失败
                message=f"Modbus断开连接完成（可能有异常）",
                data={"disconnected": True}
            )

