import sys
import math
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from PCANBasic import *
import serial.tools.list_ports
from pymodbus.client.serial import ModbusSerialClient
from pymodbus.exceptions import ModbusException
import re

# 全局常量（不变）
PI = math.pi
ANGLE_MIN = -4 * PI
ANGLE_MAX = 4 * PI
SPEED_MIN = -44.0
SPEED_MAX = 44.0
TORQUE_MIN = -17.0
TORQUE_MAX = 17.0
KP_MIN = 0.0
KP_MAX = 500.0
KD_MIN = 0.0
KD_MAX = 5.0
PROTOCOL_MAX = 65535  # 协议值范围0-65535
TIMEOUT = 0.1  # 100ms超时

# 固件刷写相关常量
FLASH_ERASE_CMD = 0x01  # Flash擦除命令
FILE_INFO_CMD = 0x02    # 文件信息命令
FILE_DATA_CMD = 0x03    # 文件数据命令
OTA_END_CMD = 0x04      # OTA结束命令

# 超时设置
FLASH_ERASE_TIMEOUT = 3.0  # 3秒
FILE_INFO_TIMEOUT = 3.0    # 3秒
FILE_DATA_TIMEOUT = 1.0    # 1秒
OTA_END_TIMEOUT = 3.0      # 3秒

# 响应类型
RESPONSE_SUCCESS = 0x00
RESPONSE_ERROR = 0x01
RESPONSE_TIMEOUT = 0x02

# 参数地址（不变）
ADDR_KP = 0x1005
ADDR_KD = 0x1006
ADDR_VERSION = 0x1004

# 固件刷写相关地址
ADDR_FLASH_OP = 0x2001  # Flash操作地址

# 全局队列（不变）
data_queue = queue.Queue(maxsize=100)
response_queue = queue.Queue(maxsize=10)
motor_queue = queue.Queue(maxsize=20)
self_check_queue = queue.Queue(maxsize=500)

class CANCommunicator:
    """CAN通信封装类（仅修改搜索帧ID和版本号解析）"""
    def __init__(self):
        self.pcan = PCANBasic()
        self.channel = PCAN_USBBUS1
        self.is_fd = False
        self.bitrate = PCAN_BAUD_1M  # 已修复为1M波特率
        self.initialized = False
        self.receive_thread = None
        self.running = False
        self.discovered_motors = []
        self.current_motor_id = None
        self.current_unique_id = None
        
        self.response_received_flag = False
        self.response_lock = threading.Lock()

    def init_can(self):
        """初始化CAN总线（不变）"""
        try:
            sts = self.pcan.Initialize(self.channel, self.bitrate)
            if sts == PCAN_ERROR_OK:
                self.initialized = True
                self.running = True
                self.receive_thread = threading.Thread(target=self.receive_loop)
                self.receive_thread.daemon = True
                self.receive_thread.start()
                return True
            else:
                err_msg = self.pcan.GetErrorText(sts, 0x09)[1].decode('utf-8')
                response_queue.put(("error", f"CAN总线初始化失败：{err_msg}"))
                return False
        except Exception as e:
            response_queue.put(("error", f"CAN库加载失败：{str(e)}"))
            return False

    def receive_loop(self):
        """接收报文循环（增强版）：添加终止检测、超时控制和资源清理"""
        print("CAN接收线程已启动")
        
        while self.running and self.initialized:
            # 快速检查终止标志，确保线程可以立即响应终止请求
            if hasattr(self, 'termination_requested') and self.termination_requested:
                print("检测到终止请求，CAN接收线程正在退出...")
                break
            
            try:
                # 检测超时
                if hasattr(self, 'last_activity_time') and hasattr(self, 'max_inactivity_time'):
                    current_time = time.time()
                    if current_time - self.last_activity_time > self.max_inactivity_time:
                        print(f"警告: {self.max_inactivity_time}秒无CAN活动，可能存在连接问题")
                        self._handle_timeout()
                        self.last_activity_time = current_time
                
                sts, msg, timestamp = self.pcan.Read(self.channel)
                
                if sts == PCAN_ERROR_OK:
                    # 更新活动时间
                    if hasattr(self, 'last_activity_time'):
                        self.last_activity_time = time.time()
                    
                    # 添加超时保护的消息解析
                    parse_start_time = time.time()
                    self.parse_message(msg)
                    parse_time = time.time() - parse_start_time
                    
                    if parse_time > 0.01:  # 10ms
                        print(f"警告: 消息解析时间过长: {parse_time:.3f}秒")
                elif sts != PCAN_ERROR_QRCVEMPTY:
                    try:
                        err_msg = self.pcan.GetErrorText(sts, 0x09)[1].decode('utf-8')
                        print(f"接收错误：{err_msg}")
                    except Exception:
                        print(f"接收错误：{sts}")
                
                # 短暂休眠以让出CPU时间片，防止CPU占用过高
                #if
                time.sleep(0.000001)
                
            except Exception as e:
                print(f"接收线程异常：{str(e)}")
                # 异常情况下增加休眠，避免CPU占用过高
                #time.sleep(0.001)
        
        # 确保在退出时清理资源
        self._cleanup_on_exit()
        print("CAN接收线程已安全退出")

    def parse_message(self, msg):
        """解析CAN报文（修改版本号解析格式）"""
        is_extended = (msg.MSGTYPE & PCAN_MESSAGE_EXTENDED.value) != 0
        if is_extended:
            # 解析29位ID，兼容新协议格式
            func_code = (msg.ID >> 16) & 0xFF  # 功能码
            
            # 特殊处理功能码为10、11、12和13的情况（flash操作相关）
            if func_code in [10, 11, 12, 13]:
                dir_bit = (msg.ID >> 24) & 0x1  # 方向位在28位
                motor_id = (msg.ID >> 8) & 0xFF  # 电机ID在15-8位
                sub_id = msg.ID & 0xFF  # 子ID在7-0位（用于表示成功/失败）
            else:
                # 兼容原有格式
                dir_bit = (msg.ID >> 24) & 0x1F
                motor_id = (msg.ID >> 8) & 0xFF
                sub_id = msg.ID & 0xFF
        else:
            dir_bit = (msg.ID >> 8) & 0x07
            func_code = 0
            motor_id = msg.ID & 0xFF
            sub_id = 0

        # 1. 设备发现应答（不变）
        if is_extended and dir_bit == 0x01 and func_code == 0x00:
            unique_id = ''.join(f"{byte:02X}" for byte in msg.DATA[:8])
            if (motor_id, unique_id) not in self.discovered_motors:
                self.discovered_motors.append((motor_id, unique_id))
                motor_queue.put(("discover", motor_id, unique_id))
        
        # 2. 状态反馈（不变）
        elif is_extended and dir_bit == 0x01 and func_code == 0x01:
            if motor_id == self.current_motor_id:
                feedback_data = {
                    'angle': self.protocol_to_actual(msg.DATA[0]  | msg.DATA[1]<< 8, ANGLE_MIN, ANGLE_MAX),
                    'speed': self.protocol_to_actual(msg.DATA[2]  | msg.DATA[3]<< 8, SPEED_MIN, SPEED_MAX),
                    'torque': self.protocol_to_actual(msg.DATA[4]  | msg.DATA[5]<< 8, TORQUE_MIN, TORQUE_MAX),
                    'temperature': msg.DATA[6] - 40,
                    'status': msg.DATA[7],
                    'fault': sub_id 
                }
                try:
                    data_queue.put_nowait(feedback_data)
                except queue.Full:
                    pass
        
        # 3. 操作应答（修改版本号解析）
        elif is_extended and dir_bit == 0x01:
            if motor_id == self.current_motor_id:
                # 3.1 Flash操作响应（功能码为10、11、12或13）
                if func_code in [10, 11, 12, 13]:
                    # 设置响应标志，通知发送命令的方法已收到响应
                    if (sub_id == 0x00):
                        with self.response_lock:
                            self.response_received_flag = True
                # 3.2 普通操作应答（增加零位设置处理）
                elif func_code in [0x04, 0x05, 0x06, 0x08, 0x03, 0x09, 0x07]:
                    success = (sub_id == 0x00)
                    msg_map = {
                        0x04: "使能", 0x05: "禁能", 0x06: "清除故障",
                        0x08: "ID设置", 0x03: "参数写入", 0x09: "自动上报设置",
                        0x07: "零位设置"
                    }
                    tip = f"{msg_map.get(func_code, '操作')}{'成功' if success else '失败'}"
                    response_queue.put(("response", success, tip))
                    
                    with self.response_lock:
                        self.response_received_flag = True
                
                # 3.2 参数读取应答（修改版本号解析格式）
                elif func_code == 0x02:
                    param_addr = (msg.DATA[3] << 24) | (msg.DATA[2] << 16) | (msg.DATA[1] << 8) | msg.DATA[0]
                    param_data = bytes(msg.DATA[4:8])  # 后4字节为版本号数据（4个数字）
                    
                    # 版本号解析：按a.b.c.d格式显示（4个字节分别对应a、b、c、d）
                    if param_addr == ADDR_VERSION:
                        if len(param_data) >= 4:
                            # 提取4个字节的数值（0-255范围）
                            a = param_data[0]
                            b = param_data[1]
                            c = param_data[2]
                            d = param_data[3]
                            version_str = f"{a}.{b}.{c}.{d}"  # 格式化为a.b.c.d
                            response_queue.put(("version", version_str))
                    
                    # KP/KD解析（不变）
                    elif param_addr == ADDR_KP:
                        kp_val = self.bytes_to_float(param_data)
                        response_queue.put(("kp", kp_val))
                    
                    elif param_addr == ADDR_KD:
                        kd_val = self.bytes_to_float(param_data)
                        response_queue.put(("kd", kd_val))
                    
                    with self.response_lock:
                        self.response_received_flag = True
        #4. 标定上传函数
        elif is_extended and dir_bit == 0x1c:
            istest = 0
            endmsg = 0
            if msg.DATA[0] == 1:
                if msg.DATA[1] == 2:
                    if msg.DATA[2] == 3:
                        if msg.DATA[3] == 4:
                            if msg.DATA[4] == 5:
                                if msg.DATA[5] == 6:
                                    if msg.DATA[6] == 7:
                                        if msg.DATA[7] == 8:
                                            endmsg = 1
            if func_code == 1:
                istest = 1
            param_data = bytes(msg.DATA[0:4])
            eleang = self.bytes_to_float(param_data)
            # 转换为uint16_t类型
            motang = msg.DATA[4] |  msg.DATA[5]<< 8  # 直接获取单个字节的值
            secangle = msg.DATA[6]  |  msg.DATA[7]<< 8 # 直接获取单个字节的值
            self.calibdata_update_callback(eleang, motang, secangle, endmsg, istest)
        elif is_extended and dir_bit == 0x1d:
            istest = 0
            endmsg = 0
            if msg.DATA[0] == 1:
                if msg.DATA[1] == 2:
                    if msg.DATA[2] == 3:
                        if msg.DATA[3] == 4:
                            if msg.DATA[4] == 5:
                                if msg.DATA[5] == 6:
                                    if msg.DATA[6] == 7:
                                        if msg.DATA[7] == 8:
                                            endmsg = 1
            if func_code == 1:
                istest = 1
            param_data = bytes(msg.DATA[0:4])
            eleang = self.bytes_to_float(param_data)
            param_data2 = bytes(msg.DATA[4:8])
            eleang2 = self.bytes_to_float(param_data2)

            self.mech_calibdata_update_callback(eleang, eleang2,endmsg, istest)
        
        # 5. 自检数据接收 - 电流数据 (0x1F+1+电机ID+0格式)
        elif is_extended and dir_bit == 0x1F and func_code == 0x01 and sub_id == 0x00:
            if motor_id == self.current_motor_id:
                # 解析电流ABC数据
                self_check_current_data = {
                    'current_a': msg.DATA[0] | msg.DATA[1] << 8,  # 16位无符号数
                    'current_b': msg.DATA[2] | msg.DATA[3] << 8,  # 16位无符号数
                    'current_c': msg.DATA[4] | msg.DATA[5] << 8,  # 16位无符号数
                    'main_angle': None,  # 角度数据来自另一条消息
                    'sub_angle': None   # 角度数据来自另一条消息
                }
                try:
                    self_check_queue.put_nowait(self_check_current_data)
                except queue.Full:
                    pass
        
        # 6. 自检数据接收 - 编码角度数据 (0x1E+25+电机ID+0格式)
        elif is_extended and dir_bit == 0x1E and func_code == 0x19 and sub_id == 0x00:
            if motor_id == self.current_motor_id:
                # 解析副编码角度和主编码角度数据
                self_check_angle_data = {
                    'current_a': None,  # 电流数据来自另一条消息
                    'current_b': None,  # 电流数据来自另一条消息
                    'current_c': None,  # 电流数据来自另一条消息
                    'sub_angle': msg.DATA[0] | msg.DATA[1] << 8,   # 16位无符号数
                    'main_angle': msg.DATA[2] | msg.DATA[3] << 8   # 16位无符号数
                }
                try:
                    self_check_queue.put_nowait(self_check_angle_data)
                except queue.Full:
                    pass
        elif is_extended and dir_bit == 0x1E and func_code == 0x19 and sub_id == 0x00:
            if motor_id == self.current_motor_id:
                # 解析副编码角度和主编码角度数据
                self_check_angle_data = {
                    'current_a': None,  # 电流数据来自另一条消息
                    'current_b': None,  # 电流数据来自另一条消息
                    'current_c': None,  # 电流数据来自另一条消息
                    'sub_angle': msg.DATA[0] | msg.DATA[1] << 8,   # 16位无符号数
                    'main_angle': msg.DATA[2] | msg.DATA[3] << 8   # 16位无符号数
                }
                try:
                    self_check_queue.put_nowait(self_check_angle_data)
                except queue.Full:
                    pass
            
    def search_motors(self):
        """搜索电机（修改：按要求设置扩展帧ID格式）"""
        if not self.initialized:
            if not self.init_can():
                return
        
        # 清除之前发现的电机列表
        self.discovered_motors.clear()
        
        # 批量处理CAN消息发送，减少循环中的延迟
        batch_size = 10  # 每批处理10个ID
        
        for batch_start in range(1, 128, batch_size):
            batch_end = min(batch_start + batch_size - 1, 127)
            
            for can_id in range(batch_start, batch_end + 1):
                try:
                    msg = TPCANMsg()
                    msg.ID = (0x00 << 24) | (0x00 << 16) | (can_id)  # 仅保留ID的低16位
                    msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value  # 扩展帧
                    msg.LEN = 8
                    msg.DATA = (c_ubyte * 8)(*[0x00]*8)
                    
                    # 发送消息，捕获可能的异常
                    self.pcan.Write(self.channel, msg)
                except Exception:
                    # 静默处理发送错误
                    pass
            
            # 批次间使用更短的延迟
            if batch_end < 127:
                time.sleep(0.002)  # 减少为2ms

    # 以下所有方法（set_motor_id、send_mpc_command等）均不变
    def set_motor_id(self, new_id):
        if not self.current_motor_id or new_id < 1 or new_id > 127:
            response_queue.put(("error", "请选择电机并输入1-127之间的ID"))
            return
        with self.response_lock:
            self.response_received_flag = False
        msg = TPCANMsg()
        msg.ID = (0x00 << 24) | (0x08 << 16) | (0x00 << 8) | self.current_motor_id
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        msg.DATA = (c_ubyte * 8)(new_id, *[0x00]*7)
        self.pcan.Write(self.channel, msg)
        # 非阻塞等待响应
        self.wait_for_response()

    def send_mpc_command(self, angle, speed, torque):
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return
        proto_angle = self.actual_to_protocol(angle, ANGLE_MIN, ANGLE_MAX)
        proto_speed = self.actual_to_protocol(speed, SPEED_MIN, SPEED_MAX)
        proto_torque = self.actual_to_protocol(torque, TORQUE_MIN, TORQUE_MAX)
        msg = TPCANMsg()
        msg.ID = (0x02 << 8) | self.current_motor_id
        msg.MSGTYPE = PCAN_MESSAGE_STANDARD.value
        msg.LEN = 6
        msg.DATA = (c_ubyte * 8)(
            (proto_angle ) & 0xFF, (proto_angle >> 8) & 0xFF,
            (proto_speed ) & 0xFF, (proto_speed >> 8) & 0xFF,
            (proto_torque ) & 0xFF, (proto_torque >> 8) & 0xFF,
            0x00, 0x00
        )
        self.pcan.Write(self.channel, msg)
        
    def send_multi_motor_command(self, angle1, angle2, angle3):
        """发送11位标准帧控制三台电机
        angle1: 髋关节目标角度（-4pi到4pi）
        angle2: 大腿关节目标角度（-4pi到4pi）
        angle3: 小腿关节目标角度（-4pi到4pi）
        """
        # 将角度值转换为协议值（0-65535）
        proto_angle1 = self.actual_to_protocol(angle1, ANGLE_MIN, ANGLE_MAX)
        proto_angle2 = self.actual_to_protocol(angle2, ANGLE_MIN, ANGLE_MAX)
        proto_angle3 = self.actual_to_protocol(angle3, ANGLE_MIN, ANGLE_MAX)
        
        # 创建CAN消息
        msg = TPCANMsg()
        msg.ID = 0x3  # 11位ID，最低位方向位为0x3（运控模式报文）
        msg.MSGTYPE = PCAN_MESSAGE_STANDARD.value
        msg.LEN = 6  # 6字节数据
        
        # 填充数据，每个角度占2字节
        msg.DATA = (c_ubyte * 8)(
            (proto_angle1) & 0xFF, (proto_angle1 >> 8) & 0xFF,  # 髋关节角度
            (proto_angle2) & 0xFF, (proto_angle2 >> 8) & 0xFF,  # 大腿关节角度
            (proto_angle3) & 0xFF, (proto_angle3 >> 8) & 0xFF,  # 小腿关节角度
            0x00, 0x00  # 填充字节
        )
        
        # 发送消息
        self.pcan.Write(self.channel, msg)

    def set_kp_kd(self, kp, kd):
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return
        with self.response_lock:
            self.response_received_flag = False
        kp_bytes = self.float_to_bytes(kp)
        kd_bytes = self.float_to_bytes(kd)
        self.send_param_write(ADDR_KP, kp_bytes)
        # 减少延迟时间
        time.sleep(0.01)
        self.send_param_write(ADDR_KD, kd_bytes)
        # 非阻塞等待响应
        self.wait_for_response()

    def read_kp_kd(self):
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return
        with self.response_lock:
            self.response_received_flag = False
        self.send_param_read(ADDR_KP)
        # 减少延迟时间
        time.sleep(0.01)
        self.send_param_read(ADDR_KD)
        # 非阻塞等待响应
        self.wait_for_response()

    def read_version(self):
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return
        with self.response_lock:
            self.response_received_flag = False
        self.send_param_read(ADDR_VERSION)
        # 非阻塞等待响应
        self.wait_for_response()

    def enable_motor(self, mode=1):
        """启用电机
        mode: 1=运控, 3=自检, 4=速度, 5=编码器标定
        """
        if not self.current_motor_id:
            return False, "请先选择要控制的电机"
        
        with self.response_lock:
            self.response_received_flag = False
        
        try:
            msg = TPCANMsg()
            msg.ID = (0x00 << 24) | (0x04 << 16) | (0x00 << 8) | self.current_motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            msg.DATA = (c_ubyte * 8)(mode, *[0x00]*7)
            
            if not self.initialized:
                return False, "CAN未初始化"
            
            write_sts = self.pcan.Write(self.channel, msg)
            if write_sts != PCAN_ERROR_OK:
                err_msg = self.pcan.GetErrorText(write_sts, 0x09)[1].decode('utf-8')
                return False, f"发送使能命令失败: {err_msg}"
            
            # 等待响应
            success = self.wait_for_response()
            return success, None
        except Exception as e:
            return False, str(e)

    def disable_motor(self):
        """禁用电机"""
        if not self.current_motor_id:
            return False, "请先选择要控制的电机"
        
        with self.response_lock:
            self.response_received_flag = False
        
        try:
            msg = TPCANMsg()
            msg.ID = (0x00 << 24) | (0x05 << 16) | (0x00 << 8) | self.current_motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            msg.DATA = (c_ubyte * 8)(*[0x00]*8)
            
            if not self.initialized:
                return False, "CAN未初始化"
            
            write_sts = self.pcan.Write(self.channel, msg)
            if write_sts != PCAN_ERROR_OK:
                err_msg = self.pcan.GetErrorText(write_sts, 0x09)[1].decode('utf-8')
                return False, f"发送禁能命令失败: {err_msg}"
            
            # 等待响应
            success = self.wait_for_response()
            return success, None
        except Exception as e:
            return False, str(e)

    def clear_fault(self):
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return
        with self.response_lock:
            self.response_received_flag = False
        msg = TPCANMsg()
        msg.ID = (0x00 << 24) | (0x06 << 16) | (0x00 << 8) | self.current_motor_id
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8

        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            response_queue.put(("error", f"清故障失败: {result}"))
            return
            
        # 等待响应
        self.wait_for_response()
        # 响应已通过parse_message方法处理并放入队列，这里不需要再次处理
        
    def toggle_auto_report(self, enable, frequency, motor_id):
        """实现自动上报功能的开关控制
        
        Args:
            enable: 是否启用自动上报（True/False）
            frequency: 上报频率（0-1500Hz）
            motor_id: 电机ID
        """
        # 验证电机ID
        if not motor_id:
            response_queue.put(("error", "无效的电机ID"))
            return
            
        # 保存当前电机ID
        self.current_motor_id = motor_id
        
        # 准备命令数据
        # byte0: 0-关闭, 1-开启
        # byte1-2: 上报频率（高位在前）
        enable_byte = 1 if enable else 0
        freq_high_byte = (frequency >> 8) & 0xFF
        freq_low_byte = frequency & 0xFF
        
        # 重置响应标志
        with self.response_lock:
            self.response_received_flag = False
        
        # 构建CAN消息
        msg = TPCANMsg()
        # 29位ID: 方向位(0为下行) + 功能码(0x09) + 0x00 + 电机ID
        msg.ID = (0x00 << 24) | (0x09 << 16) | (0x00 << 8) | motor_id
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        
        # 设置数据字节
        msg.DATA = (c_ubyte * 8)()
        msg.DATA[0] = enable_byte
        msg.DATA[1] = freq_low_byte
        msg.DATA[2] = freq_high_byte
        # 剩余字节填充0
        for i in range(3, 8):
            msg.DATA[i] = 0
            
        # 发送消息
        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            response_queue.put(("error", f"发送自动上报命令失败: {result}"))
            return
            
        # 等待响应
        self.wait_for_response()
        # 响应已通过parse_message方法处理并放入队列，这里不需要再次处理
    
    def set_zero_offset(self, offset, motor_id):
        """设置零位偏置（新增）
        
        Args:
            offset: 零位偏置值（浮点型角度值）
            motor_id: 电机ID
        """
        # 验证电机ID
        if not motor_id:
            response_queue.put(("error", "无效的电机ID"))
            return
            
        # 保存当前电机ID
        self.current_motor_id = motor_id
        
        # 重置响应标志
        with self.response_lock:
            self.response_received_flag = False
        
        # 构建CAN消息
        msg = TPCANMsg()
        # 29位ID: 方向位(0为下行) + 功能码(0x07) + 0x00 + 电机ID
        msg.ID = (0x00 << 24) | (0x07 << 16) | (0x00 << 8) | motor_id
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        
        # 将浮点数转换为字节数组（4字节小端序）
        import struct
        offset_bytes = struct.pack('<f', offset)
        
        # 设置数据字节
        msg.DATA = (c_ubyte * 8)()
        for i in range(4):
            msg.DATA[i] = offset_bytes[i]
        # 剩余字节填充0
        for i in range(4, 8):
            msg.DATA[i] = 0
            
        # 发送消息
        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            response_queue.put(("error", f"发送零位设置命令失败: {result}"))
            return
            
        # 等待响应
        self.wait_for_response()
        # 响应已通过parse_message方法处理并放入队列，这里不需要再次处理
    
    def send_flash_erase(self):
        """发送Flash擦除命令"""
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return False
        
        with self.response_lock:
            self.response_received_flag = False
        
        msg = TPCANMsg()
        # 按照协议规范构建29位标准帧ID：
        # 28-24位: 方向位(0为下行)
        # 23-16位: 功能码(10)
        # 15-8位: 保留
        # 7-0位: 电机ID
        msg.ID = (0 << 24) | (10 << 16) | (self.current_motor_id & 0xFF)
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        # 协议中数据部分全为0
        msg.DATA = (c_ubyte * 8)(*[0x00]*8)
        
        # 发送命令
        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            print(f"Flash擦除命令发送失败: {result}")
            return False
        
        # 使用自定义超时等待响应
        start_time = time.time()
        while time.time() - start_time < FLASH_ERASE_TIMEOUT:
            if self.response_received_flag:
                # 检查响应内容
                # 注意：这里可能需要根据实际的响应格式进行调整
                return True
            time.sleep(0.05)
        
        print("Flash擦除响应超时")
        return False
    
    def send_file_info(self, file_size, package_count):
        """发送文件信息命令"""
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return False
        
        with self.response_lock:
            self.response_received_flag = False
        
        msg = TPCANMsg()
        # 按照协议规范构建29位标准帧ID：方向位(0表示发送) + 命令码(11) + 电机ID
        # 格式：28-24位为方向位(0)，23-16位为功能码(11)，7-0位为电机ID
        msg.ID = (0 << 24) | (11 << 16) | (self.current_motor_id & 0xFF)
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        
        # 按照协议规范准备数据：
        # Byte0~Byte3: 数据包字节数
        # Byte4~Byte7: 包个数
        data = []
        # 添加文件大小（4字节，小端序）
        data.extend([(file_size >> i*8) & 0xFF for i in range(4)])
        # 添加包数量（4字节，小端序）
        data.extend([(package_count >> i*8) & 0xFF for i in range(4)])
        
        msg.DATA = (c_ubyte * 8)(*data)
        
        # 发送命令
        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            print(f"文件信息命令发送失败: {result}")
            return False
        
        # 等待响应
        start_time = time.time()
        while time.time() - start_time < FILE_INFO_TIMEOUT:
            if self.response_received_flag:
                return True
            #time.sleep(0.05)
        
        print("文件信息响应超时")
        return False
    
    def send_file_data(self, package_index, data_bytes):
        """发送文件数据命令"""
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return False
        
        with self.response_lock:
            self.response_received_flag = False
        
        msg = TPCANMsg()
        # 按照协议规范构建29位标准帧ID：
        # 28-24位：方向位为12
        # 23-16位：升级包当前位置
        # 7-0位：电机ID
        msg.ID = (12 << 24) | ((package_index & 0xFFFF) << 8) | (self.current_motor_id & 0xFF)
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        
        # 按照协议规范准备数据：直接使用数据字节（最多8字节）
        data = []
        # 添加数据字节
        data.extend(data_bytes[:8])
        # 填充剩余字节
        while len(data) < 8:
            data.append(0x00)
        
        msg.DATA = (c_ubyte * 8)(*data)
        
        # 发送命令
        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            print(f"文件数据命令发送失败: {result}")
            return False
        
        # 等待响应
        start_time = time.time()
        while time.time() - start_time < FILE_DATA_TIMEOUT:
            if self.response_received_flag:
                return True
            #time.sleep(0.05)
        
        print("文件数据响应超时")
        return False
    
    def send_ota_end(self):
        """发送OTA结束命令（功能码13）"""
        if not self.current_motor_id:
            response_queue.put(("error", "请先选择要控制的电机"))
            return False
        
        with self.response_lock:
            self.response_received_flag = False
        
        msg = TPCANMsg()
        # 按照协议规范构建29位ID：方向位(0) + 功能码(13) + 电机ID
        msg.ID = (0x00 << 24) | (13 << 16) | (self.current_motor_id & 0xFF)
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        # 8字节数据全部填充为0
        msg.DATA = (c_ubyte * 8)(*[0x00]*8)
        
        # 发送命令
        result = self.pcan.Write(self.channel, msg)
        if result != PCAN_ERROR_OK:
            print(f"OTA结束命令发送失败: {result}")
            return False
        
        # 等待响应
        start_time = time.time()
        while time.time() - start_time < OTA_END_TIMEOUT:
            if self.response_received_flag:
                return True
            time.sleep(0.05)
        
        print("OTA结束响应超时")
        return False

    def send_param_write(self, addr, data):
        msg = TPCANMsg()
        msg.ID = (0x00 << 24) | (0x03 << 16) | (0x00 << 8) | self.current_motor_id
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        msg.DATA = (c_ubyte * 8)(
            (addr ) & 0xFF, (addr >> 8) & 0xFF,
            (addr >> 16) & 0xFF, (addr >> 24) & 0xFF,
            data[0], data[1], data[2], data[3]
        )
        self.pcan.Write(self.channel, msg)
        # 添加5ms延时，确保标定过程中参数写入稳定
        time.sleep(0.005)

    def send_param_read(self, addr):
        msg = TPCANMsg()
        msg.ID = (0x00 << 24) | (0x02 << 16) | (0x00 << 8) | self.current_motor_id
        msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
        msg.LEN = 8
        msg.DATA = (c_ubyte * 8)(
            (addr ) & 0xFF, (addr >> 8) & 0xFF,
            (addr >> 16) & 0xFF, (addr >> 24) & 0xFF,
            0x00, 0x00, 0x00, 0x00
        )
        self.pcan.Write(self.channel, msg)

    def wait_for_response(self):
        # 使用非阻塞方式检查响应，避免GUI卡死
        start_time = time.time()
        max_checks = 10  # 最多检查10次
        check_interval = 0.005  # 每次检查间隔5ms
        
        for _ in range(max_checks):
            # 检查是否需要终止
            if hasattr(self, 'termination_requested') and self.termination_requested:
                return False
            
            with self.response_lock:
                if self.response_received_flag:
                    return True
            time.sleep(check_interval)
        
        # 记录超时信息
        elapsed_time = time.time() - start_time
        print(f"响应超时，等待时间: {elapsed_time:.3f}秒")
        
        # 不阻塞等待，而是在后台继续处理
        # 让GUI保持响应性
        return False

    @staticmethod
    def actual_to_protocol(actual_val, min_val, max_val):
        return int((actual_val - min_val) / (max_val - min_val) * PROTOCOL_MAX)

    @staticmethod
    def protocol_to_actual(proto_val, min_val, max_val):
        return (proto_val / PROTOCOL_MAX) * (max_val - min_val) + min_val

    @staticmethod
    def float_to_bytes(f):
        import struct
        return struct.pack('<f', f)

    @staticmethod
    def bytes_to_float(bytes_data):
        import struct
        return struct.unpack('<f', bytes_data)[0]
    
    def terminate(self):
        """安全终止CAN通信器的所有线程和资源"""
        print("开始安全终止CAN通信...")
        
        # 设置终止标志
        self.termination_requested = True
        self.running = False
        
        # 等待接收线程结束（最多2秒）
        if hasattr(self, 'receive_thread') and self.receive_thread.is_alive():
            print("等待接收线程结束...")
            self.receive_thread.join(timeout=2.0)
            if self.receive_thread.is_alive():
                print("警告: 接收线程未能在规定时间内结束")
        
        # 清理资源
        self._cleanup_on_exit()
        print("CAN通信已安全终止")
    
    def _handle_timeout(self):
        """处理CAN通信超时情况"""
        try:
            # 清除错误和队列
            while not data_queue.empty():
                try:
                    data_queue.get(block=False)
                except queue.Empty:
                    break
            
            while not self_check_queue.empty():
                try:
                    self_check_queue.get(block=False)
                except queue.Empty:
                    break
                    
            print("已清理数据队列以恢复正常通信")
        except Exception as e:
            print(f"处理超时异常: {e}")
    
    def safe_reset_can(self):
        """安全重置CAN通信"""
        try:
            print("开始安全重置CAN通信...")
            # 先取消初始化
            if hasattr(self, 'pcan') and hasattr(self, 'channel'):
                try:
                    self.pcan.Uninitialize(self.channel)
                    print("CAN通道已取消初始化")
                except Exception as e:
                    print(f"取消初始化异常: {e}")
                
                # 短暂暂停
                time.sleep(0.1)
            
            # 重新初始化
            self.initialized = False
            self.init_can()
            print("CAN通信重置完成")
        except Exception as e:
            print(f"安全重置失败: {e}")
    
    def _cleanup_on_exit(self):
        """程序退出时清理资源"""
        try:
            # 取消初始化CAN通道
            if hasattr(self, 'pcan') and hasattr(self, 'channel') and self.initialized:
                try:
                    self.pcan.Uninitialize(self.channel)
                    print("CAN通道已安全取消初始化")
                except Exception as e:
                    print(f"取消初始化CAN异常: {e}")
            
            # 设置标志
            self.initialized = False
            self.running = False
            
            # 清理队列（避免内存泄漏）
            queue_list = [data_queue, response_queue, motor_queue, self_check_queue]
            for q in queue_list:
                try:
                    while not q.empty():
                        q.get(block=False)
                except Exception:
                    pass
                    
        except Exception as e:
            print(f"清理资源异常: {e}")
        
    def calibdata_update_callback(self, eleangle, motorangle, secangle, endcalib, istest):
        """标定数据更新回调函数"""
        # 静态变量在Python中使用类变量或闭包实现
        if not hasattr(self, '_calib_data'):
            self._calib_data = {
                'datacnt': 0,
                'efilter': 0.0,
                'efilter_sum': 0.0,
                'efilter_sum_src': 0.0,
                'motorcr': 0.0,
                'elecr': 0.0,
                'seccr': 0.0,
                'motor_encoder_vec': [],
                'sec_encoder_vec': [],
                'error_table': [],
                'error_table_sec': [],
                'error_table_filter': [],
                'error_table_filter_sec': [],
                'error_table_out': [],
                'error_table_out_sec': [],
                'motor_encoder_vec_out': [],
                'sec_encoder_vec_out': [],
                'lastupdatetime': 0,
                'lastmot': 0.0,
                'lastele': 0.0,
                'lastsec': 0.0,
                'printflag': 1
            }
        
        cd = self._calib_data
        import time
        import math
        import struct
        
        # 计算当前时间戳（毫秒）
        thisupdatetime = int(time.time() * 1000)
        
        # 超过1秒重置数据
        if (thisupdatetime - cd['lastupdatetime']) > 1000:
            cd['efilter_sum'] = 0.0
            cd['efilter_sum_src'] = 0.0
            cd['datacnt'] = 0
            cd['motorcr'] = 0.0
            cd['seccr'] = 0.0
            cd['elecr'] = 0.0
            cd['motor_encoder_vec'] = []
            cd['error_table'] = []
            cd['error_table_filter'] = []
            cd['error_table_out'] = []
            cd['motor_encoder_vec_out'] = []
            cd['error_table_sec'] = []
            cd['sec_encoder_vec'] = []
            cd['error_table_filter_sec'] = []
            cd['error_table_out_sec'] = []
            cd['sec_encoder_vec_out'] = []
        
        cd['lastupdatetime'] = thisupdatetime
        
        if endcalib:
            # 标定结束处理
            if cd['datacnt'] > 0:
                cd['efilter_sum'] = cd['efilter_sum'] / (cd['datacnt'] + 1)
                cd['efilter_sum_src'] = cd['efilter_sum_src'] / (cd['datacnt'] + 1)
            
            cd['datacnt'] = 0
            cd['motorcr'] = 0.0
            cd['seccr'] = 0.0
            cd['elecr'] = 0.0
            cd['motor_encoder_vec_out'] = []
            cd['sec_encoder_vec_out'] = []
            cd['error_table_out'] = []
            cd['error_table_out_sec'] = []
            
            # 计算电角度偏移
            eleoffset = 14.0 * (math.pi * 2.0 * cd['efilter_sum'] / 16383.0)
            while eleoffset < -math.pi:
                eleoffset += math.pi * 2.0
            while eleoffset > math.pi:
                eleoffset -= math.pi * 2.0
            
            print(f"eleangle offset : {eleoffset}")
            
            # 主标定处理
            if len(cd['error_table']) > 1:
                for i in range((len(cd['error_table']) // 2) - 1):
                    cd['error_table'][i] = cd['error_table'][i] * 0.5 + cd['error_table'][len(cd['error_table']) - 1 - i] * 0.5
                
                lenthhalf = len(cd['error_table']) // 2
                while len(cd['error_table']) > lenthhalf:
                    cd['error_table'].pop()
                
                for i in range(lenthhalf):
                    searchidx = []
                    startidx = i - 500
                    endidx = i + 500
                    
                    for idx in range(startidx, endidx + 1):
                        idxset = idx
                        while idxset < 0:
                            idxset += lenthhalf
                        while idxset > (lenthhalf - 1):
                            idxset -= lenthhalf
                        searchidx.append(idxset)
                    
                    efilter = 0.0
                    for k in searchidx:
                        efilter += cd['error_table'][k]
                    efilter = efilter / len(searchidx)
                    cd['error_table_filter'].append(efilter - cd['efilter_sum'])
            
            # 次级标定处理
            if len(cd['error_table_sec']) > 1:
                for i in range((len(cd['error_table_sec']) // 2) - 1):
                    cd['error_table_sec'][i] = cd['error_table_sec'][i] * 0.5 + cd['error_table_sec'][len(cd['error_table_sec']) - 1 - i] * 0.5
                
                lenthhalf = len(cd['error_table_sec']) // 2
                while len(cd['error_table_sec']) > lenthhalf:
                    cd['error_table_sec'].pop()
                
                for i in range(lenthhalf):
                    searchidx = []
                    startidx = i - 200
                    endidx = i + 200
                    
                    for idx in range(startidx, endidx + 1):
                        idxset = idx
                        while idxset < 0:
                            idxset += lenthhalf
                        while idxset > (lenthhalf - 1):
                            idxset -= lenthhalf
                        searchidx.append(idxset)
                    
                    efilter = 0.0
                    for k in searchidx:
                        efilter += cd['error_table_sec'][k]
                    efilter = efilter / len(searchidx)
                    cd['error_table_filter_sec'].append(efilter - cd['efilter_sum_src'])
            
            # 生成电机编码器输出表
            for i in range(256):
                lowidx = i * 256 + 120
                highidx = i * 256 + 136
                for j in range(len(cd['motor_encoder_vec']) // 2 - 1):
                    if lowidx <= cd['motor_encoder_vec'][j] <= highidx:
                        cd['motor_encoder_vec_out'].append(cd['motor_encoder_vec'][j])
                        cd['error_table_out'].append(round(cd['error_table_filter'][j]))
                        break
            
            print("encoder cnt : ", end="")
            for a in cd['motor_encoder_vec_out']:
                # 编码器计数值保持为无符号整数，不进行符号转换
                print(f"{int(a)}, ", end="")
            print()
            
            # 生成次级编码器输出表
            for i in range(256):
                lowidx = i * 256 + 120
                highidx = i * 256 + 136
                for j in range(len(cd['sec_encoder_vec']) // 2 - 1):
                    if lowidx <= cd['sec_encoder_vec'][j] <= highidx:
                        cd['sec_encoder_vec_out'].append(cd['sec_encoder_vec'][j])
                        cd['error_table_out_sec'].append(round(0.1 * cd['error_table_filter_sec'][j]))
                        break
            
            # 写入标定数据，使用send_param_write替代writepara
            if istest == 0:
                # 写入标定标志
                addr =  34  # 假设地址格式为0x1000+index
                data = struct.pack('<I', 0x01)
                self.send_param_write(addr, data)
                
                # 写入电角度偏移
                addr =  1
                eleoffset = -eleoffset
                data = struct.pack('<f', eleoffset)
                self.send_param_write(addr, data)
            
            paracnt = 0
            paratablecnt = 0
            failcnt = 0
            
            print("calib num : ", end="")
            # 写入主标定表
            for a in cd['error_table_out']:
                # 错误值作为有符号8位数处理
                # 如果值超过127，则表示负数（补码表示）
                if a > 127:
                    signed_a = a - 256
                elif a < -128:
                    signed_a = a + 256
                else:
                    signed_a = a
                print(f"{signed_a}, ", end="")
                # 构建32位参数数据，每次打包4个字节
                if paracnt == 0:
                    param_data = bytearray(4)
                # 错误值作为有符号8位数处理
                # 如果值超过127，则表示负数（补码表示）
                if a > 127:
                    signed_a = a - 256
                elif a < -128:
                    signed_a = a + 256
                else:
                    signed_a = a
                # 保持有符号8位数的补码表示，使用与运算确保正确的字节值
                param_data[3 - paracnt] = signed_a & 0xFF  # 注意索引顺序
                paracnt += 1
                
                if paracnt >= 4:
                    addr =  36 + paratablecnt
                    if istest == 0:
                        self.send_param_write(addr, bytes(param_data))
                    paracnt = 0
                    paratablecnt += 1
                
                if abs(a) > 5:
                    failcnt += 1
            print()
            
            print("src encoder cnt : ", end="")
            for a in cd['sec_encoder_vec_out']:
                # 编码器计数值保持为无符号整数，不进行符号转换
                print(f"{int(a)}, ", end="")
            print()
            
            print("sec calib num : ", end="")
            # 写入次级标定表
            for a in cd['error_table_out_sec']:
                # 错误值作为有符号8位数处理
                # 如果值超过127，则表示负数（补码表示）
                if a > 127:
                    signed_a = a - 256
                elif a < -128:
                    signed_a = a + 256
                else:
                    signed_a = a
                print(f"{signed_a}, ", end="")
                # 构建32位参数数据，每次打包4个字节
                if paracnt == 0:
                    param_data = bytearray(4)
                # 保持有符号8位数的补码表示，使用与运算确保正确的字节值
                param_data[3 - paracnt] = signed_a & 0xFF  # 索引顺序与主标定表一致
                paracnt += 1
                
                if paracnt >= 4:
                    addr =  36 + paratablecnt
                    if istest == 0:
                        self.send_param_write(addr, bytes(param_data))
                    paracnt = 0
                    paratablecnt += 1
                
                if abs(a) > 5:
                    failcnt += 1
            print()
            
            # 测试模式处理
            if istest == 1:
                addr =  35  # 测试标志地址
                if failcnt < 20:
                    data = struct.pack('<I', 0x01)
                    self.send_param_write(addr, data)
                    print("calib test success")
                else:
                    data = struct.pack('<I', 0x00)
                    self.send_param_write(addr, data)
                    print("calib test fail")
            
            # 重置所有数据
            cd['efilter_sum'] = 0.0
            cd['efilter_sum_src'] = 0.0
            cd['motor_encoder_vec'] = []
            cd['error_table'] = []
            cd['motor_encoder_vec_out'] = []
            cd['error_table_out'] = []
            cd['error_table_filter'] = []
            cd['datacnt'] = 0
            cd['motorcr'] = 0.0
            cd['error_table_sec'] = []
            cd['sec_encoder_vec'] = []
            cd['error_table_filter_sec'] = []
            cd['error_table_out_sec'] = []
            cd['sec_encoder_vec_out'] = []
        else:
            # 处理标定数据收集
            # 计算编码器值
            eleangle_encoder = ((eleangle / 14.0) / (2.0 * math.pi)) * 16383
            while eleangle_encoder > 16383:
                eleangle_encoder -= 16384
            while eleangle_encoder < 0:
                eleangle_encoder += 16384
            
            motorangle_encoder = motorangle  # 直接使用传入的值
            
            # 添加到向量
            cd['motor_encoder_vec'].append(motorangle_encoder)
            cd['sec_encoder_vec'].append(secangle)
            
            # 计算变化量
            dmotor = motorangle_encoder - cd['lastmot']
            dele = eleangle_encoder - cd['lastele']
            dsec = secangle - cd['lastsec']
            
            # 更新last值
            cd['lastmot'] = motorangle_encoder
            cd['lastele'] = eleangle_encoder
            cd['lastsec'] = secangle
            
            # 处理环绕计数
            if dmotor > 8000:
                cd['motorcr'] -= 1.0
            if dmotor < -8000:
                cd['motorcr'] += 1.0
            
            if dele > 8000:
                cd['elecr'] -= 1.0
            if dele < -8000:
                cd['elecr'] += 1.0
            
            if dsec > 8000:
                cd['seccr'] -= 1.0
            if dsec < -8000:
                cd['seccr'] += 1.0
            
            # 非测试模式下的打印，每100次打印一次
            if istest == 0:
                if cd['printflag'] == 0:
                    print(f" {eleangle_encoder} ,  {motorangle_encoder},  {secangle}")
                cd['printflag'] += 1
                if cd['printflag'] >= 200:
                    cd['printflag'] = 0
            
            # 确保在范围内
            while eleangle_encoder > 16383:
                eleangle_encoder -= 16384
            while eleangle_encoder < 0:
                eleangle_encoder += 16384
            
            # 计算误差
            e = (eleangle_encoder + cd['elecr'] * 16384) - (motorangle_encoder + cd['motorcr'] * 16384)
            e_sec = (16384 - (eleangle_encoder + cd['elecr'] * 16384) * (32.0 / 31.0)) - (secangle + cd['seccr'] * 16384)
            
            if cd['datacnt'] == 0:
                cd['efilter'] = e
            
            # 累加误差
            cd['efilter_sum'] += e
            cd['efilter_sum_src'] += e_sec
            cd['error_table'].append(e)
            cd['error_table_sec'].append(e_sec)
        
        cd['datacnt'] += 1

    def mech_calibdata_update_callback(self, accangle, senseangle, endcalib, istest):
        """机械标定数据更新回调函数"""
        # 使用独立的数据结构，避免与电角度标定数据混淆
        if not hasattr(self, '_mech_calib_data'):
            self._mech_calib_data = {
                'datacnt': 0,
                'accangle_vec': [],
                'senseangle_vec': [],
                'lastupdatetime': 0,
                'last_accangle': 0.0,
                'last_senseangle': 0.0,
                'printflag': 1,
                'acc_edges': [],  # 存储accangle的下降沿索引
                'sense_edges': []  # 存储senseangle的下降沿索引
            }
        
        cd = self._mech_calib_data
        import time
        import math
        import struct
        
        # 计算当前时间戳（毫秒）
        thisupdatetime = int(time.time() * 1000)
        
        # 超过1秒重置数据
        if (thisupdatetime - cd['lastupdatetime']) > 1000:
            cd['datacnt'] = 0
            cd['accangle_vec'] = []
            cd['senseangle_vec'] = []
            cd['acc_edges'] = []
            cd['sense_edges'] = []
            cd['last_accangle'] = 0.0
            cd['last_senseangle'] = 0.0
        
        cd['lastupdatetime'] = thisupdatetime
        
        if endcalib == 1:
            # 标定结束处理
            if cd['datacnt'] > 0:
                # 检测跳变沿
                self.detect_falling_edges(cd)
                
                # 计算相位差
                phase_diff = -1.0*self.calculate_phase_difference(cd)
                
                if phase_diff is not None:
                    print(f"检测到的相位差: {phase_diff:.4f} rad")
                    
                    # 非测试模式下，将相位差写入地址87
                    if istest == 0:
                        # 将相位差转换为4字节数据
                        phase_bytes = struct.pack('<f', phase_diff)
                        param_data = bytearray(4)
                        for j in range(4):
                            param_data[j] = phase_bytes[j]
                        
                        # 写入参数
                        addr = 87
                        self.send_param_write(addr, bytes(param_data))
                        time.sleep(0.01)
                        print(f"相位差已写入地址87")

                        data = struct.pack('<I', 0x01)
                        self.send_param_write(85, data)
                        print("标定完成")
                        
                        # 在标定时绘制图表
                        self.plot_mech_calib_data(cd, istest)
                    
                    # 测试模式下验证相位差和绘制图表
                    if istest == 1:
                        # 在测试时绘制图表
                        self.plot_mech_calib_data(cd, istest)
                        
                        if phase_diff < 0.1:
                            print(f"机械标定测试成功！相位差为{phase_diff:.4f} rad，小于0.1 rad")
                            set_bytes = struct.pack('<I', 0x01)
                            self.send_param_write(86, bytes(set_bytes))
                        else:
                            print(f"机械标定测试失败！相位差为{phase_diff:.4f} rad，大于等于0.1 rad")
                else:
                    print("未检测到足够的跳变沿，无法计算相位差")
            
            # 重置数据
            cd['datacnt'] = 0
            cd['accangle_vec'] = []
            cd['senseangle_vec'] = []
            cd['acc_edges'] = []
            cd['sense_edges'] = []
        
        elif endcalib == 0:
            # 处理标定数据收集 - 直接保存原始数据
            cd['accangle_vec'].append(accangle)
            cd['senseangle_vec'].append(senseangle)
            
            # 非测试模式下的打印，每10次打印一次
            if istest == 0:
                if cd['printflag'] == 0:
                    print(f" {accangle:.4f},  {senseangle:.4f}")
                cd['printflag'] += 1
                if cd['printflag'] >= 10:
                    cd['printflag'] = 0
            
            # 更新last值
            cd['last_accangle'] = accangle
            cd['last_senseangle'] = senseangle
            
            cd['datacnt'] += 1
    
    def detect_falling_edges(self, cd):
        """检测accangle和senseangle的下降沿跳变"""
        if len(cd['accangle_vec']) < 2 or len(cd['senseangle_vec']) < 2:
            return
        
        # 检测senseangle从4pi跳转到-4pi的下降沿
        for i in range(1, len(cd['senseangle_vec'])):
            prev_sense = cd['senseangle_vec'][i-1]
            curr_sense = cd['senseangle_vec'][i]
            
            # 检测从接近4pi到接近-4pi的跳变（4pi≈12.566rad）
            if prev_sense > 10.0 and curr_sense < -10.0:
                cd['sense_edges'].append(i)
                print(f"检测到SENSE下降沿在数据点 {i}: {prev_sense:.4f} -> {curr_sense:.4f}")
        
        # 检测accangle的下降沿 - 只检测从接近pi到接近-pi的跳变
        for i in range(1, len(cd['accangle_vec'])):
            prev_acc = cd['accangle_vec'][i-1]
            curr_acc = cd['accangle_vec'][i]
            
            # 检测从接近pi到接近-pi的跳变（pi≈3.14，-pi≈-3.14）
            if prev_acc > 2.5 and curr_acc < -2.5:
                cd['acc_edges'].append(i)
                print(f"检测到ACC下降沿在数据点 {i}: {prev_acc:.4f} -> {curr_acc:.4f}")
    
    def plot_mech_calib_data(self, cd, istest):
        """绘制机械标定数据图表并保存，只展示sense角度负跳变周围100个点"""
        try:
            # 确定需要展示的数据点范围
            display_indices = set()
            data_length = len(cd['accangle_vec']) if cd['accangle_vec'] else 0
            
            # 如果有sense下降沿，只展示每个跳变周围100个点
            if cd['sense_edges']:
                for edge_idx in cd['sense_edges']:
                    # 计算每个跳变点前后100个点的范围，确保在有效索引内
                    start_idx = max(0, edge_idx - 100)
                    end_idx = min(data_length, edge_idx + 100)
                    # 将范围内的所有索引添加到集合中
                    for idx in range(start_idx, end_idx + 1):
                        display_indices.add(idx)
            # 如果没有检测到跳变沿，就绘制整个数据集
            else:
                if data_length > 0:
                    display_indices = set(range(data_length))
            
            # 如果没有需要展示的数据，直接返回
            if not display_indices:
                print("没有可展示的数据点")
                return
            
            # 将索引排序
            sorted_indices = sorted(display_indices)
            
            # 提取需要展示的数据
            acc_data = [cd['accangle_vec'][i] for i in sorted_indices]
            sense_data = [cd['senseangle_vec'][i] for i in sorted_indices]
            
            # 创建新的连续索引（从0开始）
            new_indices = list(range(len(sorted_indices)))
            
            # 创建原始索引到新索引的映射
            index_map = {old_idx: new_idx for new_idx, old_idx in enumerate(sorted_indices)}
            
            # 使用matplotlib绘制曲线（非阻塞方式）
            plt.figure(figsize=(12, 6))
            plt.plot(new_indices, acc_data, label='Actual Acc Angle')
            plt.plot(new_indices, sense_data, label='Actual Sense Angle')
            
            # 标记检测到的跳变沿
            if cd['acc_edges']:
                # 只标记在展示范围内的ACC下降沿
                acc_edges_in_range = [i for i in cd['acc_edges'] if i in display_indices]
                if acc_edges_in_range:
                    # 将原始索引转换为新索引
                    acc_edges_new_indices = [index_map[i] for i in acc_edges_in_range]
                    plt.scatter(acc_edges_new_indices, [cd['accangle_vec'][i] for i in acc_edges_in_range], 
                              color='red', marker='x', label='ACC下降沿')
            if cd['sense_edges']:
                # 只标记在展示范围内的SENSE下降沿
                sense_edges_in_range = [i for i in cd['sense_edges'] if i in display_indices]
                if sense_edges_in_range:
                    # 将原始索引转换为新索引
                    sense_edges_new_indices = [index_map[i] for i in sense_edges_in_range]
                    plt.scatter(sense_edges_new_indices, [cd['senseangle_vec'][i] for i in sense_edges_in_range], 
                              color='green', marker='o', label='SENSE下降沿')
            
            # 根据模式设置不同的标题和文件名
            if istest:
                plt.title('Mechanical Calibration Test: Actual Acc vs Actual Sense')
                filename = 'mech_calib_test_plot.png'
            else:
                plt.title('Mechanical Calibration: Actual Acc vs Actual Sense')
                filename = 'mech_calib_plot.png'
            
            plt.xlabel('Data Point')
            plt.ylabel('Angle (rad)')
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            # 保存图像而不是直接显示，避免线程问题
            import os
            save_path = os.path.join(os.getcwd(), filename)
            plt.savefig(save_path)
            plt.close()  # 关闭图像以释放内存
            print(f"标定曲线图已保存到: {save_path}")
        except Exception as e:
            print(f"绘图失败: {e}")
    
    def calculate_phase_difference(self, cd):
        """计算accangle和senseangle跳变沿的相位差，只选择索引最接近的两个下降沿进行比对"""
        if not cd['acc_edges'] or not cd['sense_edges']:
            print(f"跳变沿检测结果: ACC={len(cd['acc_edges'])}个, SENSE={len(cd['sense_edges'])}个")
            return None
        
        print(f"跳变沿检测结果: ACC={len(cd['acc_edges'])}个, SENSE={len(cd['sense_edges'])}个")
        
        # 找到所有下降沿组合中索引最接近的一对
        min_distance = float('inf')
        best_acc_idx = None
        best_sense_idx = None
        
        # 遍历所有SENSE和ACC下降沿的组合
        for sense_idx in cd['sense_edges']:
            for acc_idx in cd['acc_edges']:
                distance = abs(sense_idx - acc_idx)
                if distance < min_distance:
                    min_distance = distance
                    best_acc_idx = acc_idx
                    best_sense_idx = sense_idx
        
        if best_acc_idx is not None and best_sense_idx is not None:
            # 获取跳变沿处的实际角度值
            acc_phase = cd['accangle_vec'][best_acc_idx]
            sense_phase = cd['senseangle_vec'][best_sense_idx]
            
            print(f"匹配跳变沿: ACC点{best_acc_idx}({acc_phase:.4f}), SENSE点{best_sense_idx}({sense_phase:.4f})")
            print(f"索引距离: {min_distance}")
            
            # 根据用户要求：基于速度和跳变沿在index的位置计算相位差
            # 一个数据点是0.00066秒
            time_per_point = 0.00066  # 秒
            # 电机运行速度是10rad/s
            motor_speed = 10.0  # rad/s
            
            # 计算两个跳变沿之间的时间差
            # 注意：需要考虑哪个跳变沿在前面
            if best_acc_idx < best_sense_idx:
                # ACC跳变沿在SENSE跳变沿前面
                time_diff = (best_sense_idx - best_acc_idx) * time_per_point
            else:
                # SENSE跳变沿在ACC跳变沿前面
                time_diff = (best_acc_idx - best_sense_idx) * time_per_point
            
            # 根据时间差和电机速度计算相位差
            # 相位差 = 速度 * 时间差
            phase_diff = motor_speed * time_diff
            
            print(f"时间差: {time_diff:.6f} 秒")
            print(f"相位差: {phase_diff:.4f} rad")
            
            return phase_diff
        else:
            return None

class Oscilloscope:
    """示波器类（完全不变）"""
    def __init__(self, max_points=100):
        self.max_points = max_points
        self.x_data = []
        self.data = {
            'angle': [], 'speed': [], 'torque': [], 'temperature': []
        }
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False
        self.fig, self.ax = plt.subplots(figsize=(10, 6), dpi=100)
        self.fig.tight_layout()
        self.lines = {
            'angle': self.ax.plot([], [], 'r-', label='角度(rad)', linewidth=1.2)[0],
            'speed': self.ax.plot([], [], 'b-', label='速度(rad/s)', linewidth=1.2)[0],
            'torque': self.ax.plot([], [], 'g-', label='扭矩(Nm)', linewidth=1.2)[0],
            'temperature': self.ax.plot([], [], 'orange', label='温度(°C)', linewidth=1.2)[0]
        }
        self.ax.set_xlabel('数据点', fontsize=10)
        self.ax.set_ylabel('数值', fontsize=10)
        self.ax.set_title('电机状态示波器', fontsize=12, fontweight='bold')
        self.ax.legend(loc='upper right', fontsize=9)
        self.ax.grid(True, alpha=0.3)
        self.show_flags = {
            'angle': True, 'speed': True, 'torque': True, 'temperature': True
        }
        
        # 鼠标悬停显示数值相关变量
        self.annotation = None
        self.last_hovered_line = None
        
        # 绑定鼠标移动事件
        self.fig.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)

    def update_data(self, feedback_data):
        # 检查是否达到最大点数，如果是则清空数据重新开始
        if len(self.x_data) >= self.max_points:
            # 清空所有数据，实现示波器刷屏效果
            self.x_data = []
            for key in self.data.keys():
                self.data[key] = []
        
        # 添加新数据，x坐标从0开始重新计数
        self.x_data.append(len(self.x_data))
        self.data['angle'].append(feedback_data['angle'])
        self.data['speed'].append(feedback_data['speed'])
        self.data['torque'].append(feedback_data['torque'])
        self.data['temperature'].append(feedback_data['temperature'])

    def update_plot(self, show_flags=None, max_points=None):
        if show_flags:
            self.show_flags = show_flags
        if max_points:
            self.max_points = max_points
        
        for key, line in self.lines.items():
            if self.show_flags[key] and len(self.x_data) > 0:
                line.set_data(self.x_data, self.data[key])
                line.set_visible(True)
            else:
                line.set_visible(False)
        
        if len(self.x_data) > 0:
            self.ax.set_xlim(0, self.max_points)
            y_data = []
            for key in self.data.keys():
                if self.show_flags[key]:
                    y_data.extend(self.data[key])
            if y_data:
                self.ax.set_ylim(min(y_data)*0.9, max(y_data)*1.1)
        
        # 使用draw_idle()替代draw()以提高性能
        self.fig.canvas.draw_idle()
    
    def on_mouse_move(self, event):
        """鼠标移动事件处理，显示最近曲线点的数值"""
        if event.inaxes != self.ax:
            # 鼠标不在图表区域内，清除注释
            if self.annotation:
                self.annotation.remove()
                self.annotation = None
                self.fig.canvas.draw_idle()
            return
        
        # 如果数据为空，不处理
        if len(self.x_data) == 0:
            return
        
        # 将鼠标坐标转换为数据坐标
        mouse_x = event.xdata
        mouse_y = event.ydata
        
        if mouse_x is None or mouse_y is None:
            return
        
        # 找到最近的曲线点和对应的数值
        min_distance = float('inf')
        closest_line_key = None
        closest_index = None
        closest_x = None
        closest_y = None
        
        # 遍历所有显示的曲线
        for key, line in self.lines.items():
            if not self.show_flags[key] or not line.get_visible():
                continue
            
            x_data = line.get_xdata()
            y_data = line.get_ydata()
            
            if len(x_data) == 0 or len(y_data) == 0:
                continue
            
            # 找到最近的x坐标点
            if len(x_data) > 0 and len(y_data) > 0:
                # 确保x_data和y_data长度一致
                min_len = min(len(x_data), len(y_data))
                if min_len == 0:
                    continue
                
                # 找到最接近鼠标x坐标的数据点
                distances = [abs(x_data[i] - mouse_x) for i in range(min_len)]
                idx = distances.index(min(distances))
                
                # 确保索引有效
                if idx >= min_len:
                    continue
                
                # 计算到该点的距离（考虑x和y）
                point_x = x_data[idx]
                point_y = y_data[idx]
                distance = ((point_x - mouse_x) ** 2 + (point_y - mouse_y) ** 2) ** 0.5
                
                # 如果距离太远（超过一定阈值），跳过
                x_range = self.ax.get_xlim()[1] - self.ax.get_xlim()[0]
                y_range = self.ax.get_ylim()[1] - self.ax.get_ylim()[0]
                threshold = (x_range ** 2 + y_range ** 2) ** 0.5 * 0.05  # 5%的图表范围
                
                if distance < min_distance and distance < threshold:
                    min_distance = distance
                    closest_line_key = key
                    closest_index = idx
                    closest_x = point_x
                    closest_y = point_y
        
        # 如果找到了最近的曲线点，显示注释
        if closest_line_key is not None:
            # 获取该点的所有数值
            labels = {
                'angle': '角度',
                'speed': '速度',
                'torque': '扭矩',
                'temperature': '温度'
            }
            units = {
                'angle': 'rad',
                'speed': 'rad/s',
                'torque': 'Nm',
                'temperature': '°C'
            }
            
            # 构建显示文本
            text_lines = [f"数据点: {int(closest_x)}"]
            for key in self.data.keys():
                if self.show_flags[key] and len(self.data[key]) > closest_index:
                    value = self.data[key][closest_index]
                    label = labels.get(key, key)
                    unit = units.get(key, '')
                    text_lines.append(f"{label}: {value:.3f} {unit}")
            
            text = "\n".join(text_lines)
            
            # 移除旧的注释
            if self.annotation:
                self.annotation.remove()
            
            # 创建新注释
            self.annotation = self.ax.annotate(
                text,
                xy=(closest_x, closest_y),
                xytext=(10, 10),
                textcoords='offset points',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'),
                fontsize=9
            )
            
            self.fig.canvas.draw_idle()
        else:
            # 没有找到附近的曲线点，清除注释
            if self.annotation:
                self.annotation.remove()
                self.annotation = None
                self.fig.canvas.draw_idle()

import math

class SelfCheckOscilloscope:
    """自检数据示波器类，用于实时显示电机自检过程中的数据"""
    @staticmethod
    def convert_current(encoded_value):
        """将16位无符号电流值转换为实际电流值(-300A到300A)
        
        Args:
            encoded_value: 16位无符号数，表示电流值
            
        Returns:
            float: 转换后的实际电流值(A)
        """
        # 16位无符号数范围是0-65535
        # 映射到-300A到300A
        # 先将encoded_value转换为float类型再进行计算
        return (float(encoded_value) * (600.0 / 65535.0)) - 300.0
    
    @staticmethod
    def convert_sub_angle(encoded_value):
        """将副编码角度值(0-16383)转换为-pi到pi的范围
        
        Args:
            encoded_value: 16位无符号数，表示副编码角度(0-16383)
            
        Returns:
            float: 转换后的角度值(rad)
        """
        # 副编码范围是0-16383
        # 映射到-pi到pi
        # 先将encoded_value转换为float类型再进行计算
        return (float(encoded_value) / 16383.0) * 2 * math.pi - math.pi
    
    @staticmethod
    def convert_main_angle(encoded_value):
        """将主编码角度值(16位无符号数)转换为-pi到pi的范围
        
        Args:
            encoded_value: 16位无符号数，表示主编码角度
            
        Returns:
            float: 转换后的角度值(rad)
        """
        # 16位无符号数范围是0-65535
        # 映射到-pi到pi
        # 先将encoded_value转换为float类型再进行计算
        return (float(encoded_value) * (2 * math.pi)/ (65535.0))  - math.pi
    
    def __init__(self, max_points=1000):
        """初始化自检示波器，设置最大显示点数"""
        self.max_points = max_points
        self.x_data = []
        # 初始化各种数据列表
        self.data = {
            'current_a': [], 'current_b': [], 'current_c': [],
            'main_angle': [], 'sub_angle': []
        }
        
        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 创建图形和子图
        self.fig, self.ax = plt.subplots(figsize=(10, 6), dpi=100)
        self.fig.tight_layout()
        
        # 创建线条对象
        self.lines = {
            'current_a': self.ax.plot([], [], 'r-', label='电流A(A)', linewidth=1.0)[0],
            'current_b': self.ax.plot([], [], 'g-', label='电流B(A)', linewidth=1.0)[0],
            'current_c': self.ax.plot([], [], 'b-', label='电流C(A)', linewidth=1.0)[0],
            'main_angle': self.ax.plot([], [], 'orange', label='主编码角度(rad)', linewidth=1.2)[0],
            'sub_angle': self.ax.plot([], [], 'purple', label='副编码角度(rad)', linewidth=1.2)[0]
        }
        
        # 设置图表属性
        self.ax.set_xlabel('数据点', fontsize=10)
        self.ax.set_ylabel('数值', fontsize=10)
        self.ax.set_title('电机自检数据示波器', fontsize=12, fontweight='bold')
        self.ax.legend(loc='upper right', fontsize=9)
        self.ax.grid(True, alpha=0.3)
        
        # 显示标志
        self.show_flags = {
            'current_a': True, 'current_b': True, 'current_c': True,
            'main_angle': True, 'sub_angle': True
        }
    
    @staticmethod
    def convert_angle(encoded_value):
        """将16位无符号角度值转换为实际角度值(-π到π rad)
        
        Args:
            encoded_value: 16位无符号数，表示角度值(0-16383)
            
        Returns:
            float: 转换后的实际角度值(rad)
        """
        # 假设角度编码范围是0-16383，映射到-π到π
        return (encoded_value / 16383.0) * 2 * math.pi - math.pi
    
    def update_data(self, raw_data):
        """更新自检数据，接收原始编码数据并转换为实际值后绘图显示
        
        Args:
            raw_data: 包含原始编码数据的字典，现在可能只包含部分字段
                    {
                        'current_a': 16位无符号数 (可选),
                        'current_b': 16位无符号数 (可选),
                        'current_c': 16位无符号数 (可选),
                        'main_angle': 16位无符号数 (可选),
                        'sub_angle': 16位无符号数 (可选, 0-16383)
                    }
        """
        # 检查是否达到最大点数，如果是则清空数据重新开始
        if len(self.x_data) >= self.max_points:
            self.x_data = []
            for key in self.data.keys():
                self.data[key] = []
        
        # 添加新数据点索引
        if raw_data:  # 确保数据不为空
            new_index = len(self.x_data)
            self.x_data.append(new_index)
            
            # 定义数据类型和对应的转换函数
            data_types = {
                'current_a': self.convert_current,
                'current_b': self.convert_current,
                'current_c': self.convert_current,
                'main_angle': self.convert_main_angle,
                'sub_angle': self.convert_sub_angle
            }
            
            # 批量处理所有数据类型，减少重复代码
            for data_type, convert_func in data_types.items():
                # 检查数据是否存在且有效
                if data_type in raw_data and raw_data[data_type] is not None:
                    # 使用转换函数处理数据
                    self.data[data_type].append(convert_func(raw_data[data_type]))
                elif self.data[data_type]:  # 如果没有新数据，复制最后一个值保持长度一致
                    self.data[data_type].append(self.data[data_type][-1])
                else:
                    # 首次添加数据时使用默认值
                    self.data[data_type].append(0.0)
    
    def update_plot(self, show_flags=None, max_points=None):
        """更新示波器显示"""
        # 移除更新频率限制，与普通示波器保持一致
        if show_flags:
            self.show_flags = show_flags
        if max_points:
            self.max_points = max_points
        
        # 限制数据点数量，避免无限增长
        if len(self.x_data) > self.max_points:
            excess = len(self.x_data) - self.max_points
            self.x_data = self.x_data[excess:]
            for key in self.data.keys():
                if len(self.data[key]) > excess:
                    self.data[key] = self.data[key][excess:]
        
        # 更新每条线的数据
        for key, line in self.lines.items():
            if self.show_flags[key] and len(self.x_data) > 0 and len(self.data[key]) > 0:
                line.set_data(self.x_data, self.data[key])
                line.set_visible(True)
            else:
                line.set_visible(False)
        
        # 固定横轴显示范围，无论数据量多少都显示固定数量的数据点
        display_points = min(len(self.x_data), self.max_points)
        if display_points > 0:
            # 总是显示最近的display_points个数据点
            self.ax.set_xlim(0, self.max_points)
            
            # 计算显示范围内的y数据
            y_data = []
            for key in self.data.keys():
                if self.show_flags[key] and len(self.data[key]) > 0:
                    # 只取最近的display_points个数据点用于计算y轴范围
                    recent_data = self.data[key][-display_points:] if len(self.data[key]) > display_points else self.data[key]
                    y_data.extend(recent_data)
            if y_data:
                self.ax.set_ylim(min(y_data)*0.9, max(y_data)*1.1)
        
        # 使用draw_idle()替代draw()以提高性能，与普通示波器保持一致
        self.fig.canvas.draw_idle()

class MotorControlGUI:
    """Tkinter主GUI类（不变，版本号显示逻辑已适配a.b.c.d格式）"""
    def __init__(self, root):
        self.root = root
        self.root.title("电机控制GUI")
        self.root.geometry("1400x800")
        self.root.resizable(True, True)

        self.can_comm = CANCommunicator()
        # 添加can_communicator属性，保持向后兼容性
        self.can_communicator = self.can_comm
        self.oscilloscope = Oscilloscope()
        self.self_check_oscilloscope = SelfCheckOscilloscope()
        
        # PLC Modbus通信对象
        self.modbus_client = None
        self.plc_connected = False
        self.device_id = 1  # 默认设备ID
        
        # PCAN连接状态
        self.can_connected = False
        
        # 控制状态
        self.motor_enabled = False
        
        # 新增：MPC自动发送相关变量
        self.auto_send = False
        self.send_interval = 20  # 默认20ms，即50Hz
        self.send_timer = None
        self.actual_freq = 50  # 默认频率值
        
        # 新增：低通滤波相关变量
        self.filter_alpha = 0.3  # 低通滤波系数，0-1之间，越小滤波效果越强
        # 上一次滤波后的角度值
        self.filtered_hip_angle = 0.0
        self.filtered_thigh_angle = 0.0
        self.filtered_calf_angle = 0.0
        # 初始标志
        self.filter_initialized = False
        
        # 新增：PI控制相关变量
        self.pi_control_running = False
        self.pi_control_thread = None
        self.target_speed = 0.0  # 目标速度
        self.current_speed = 0.0  # 当前速度（从电机反馈获取）
        self.current_angle = 0.0  # 当前角度（从电机反馈获取）
        self.sumerror_spd = 0.0  # 速度误差积分
        self.pi_control_lock = threading.Lock()  # 用于线程安全访问共享变量
        
        self.status_map = {
            0: "待机", 1: "运控使能", 2: "故障",
            3: "自检模式", 4: "速度模式", 5: "编码器标定"
        }
        self.fault_map = {
            0: "过载", 1: "过流", 2: "过温", 3: "欠压",
            4: "过压", 5: "编码器故障", 6: "过载预警"
        }

        self.create_layout()
        self.root.after(10, self.update_gui)

    def create_layout(self):
        """UI布局（添加新功能）"""
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X, side=tk.TOP)

        # 新增：电机电源控制区域（PLC Modbus）
        power_frame = ttk.LabelFrame(top_frame, text="电机电源控制", padding="10")
        power_frame.grid(row=0, column=0, columnspan=6, padx=5, pady=5, sticky=tk.EW)
        self.create_power_control(power_frame)

        # 新增：电机控制区域 - 放在电机电源控制下面
        motor_control_frame = ttk.LabelFrame(top_frame, text="电机控制", padding="10")
        motor_control_frame.grid(row=1, column=0, columnspan=6, padx=5, pady=5, sticky=tk.EW)
        self.create_motor_control(motor_control_frame)

        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        left_frame = ttk.Frame(main_frame, width=400)
        left_frame.pack(fill=tk.Y, side=tk.LEFT, padx=(0, 10))
        left_frame.pack_propagate(False)
        


        # 新增：电机状态和故障显示
        status_group = ttk.LabelFrame(left_frame, text="电机状态", padding="10")
        status_group.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(status_group, text="当前状态：").grid(row=0, column=0, padx=5, pady=3, sticky=tk.W)
        self.status_display = ttk.Label(status_group, text="未连接", width=20, background="#EEEEEE")
        self.status_display.grid(row=0, column=1, padx=5, pady=3)
        
        ttk.Label(status_group, text="当前故障：").grid(row=1, column=0, padx=5, pady=3, sticky=tk.W)
        self.fault_display = ttk.Label(status_group, text="无", width=20, background="#EEEEEE")
        self.fault_display.grid(row=1, column=1, padx=5, pady=3)

        # 新增：PI控制组
        pi_control_group = ttk.LabelFrame(left_frame, text="PI速度控制", padding="10")
        pi_control_group.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(pi_control_group, text="目标速度（rad/s）：").grid(row=0, column=0, padx=5, pady=3, sticky=tk.W)
        self.target_speed_var = tk.StringVar(value="0.0")
        self.target_speed_entry = ttk.Entry(pi_control_group, textvariable=self.target_speed_var, width=15)
        self.target_speed_entry.grid(row=0, column=1, padx=5, pady=3)
        
        self.set_target_speed_btn = ttk.Button(pi_control_group, text="设定目标速度", command=self.set_target_speed)
        self.set_target_speed_btn.grid(row=0, column=2, padx=5, pady=3)
        
        ttk.Label(pi_control_group, text="当前速度（rad/s）：").grid(row=1, column=0, padx=5, pady=3, sticky=tk.W)
        self.current_speed_label = ttk.Label(pi_control_group, text="0.00", width=15, background="#EEEEEE")
        self.current_speed_label.grid(row=1, column=1, padx=5, pady=3, sticky=tk.W)
        
        # 使能运控按钮
        self.enable_motion_btn = ttk.Button(pi_control_group, text="使能运控", command=lambda: self.enable_motor(1))
        self.enable_motion_btn.grid(row=2, column=0, columnspan=3, padx=5, pady=5, sticky=tk.EW)
        
        self.pi_control_btn = ttk.Button(pi_control_group, text="启动PI控制", command=self.toggle_pi_control)
        self.pi_control_btn.grid(row=3, column=0, columnspan=3, padx=5, pady=10, sticky=tk.EW)

        # 新增：踢腿控制模块
        kick_control_group = ttk.LabelFrame(left_frame, text="踢腿控制", padding="10")
        kick_control_group.pack(fill=tk.X, padx=5, pady=5)
        
        # 伸腿按钮
        extend_leg_btn = ttk.Button(kick_control_group, text="伸腿", command=self.extend_leg)
        extend_leg_btn.grid(row=0, column=0, padx=5, pady=5, sticky=tk.EW)
        
        # 踢腿按钮
        kick_leg_btn = ttk.Button(kick_control_group, text="踢腿", command=self.kick_leg)
        kick_leg_btn.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
        
        kick_control_group.grid_columnconfigure(0, weight=1)
        kick_control_group.grid_columnconfigure(1, weight=1)

        # 版本信息和其他操作
        info_group = ttk.LabelFrame(left_frame, text="设备信息", padding="10")
        info_group.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(info_group, text="固件版本：").grid(row=0, column=0, padx=5, pady=3, sticky=tk.W)
        self.version_label = ttk.Label(info_group, text="未读取", width=20)
        self.version_label.grid(row=0, column=1, padx=5, pady=3)

        self.read_version_btn = ttk.Button(info_group, text="读取版本", command=self.read_version)
        self.read_version_btn.grid(row=1, column=0, padx=5, pady=5)

        self.clear_fault_btn = ttk.Button(info_group, text="清除故障", command=self.clear_fault)
        self.clear_fault_btn.grid(row=1, column=1, padx=5, pady=5)
        
        # 创建Notebook组件用于多页面显示
        self.notebook = ttk.Notebook(main_frame)  # 确保使用self.notebook
        self.notebook.pack(fill=tk.BOTH, expand=True, side=tk.RIGHT)
        
        # 页面1: 电机控制
        control_page = ttk.Frame(self.notebook)
        self.notebook.add(control_page, text="电机控制")
        
        # 示波器显示区域
        self.canvas = FigureCanvasTkAgg(self.oscilloscope.fig, master=control_page)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 示波器控制
        scope_control = ttk.Frame(control_page, padding="5")
        scope_control.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 页面2: 自检工具
        self.self_check_page = ttk.Frame(self.notebook)
        self.notebook.add(self.self_check_page, text="自检工具")
        
        # 初始化自检工具页面布局
        self.init_self_check_page()
        
        # 页面3: 固件刷写
        self.firmware_page = ttk.Frame(self.notebook)
        self.notebook.add(self.firmware_page, text="固件刷写")
        
        # 初始化固件刷写页面布局
        self.init_firmware_page()

        self.show_angle = tk.BooleanVar(value=True)
        self.show_speed = tk.BooleanVar(value=True)
        self.show_torque = tk.BooleanVar(value=True)
        self.show_temp = tk.BooleanVar(value=True)

        ttk.Checkbutton(scope_control, text="显示角度", variable=self.show_angle, command=self.update_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(scope_control, text="显示速度", variable=self.show_speed, command=self.update_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(scope_control, text="显示扭矩", variable=self.show_torque, command=self.update_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(scope_control, text="显示温度", variable=self.show_temp, command=self.update_scope).pack(side=tk.LEFT, padx=10)

        ttk.Label(scope_control, text="数据点数：").pack(side=tk.LEFT, padx=(20, 5))
        self.points_var = tk.IntVar(value=100)
        ttk.Combobox(scope_control, textvariable=self.points_var, values=[500, 100, 2000, 5000], width=8).pack(side=tk.LEFT)
        ttk.Button(scope_control, text="更新显示", command=self.update_scope).pack(side=tk.LEFT, padx=10)
        
        # 配置样式使禁能按钮更大更醒目
        style = ttk.Style()
        style.configure('Red.TButton', font=('Helvetica', 12, 'bold'), foreground='red')
    
    def create_power_control(self, parent):
        """创建电机电源控制面板（PLC Modbus）"""
        # 第一行：COM口和连接控制
        row0 = ttk.Frame(parent)
        row0.pack(fill=tk.X, pady=3)
        
        ttk.Label(row0, text="COM口:").pack(side=tk.LEFT, padx=5)
        self.com_port_combo = ttk.Combobox(row0, width=20, state="readonly")
        self.com_port_combo.pack(side=tk.LEFT, padx=5)
        
        refresh_btn = ttk.Button(row0, text="刷新", command=self.scan_serial_ports, width=8)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        
        self.plc_connect_btn = ttk.Button(row0, text="连接", command=self.toggle_plc_connection, width=8)
        self.plc_connect_btn.pack(side=tk.LEFT, padx=(10, 5))
        
        self.plc_status_label = ttk.Label(row0, text="未连接", foreground="red", font=("Arial", 9, "bold"))
        self.plc_status_label.pack(side=tk.LEFT, padx=5)
        
        # 串口参数：放在未连接后面
        ttk.Label(row0, text="波特率:").pack(side=tk.LEFT, padx=(10, 5))
        self.baudrate_combo = ttk.Combobox(row0, width=10, values=["9600", "19200", "38400", "57600", "115200"], state="readonly")
        self.baudrate_combo.set("115200")
        self.baudrate_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="数据位:").pack(side=tk.LEFT, padx=(10, 5))
        self.databits_combo = ttk.Combobox(row0, width=8, values=["7", "8"], state="readonly")
        self.databits_combo.set("8")
        self.databits_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="校验位:").pack(side=tk.LEFT, padx=(10, 5))
        self.parity_combo = ttk.Combobox(row0, width=10, values=["None", "Even", "Odd"], state="readonly")
        self.parity_combo.set("Odd")
        self.parity_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="停止位:").pack(side=tk.LEFT, padx=(10, 5))
        self.stopbits_combo = ttk.Combobox(row0, width=8, values=["1", "2"], state="readonly")
        self.stopbits_combo.set("1")
        self.stopbits_combo.pack(side=tk.LEFT, padx=5)
        
        # 第二行：设备ID和寄存器类型
        row2 = ttk.Frame(parent)
        row2.pack(fill=tk.X, pady=3)
        
        ttk.Label(row2, text="Device Id:").pack(side=tk.LEFT, padx=5)
        self.device_id_var = tk.StringVar(value="1")
        device_id_entry = ttk.Entry(row2, textvariable=self.device_id_var, width=10)
        device_id_entry.pack(side=tk.LEFT, padx=5)
        
        # 寄存器类型选择（默认选择线圈）
        ttk.Label(row2, text="类型:").pack(side=tk.LEFT, padx=(10, 5))
        self.register_type_var = tk.StringVar(value="线圈")
        type_combo = ttk.Combobox(row2, textvariable=self.register_type_var, 
                                  values=["保持寄存器", "线圈"], state="readonly", width=12)
        type_combo.pack(side=tk.LEFT, padx=5)
        
        # 电源控制按钮：放在类型后面
        self.power_btn1 = ttk.Button(row2, text="设备启动", command=lambda: self.write_plc_register(2049, 1), width=12)
        self.power_btn1.pack(side=tk.LEFT, padx=5)
        
        self.power_btn2 = ttk.Button(row2, text="左电源", command=lambda: self.write_plc_register(2053, 1), width=12)
        self.power_btn2.pack(side=tk.LEFT, padx=5)
        
        self.power_btn3 = ttk.Button(row2, text="右电源", command=lambda: self.write_plc_register(2054, 1), width=12)
        self.power_btn3.pack(side=tk.LEFT, padx=5)
        
        self.power_btn4 = ttk.Button(row2, text="全部下电", command=lambda: self.write_plc_register(2050, 1), width=12)
        self.power_btn4.pack(side=tk.LEFT, padx=5)
        
        # 测试读取按钮
        test_btn = ttk.Button(row2, text="测试读取", command=self.test_read_register, width=10)
        test_btn.pack(side=tk.LEFT, padx=5)
        
        # 更新按钮状态
        self.update_power_buttons_state()
        
        # 扫描串口
        self.scan_serial_ports()
    
    def create_motor_control(self, parent):
        """创建电机控制面板"""
        # 第一行：PCAN设备和连接控制
        row0 = ttk.Frame(parent)
        row0.pack(fill=tk.X, pady=3)
        
        ttk.Label(row0, text="PCAN设备:").pack(side=tk.LEFT, padx=5)
        self.pcan_device_combo = ttk.Combobox(row0, width=30, state="readonly")
        self.pcan_device_combo.pack(side=tk.LEFT, padx=5)
        self.pcan_device_combo.bind('<<ComboboxSelected>>', self.on_pcan_device_select)
        
        ttk.Button(row0, text="刷新设备", command=self.scan_pcan_devices, width=10).pack(side=tk.LEFT, padx=5)
        
        self.can_connect_btn = ttk.Button(row0, text="连接", command=self.toggle_can_connection, width=8)
        self.can_connect_btn.pack(side=tk.LEFT, padx=(10, 5))
        
        self.can_status_var = tk.StringVar(value="未连接")
        self.can_status_label = ttk.Label(row0, textvariable=self.can_status_var, width=15, foreground="red", font=("Arial", 9, "bold"))
        self.can_status_label.pack(side=tk.LEFT, padx=5)
        
        # 搜索和选择区域：放在同一行（参考搜索设备模块的方式）
        ttk.Button(row0, text="搜索", command=self.search_motors_can).pack(side=tk.LEFT, padx=(10, 5))
        ttk.Button(row0, text="重置", command=self.reset_can_bus, width=10).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="选中电机：").pack(side=tk.LEFT, padx=(10, 5))
        self.motor_can_var = tk.StringVar()
        self.motor_can_combo = ttk.Combobox(row0, textvariable=self.motor_can_var, width=30, state="readonly")
        self.motor_can_combo.pack(side=tk.LEFT, padx=5)
        self.motor_can_combo.bind("<<ComboboxSelected>>", self.on_motor_select_can)
        
        # 使能/禁能按钮
        self.enable_button = ttk.Button(row0, text="使能电机", command=self.toggle_motor)
        self.enable_button.pack(side=tk.LEFT, padx=(10, 5))
        
        ttk.Button(row0, text="清除故障", command=self.clear_fault).pack(side=tk.LEFT, padx=5)
        
        # 扫描PCAN设备（延迟执行）
        self.root.after(100, self.scan_pcan_devices)
    
    def init_self_check_page(self):
        """初始化自检工具页面的布局"""
        # 自检示波器显示区域
        self.self_check_canvas = FigureCanvasTkAgg(self.self_check_oscilloscope.fig, master=self.self_check_page)
        self.self_check_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 自检工具控制区域
        control_frame = ttk.Frame(self.self_check_page, padding="5")
        control_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        # 数据显示控制复选框
        self.show_current_a = tk.BooleanVar(value=True)
        self.show_current_b = tk.BooleanVar(value=True)
        self.show_current_c = tk.BooleanVar(value=True)
        self.show_main_angle = tk.BooleanVar(value=True)
        self.show_sub_angle = tk.BooleanVar(value=True)
        
        ttk.Checkbutton(control_frame, text="显示电流A", variable=self.show_current_a, command=self.update_self_check_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(control_frame, text="显示电流B", variable=self.show_current_b, command=self.update_self_check_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(control_frame, text="显示电流C", variable=self.show_current_c, command=self.update_self_check_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(control_frame, text="显示主编码角度", variable=self.show_main_angle, command=self.update_self_check_scope).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(control_frame, text="显示副编码角度", variable=self.show_sub_angle, command=self.update_self_check_scope).pack(side=tk.LEFT, padx=10)
        
        # 数据点数控制
        ttk.Label(control_frame, text="数据点数：").pack(side=tk.LEFT, padx=(20, 5))
        self.self_check_points_var = tk.IntVar(value=1000)
        ttk.Combobox(control_frame, textvariable=self.self_check_points_var, values=[50, 1000, 200, 500], width=8).pack(side=tk.LEFT)
        ttk.Button(control_frame, text="更新显示", command=self.update_self_check_scope).pack(side=tk.LEFT, padx=10)
    
    def init_firmware_page(self):
        """初始化固件刷写页面的布局"""
        # 创建主框架
        main_frame = ttk.Frame(self.firmware_page, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 文件选择区域
        file_frame = ttk.LabelFrame(main_frame, text="固件文件", padding="10")
        file_frame.pack(fill=tk.X, padx=5, pady=10)
        
        self.firmware_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.firmware_path_var, width=60).grid(row=0, column=0, padx=5, pady=5, sticky=tk.EW)
        ttk.Button(file_frame, text="选择固件", command=self.select_firmware_file).grid(row=0, column=1, padx=5, pady=5)
        file_frame.grid_columnconfigure(0, weight=1)
        
        # 固件信息显示区域
        info_frame = ttk.LabelFrame(main_frame, text="固件信息", padding="10")
        info_frame.pack(fill=tk.X, padx=5, pady=10)
        
        ttk.Label(info_frame, text="文件大小：").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.file_size_var = tk.StringVar(value="未选择文件")
        ttk.Label(info_frame, textvariable=self.file_size_var).grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        ttk.Label(info_frame, text="打包数量：").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.package_count_var = tk.StringVar(value="未选择文件")
        ttk.Label(info_frame, textvariable=self.package_count_var).grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        # 刷写控制区域
        control_frame = ttk.LabelFrame(main_frame, text="刷写控制", padding="10")
        control_frame.pack(fill=tk.X, padx=5, pady=10)
        
        self.flash_erase_btn = ttk.Button(control_frame, text="Flash擦除", command=self.flash_erase, state=tk.DISABLED)
        self.flash_erase_btn.grid(row=0, column=0, padx=20, pady=10, sticky=tk.EW)
        
        self.flash_write_btn = ttk.Button(control_frame, text="刷写固件", command=self.write_firmware, state=tk.DISABLED)
        self.flash_write_btn.grid(row=0, column=1, padx=20, pady=10, sticky=tk.EW)
        
        self.cancel_flash_btn = ttk.Button(control_frame, text="取消刷写", command=self.cancel_flash, state=tk.DISABLED)
        self.cancel_flash_btn.grid(row=0, column=2, padx=20, pady=10, sticky=tk.EW)
        
        control_frame.grid_columnconfigure(0, weight=1)
        control_frame.grid_columnconfigure(1, weight=1)
        control_frame.grid_columnconfigure(2, weight=1)
        
        # 进度和状态显示区域
        status_frame = ttk.LabelFrame(main_frame, text="刷写状态", padding="10")
        status_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=10)
        
        # 进度条
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(status_frame, variable=self.progress_var, length=100, mode='determinate')
        self.progress_bar.pack(fill=tk.X, padx=5, pady=5)
        
        # 进度标签
        self.progress_label = ttk.Label(status_frame, text="0% - 准备就绪")
        self.progress_label.pack(fill=tk.X, padx=5, pady=5)
        
        # 状态标签
        self.erase_status_var = tk.StringVar(value="未擦除")
        self.write_status_var = tk.StringVar(value="准备就绪")
        
        status_info_frame = ttk.Frame(status_frame)
        status_info_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(status_info_frame, text="擦除状态：").grid(row=0, column=0, padx=5, pady=2, sticky=tk.W)
        ttk.Label(status_info_frame, textvariable=self.erase_status_var).grid(row=0, column=1, padx=5, pady=2, sticky=tk.W)
        
        ttk.Label(status_info_frame, text="刷写状态：").grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        ttk.Label(status_info_frame, textvariable=self.write_status_var).grid(row=1, column=1, padx=5, pady=2, sticky=tk.W)
        
        # 日志文本框
        self.log_text = tk.Text(status_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text.config(state=tk.DISABLED)  # 初始为只读
        
        # 固件刷写相关变量初始化
        self.selected_firmware = None
        self.firmware_data = None
        self.is_erased = False
        self.is_flashing = False
        self.is_erasing = False
        self.stop_flag = False

    def update_angle_label(self, value):
        actual = CANCommunicator.protocol_to_actual(int(float(value)), ANGLE_MIN, ANGLE_MAX)
        self.angle_label.config(text=f"{actual:.2f} rad")

    def update_speed_label(self, value):
        actual = CANCommunicator.protocol_to_actual(int(float(value)), SPEED_MIN, SPEED_MAX)
        self.speed_label.config(text=f"{actual:.2f} rad/s")

    def update_torque_label(self, value):
        actual = CANCommunicator.protocol_to_actual(int(float(value)), TORQUE_MIN, TORQUE_MAX)
        self.torque_label.config(text=f"{actual:.2f} Nm")

    def search_motors(self):
        # 在独立线程中执行电机搜索，避免阻塞GUI
        import threading
        def search_in_thread():
            self.can_comm.search_motors()
        
        # 启动搜索线程
        search_thread = threading.Thread(target=search_in_thread, daemon=True)
        search_thread.start()

    def on_motor_select(self, event):
        # 优化电机选择处理，避免阻塞
        selected = self.motor_var.get()
        if selected:
            try:
                motor_id = int(selected.split()[0])
                # 直接设置电机ID，避免遍历搜索
                self.can_comm.current_motor_id = motor_id
                # 同时设置self.selected_motor_id，确保自动上报功能能正确检测
                self.selected_motor_id = motor_id
                
                # 异步查找unique_id，不阻塞主线程
                def find_unique_id():
                    for mid, uid in self.can_comm.discovered_motors:
                        if mid == motor_id:
                            self.can_comm.current_unique_id = uid
                            break
                
                # 使用单独的线程处理，避免阻塞GUI
                import threading
                threading.Thread(target=find_unique_id, daemon=True).start()
                
            except Exception as e:
                # 静默处理异常，避免程序崩溃
                pass

    def set_motor_id(self):
        try:
            new_id = int(self.new_id_entry.get())
            if 1 <= new_id <= 127:
                self.can_comm.set_motor_id(new_id)
            else:
                # 移除错误弹窗
                pass
        except ValueError:
            # 移除错误弹窗
            pass

    def send_mpc_command(self):
        angle = CANCommunicator.protocol_to_actual(int(self.angle_var.get()), ANGLE_MIN, ANGLE_MAX)
        speed = CANCommunicator.protocol_to_actual(int(self.speed_var.get()), SPEED_MIN, SPEED_MAX)
        torque = CANCommunicator.protocol_to_actual(int(self.torque_var.get()), TORQUE_MIN, TORQUE_MAX)
        self.can_comm.send_mpc_command(angle, speed, torque)
    
    # 新增：自动发送MPC指令相关方法
    def select_firmware_file(self):
        """选择固件文件并统计信息"""
        from tkinter import filedialog
        import os
        
        # 打开文件选择对话框
        file_path = filedialog.askopenfilename(
            title="选择固件文件",
            filetypes=[("Bin文件", "*.bin"), ("所有文件", "*.*")]
        )
        
        if file_path:
            try:
                # 读取文件信息
                file_size = os.path.getsize(file_path)
                package_count = (file_size + 7) // 8  # 向上取整，8字节一包
                
                # 读取文件内容
                with open(file_path, 'rb') as f:
                    self.firmware_data = f.read()
                
                # 更新UI显示
                self.firmware_path_var.set(file_path)
                self.file_size_var.set(f"{file_size} 字节")
                self.package_count_var.set(f"{package_count} 包")
                
                # 启用Flash擦除按钮
                self.flash_erase_btn.config(state=tk.NORMAL)
                
                # 重置刷写状态
                self.is_erased = False
                self.flash_write_btn.config(state=tk.DISABLED)
                
                # 记录日志
                self.log(f"已选择固件文件: {os.path.basename(file_path)}")
                self.log(f"文件大小: {file_size} 字节")
                self.log(f"打包数量: {package_count} 包")
                
                # 保存文件路径
                self.selected_firmware = file_path
                
            except Exception as e:
                self.log(f"文件读取错误: {str(e)}")
                # 重置状态
                self.firmware_path_var.set("")
                self.file_size_var.set("读取失败")
                self.package_count_var.set("读取失败")
                self.firmware_data = None
                self.selected_firmware = None
                self.flash_erase_btn.config(state=tk.DISABLED)
    
    def log(self, message):
        """向日志文本框添加消息"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)  # 自动滚动到底部
        self.log_text.config(state=tk.DISABLED)
        
    def cancel_flash(self):
        """取消正在进行的刷写或擦除操作"""
        if self.is_erasing or self.is_flashing:
            self.log("正在取消操作...")
            self.stop_flag = True
            
            # 更新状态
            if self.is_erasing:
                self.erase_status_var.set("擦除已取消")
            if self.is_flashing:
                self.write_status_var.set("刷写已取消")
            
            # 重置UI状态
            def reset_ui_after_delay():
                self.log("操作已取消")
                self.is_erasing = False
                self.is_flashing = False
                self.stop_flag = False
                self.flash_erase_btn.config(state=tk.NORMAL if self.selected_firmware else tk.DISABLED)
                self.flash_write_btn.config(state=tk.NORMAL if self.is_erased and self.selected_firmware else tk.DISABLED)
                self.cancel_flash_btn.config(state=tk.DISABLED)
                self.progress_var.set(0)
                self.progress_label.config(text="0% - 准备就绪")
            
            # 延迟重置UI，确保线程有时间响应停止标志
            self.root.after(1000, reset_ui_after_delay)
        
    def flash_erase(self):
        """执行Flash擦除操作"""
        #if not self.can_communicator.current_motor_id:
        #    self.log("请先选择要控制的电机")
        #    return
        
        # 更新UI状态
        self.flash_erase_btn.config(state=tk.DISABLED)
        self.flash_write_btn.config(state=tk.DISABLED)
        self.cancel_flash_btn.config(state=tk.NORMAL)  # 启用取消按钮
        self.erase_status_var.set("擦除中...")
        self.progress_var.set(50)  # 擦除操作设置为50%进度
        self.progress_label.config(text="50% - 正在擦除")
        self.is_erasing = True
        self.stop_flag = False
        self.log("开始执行Flash擦除操作...")
        
        # 创建一个线程来执行擦除操作，避免阻塞UI
        def erase_thread_func():
            success = False
            try:
                # 检查是否已取消
                if self.stop_flag:
                    return
                    
                # 调用CAN通信器发送擦除命令
                success = self.can_comm.send_flash_erase()
                
                # 再次检查是否已取消
                if self.stop_flag:
                    return
                
                # 在主线程中更新UI
                def update_ui():
                    self.is_erasing = False
                    self.progress_var.set(0)
                    self.cancel_flash_btn.config(state=tk.DISABLED)
                    
                    if success:
                        self.erase_status_var.set("擦除成功")
                        self.flash_write_btn.config(state=tk.NORMAL)
                        self.is_erased = True  # 标记擦除成功
                        self.log("Flash擦除成功")
                    else:
                        self.erase_status_var.set("擦除失败")
                        self.flash_erase_btn.config(state=tk.NORMAL)
                        self.log("Flash擦除失败: 电机响应超时或错误")
                    
                    self.progress_label.config(text="0% - 准备就绪")
                
                # 使用after方法在主线程中更新UI
                self.root.after(0, update_ui)
                
            except Exception as e:
                error_message = str(e)  # 保存异常信息
                if not self.stop_flag:  # 只有在未取消的情况下才显示错误
                    def update_ui_error():
                        self.is_erasing = False
                        self.erase_status_var.set("擦除失败")
                        self.flash_erase_btn.config(state=tk.NORMAL)
                        self.cancel_flash_btn.config(state=tk.DISABLED)
                        self.progress_var.set(0)
                        self.progress_label.config(text="0% - 准备就绪")
                        self.log(f"Flash擦除过程异常: {error_message}")  # 使用保存的异常信息
                    self.root.after(0, update_ui_error)
                else:
                    self.is_erasing = False
        
        # 启动擦除线程
        erase_thread = threading.Thread(target=erase_thread_func)
        erase_thread.daemon = True
        erase_thread.start()
        
    def write_firmware(self):
        """执行固件刷写操作"""
        if not self.can_comm.current_motor_id:
            self.log("请先选择要控制的电机")
            return
            
        if not self.is_erased:
            self.log("请先执行Flash擦除操作")
            return
            
        if not hasattr(self, 'firmware_data') or self.firmware_data is None:
            self.log("未找到固件数据，请先选择固件文件")
            return
        
        # 更新UI状态
        self.flash_erase_btn.config(state=tk.DISABLED)
        self.flash_write_btn.config(state=tk.DISABLED)
        self.cancel_flash_btn.config(state=tk.NORMAL)  # 启用取消按钮
        self.write_status_var.set("刷写中...")
        self.progress_var.set(0)
        self.progress_label.config(text="0% - 准备发送文件信息")
        self.log("开始执行固件刷写操作...")
        
        # 设置状态标志
        self.is_flashing = True
        self.stop_flag = False
        
        # 创建一个线程来执行刷写操作，避免阻塞UI
        def write_thread_func():
            try:
                # 获取文件信息
                file_size = len(self.firmware_data)
                package_count = (file_size + 7) // 8  # 向上取整，5字节一包（按照新协议要求）
                
                # 检查是否已取消
                if self.stop_flag:
                    self.root.after(0, lambda: self.log("刷写操作已取消"))
                    self.root.after(0, lambda: self.write_status_var.set("已取消"))
                    return
                
                # 1. 发送文件信息
                self.root.after(0, lambda: self.log(f"发送文件信息：大小={file_size}字节, 包数={package_count}包"))
                self.root.after(0, lambda: self.progress_label.config(text="10% - 发送文件信息"))
                success = self.can_comm.send_file_info(file_size, package_count)
                
                if not success:
                    self.root.after(0, lambda: self.log("发送文件信息失败: 电机响应超时或错误"))
                    self.root.after(0, lambda: self.write_status_var.set("发送文件信息失败"))
                    return
                
                self.root.after(0, lambda: self.log("文件信息发送成功，开始传输数据..."))
                
                # 检查是否已取消
                if self.stop_flag:
                    self.root.after(0, lambda: self.log("刷写操作已取消"))
                    self.root.after(0, lambda: self.write_status_var.set("已取消"))
                    return
                
                # 2. 分包发送文件数据
                success = True
                for i in range(package_count):
                    # 检查是否已取消
                    if self.stop_flag:
                        self.root.after(0, lambda: self.log("刷写操作已取消"))
                        success = False
                        break
                    
                    # 计算当前包的数据范围
                    start_idx = i * 8
                    end_idx = min(start_idx + 8, file_size)
                    data_bytes = list(self.firmware_data[start_idx:end_idx])
                    
                    # 发送数据包
                    if not self.can_comm.send_file_data(i, data_bytes):
                        success = False
                        error_msg = f"发送数据包 #{i+1}/{package_count} 失败: 电机响应超时"
                        self.root.after(0, lambda msg=error_msg: self.log(msg))
                        break
                    
                    # 更新进度条和进度标签
                    progress = 10 + (i + 1) / package_count * 80  # 10%-90%用于数据传输
                    progress_percent = int(progress)
                    self.root.after(0, lambda p=progress: self.progress_var.set(p))
                    self.root.after(0, lambda p=progress_percent: 
                                  self.progress_label.config(text=f"{p}% - 传输数据中"))
                    
                    # 日志记录（每10包记录一次，避免日志过多）
                    if (i + 1) % 10 == 0 or i + 1 == package_count:
                        self.root.after(0, lambda idx=i+1: 
                                      self.log(f"已发送 {idx}/{package_count} 包 ({int(idx/package_count*100)}%)"))
                    
                    # 小延迟，避免通信过载
                    #time.sleep(0.01)
                
                if not success:
                    self.root.after(0, lambda: self.write_status_var.set("数据发送失败"))
                    return
                
                # 检查是否已取消
                if self.stop_flag:
                    self.root.after(0, lambda: self.log("刷写操作已取消"))
                    self.root.after(0, lambda: self.write_status_var.set("已取消"))
                    return
                
                # 3. 发送OTA结束通知
                self.root.after(0, lambda: self.log("数据传输完成，发送OTA结束通知..."))
                self.root.after(0, lambda: self.progress_label.config(text="95% - 发送OTA结束通知"))
                if not self.can_communicator.send_ota_end():
                    self.root.after(0, lambda: self.log("发送OTA结束通知失败: 电机响应超时"))
                    self.root.after(0, lambda: self.write_status_var.set("OTA结束通知失败"))
                    return
                
                # 刷写成功
                self.root.after(0, lambda: self.log("固件刷写成功完成！"))
                self.root.after(0, lambda: self.write_status_var.set("刷写成功"))
                self.root.after(0, lambda: self.progress_var.set(100))
                self.root.after(0, lambda: self.progress_label.config(text="100% - 刷写成功"))
                
                # 重置状态，允许重新刷写
                def reset_after_delay():
                    self.is_erased = False
                    self.erase_status_var.set("未擦除")
                    self.flash_erase_btn.config(state=tk.NORMAL)
                
                # 延迟2秒后重置状态
                self.root.after(2000, reset_after_delay)
                
            except Exception as e:
                if not self.stop_flag:  # 只有在未取消的情况下才显示错误
                    error_msg = f"固件刷写过程异常: {str(e)}"
                    self.root.after(0, lambda msg=error_msg: self.log(msg))
                    self.root.after(0, lambda: self.write_status_var.set("刷写异常"))
            finally:
                # 确保状态正确重置
                self.is_flashing = False
                # 捕获success变量的值，避免闭包作用域问题
                success_value = success if 'success' in locals() else False
                def update_ui_final():
                    self.flash_write_btn.config(state=tk.NORMAL)
                    self.cancel_flash_btn.config(state=tk.DISABLED)
                    if not success_value and not self.stop_flag:
                        self.flash_erase_btn.config(state=tk.NORMAL)
                self.root.after(0, update_ui_final)
        
        # 启动刷写线程
        write_thread = threading.Thread(target=write_thread_func)
        write_thread.daemon = True
        write_thread.start()
    
    def toggle_auto_send(self):
        # 先获取复选框状态
        requested_state = self.auto_send_var.get()
        
        # 如果状态改变，才执行相应操作
        if requested_state != self.auto_send:
            self.auto_send = requested_state
            if self.auto_send:
                # 只在启用时设置频率，避免不必要的对话框
                try:
                    freq = int(self.freq_entry.get())
                    if 1 <= freq <= 50:
                        self.send_interval = 1000 / freq
                        self.actual_freq = freq
                except:
                    # 如果获取频率失败，使用默认值
                    self.send_interval = 20  # 默认20ms
                    self.actual_freq = 50
                    self.freq_entry.delete(0, tk.END)
                    self.freq_entry.insert(0, "50")
                
                # 启动自动发送
                self.start_auto_send()
            else:
                # 停止自动发送
                self.stop_auto_send()
    
    def set_send_frequency(self):
        try:
            freq = int(self.freq_entry.get())
            if 1 <= freq <= 50:  # 限制最高50Hz
                # 不使用int()截断，保留浮点数以提高高频时的精度
                self.send_interval = 1000 / freq  # 转换为毫秒
                self.actual_freq = freq  # 保存实际设置的频率值
                if self.auto_send:
                    # 避免直接重启，让现有定时器自然结束并在下一次迭代中使用新的间隔
                    pass  # 不再立即重启定时器，避免可能的竞争条件
            else:
                # 静默修正无效的频率值，不弹出对话框
                self.freq_entry.delete(0, tk.END)
                self.freq_entry.insert(0, "50")
                self.send_interval = 20
                self.actual_freq = 50
        except ValueError:
            # 静默修正无效的输入，不弹出对话框
            self.freq_entry.delete(0, tk.END)
            self.freq_entry.insert(0, "50")
            self.send_interval = 20
            self.actual_freq = 50
    
    def start_auto_send(self):
        if not self.auto_send:  # 首先检查是否仍然需要自动发送
            return
            
        # 清除可能存在的旧定时器
        if self.send_timer:
            try:
                self.root.after_cancel(self.send_timer)
                self.send_timer = None
            except:
                pass  # 忽略可能已过期的定时器
        
        # 发送MPC命令
        try:
            self.send_mpc_command()
        except Exception as e:
            print(f"发送MPC命令异常: {e}")
            self.auto_send = False
            self.auto_send_var.set(False)
            return
        
        # 只在auto_send为True时设置下一次定时器
        if self.auto_send:
            # 确保间隔至少为10ms，避免GUI卡死
            safe_interval = max(10, int(self.send_interval))
            self.send_timer = self.root.after(safe_interval, self.start_auto_send)
    
    def stop_auto_send(self):
        if self.send_timer:
            self.root.after_cancel(self.send_timer)
            self.send_timer = None

    def set_kp_kd(self):
        try:
            kp = self.kp_var.get()
            kd = self.kd_var.get()
            if KP_MIN <= kp <= KP_MAX and KD_MIN <= kd <= KD_MAX:
                self.can_comm.set_kp_kd(kp, kd)
            else:
                messagebox.showerror("错误", f"KP范围{KP_MIN}-{KP_MAX}, KD范围{KD_MIN}-{KD_MAX}")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def read_kp_kd(self):
        self.can_comm.read_kp_kd()

    def read_version(self):
        self.can_comm.read_version()

    def enable_motor(self, mode):
        self.can_comm.enable_motor(mode)
    
    def disable_motor(self):
        self.can_comm.disable_motor()
        
    def set_zero_offset(self):
        # 验证是否已选择电机
        if not hasattr(self, 'selected_motor_id') or self.selected_motor_id is None:
            messagebox.showerror("错误", "请先选择一个电机")
            return
            
        # 获取偏置值并验证
        try:
            offset_value = self.zero_offset_var.get()
            # 这里可以根据需要添加偏置值的范围验证
        except ValueError:
            messagebox.showerror("错误", "请输入有效的偏置值")
            return
            
        # 调用CANCommunicator的set_zero_offset方法
        self.can_comm.set_zero_offset(offset_value, self.selected_motor_id)
        
    def low_pass_filter(self, new_value, previous_value):
        """低通滤波函数
        new_value: 新的输入值
        previous_value: 上一次滤波后的值
        返回: 滤波后的值
        """
        # 首次初始化时直接返回新值
        if not self.filter_initialized:
            self.filter_initialized = True
            return new_value
        
        # 低通滤波公式: filtered = alpha * new_value + (1 - alpha) * previous_value
        return self.filter_alpha * new_value + (1 - self.filter_alpha) * previous_value
        
    def update_multi_motor_angle_label(self, value, label):
        """更新多电机控制中的角度标签显示"""
        # 将协议值转换为实际角度值
        proto_value = float(value)
        actual_angle = CANCommunicator.protocol_to_actual(proto_value, ANGLE_MIN, ANGLE_MAX)
        label.config(text=f"{actual_angle:.2f} rad")
        
    def send_multi_motor_command(self):
        """发送多电机控制指令"""
        # 获取滑动条的协议值并转换为实际角度值
        hip_proto_value = self.hip_angle_var.get()
        thigh_proto_value = self.thigh_angle_var.get()
        calf_proto_value = self.calf_angle_var.get()
        
        # 转换为实际角度值
        hip_angle = CANCommunicator.protocol_to_actual(hip_proto_value, ANGLE_MIN, ANGLE_MAX)
        thigh_angle = CANCommunicator.protocol_to_actual(thigh_proto_value, ANGLE_MIN, ANGLE_MAX)
        calf_angle = CANCommunicator.protocol_to_actual(calf_proto_value, ANGLE_MIN, ANGLE_MAX)
        
        # 应用低通滤波
        #self.filtered_hip_angle = self.low_pass_filter(hip_angle, self.filtered_hip_angle)
        #self.filtered_thigh_angle = self.low_pass_filter(thigh_angle, self.filtered_thigh_angle)
        #self.filtered_calf_angle = self.low_pass_filter(calf_angle, self.filtered_calf_angle)
        
        # 调用CAN通信方法发送指令
        self.can_comm.send_multi_motor_command(
            hip_angle, 
            thigh_angle, 
            calf_angle
        )
        
    def toggle_auto_report(self):
        # 获取复选框状态
        enable = self.auto_report_var.get()
        
        # 验证是否已选择电机
        if not hasattr(self, 'selected_motor_id') or self.selected_motor_id is None:
            messagebox.showerror("错误", "请先选择一个电机")
            self.auto_report_var.set(False)
            return
            
        # 验证频率输入
        try:
            frequency = int(self.freq_entry.get())
            if frequency < 0 or frequency > 1500:
                messagebox.showerror("错误", "频率必须在0-1500Hz之间")
                self.freq_entry.delete(0, tk.END)
                self.freq_entry.insert(0, "50")
                self.auto_report_var.set(False)
                return
        except ValueError:
            messagebox.showerror("错误", "请输入有效的频率值")
            self.freq_entry.delete(0, tk.END)
            self.freq_entry.insert(0, "50")
            self.auto_report_var.set(False)
            return
            
        # 发送自动上报命令到电机
        self.can_comm.toggle_auto_report(enable, frequency, self.selected_motor_id)

    def clear_fault(self):
        self.can_comm.clear_fault()
    
    def scan_serial_ports(self):
        """扫描可用的串口"""
        ports = serial.tools.list_ports.comports()
        port_list = []
        for port in ports:
            port_list.append(f"{port.device} - {port.description}")
        
        self.com_port_combo['values'] = port_list
        if port_list:
            self.com_port_combo.current(0)
        else:
            self.com_port_combo['values'] = ["未找到串口"]
            self.com_port_combo.current(0)
    
    def get_com_port(self):
        """获取选中的COM口"""
        selected = self.com_port_combo.get()
        if selected and selected != "未找到串口":
            if "COM" in selected.upper():
                match = re.search(r'COM(\d+)', selected.upper())
                if match:
                    return f"COM{match.group(1)}"
            return selected.split(" - ")[0]
        return None
    
    def toggle_plc_connection(self):
        """切换PLC连接状态"""
        if not self.plc_connected:
            self.connect_plc()
        else:
            self.disconnect_plc()
    
    def connect_plc(self):
        """连接PLC Modbus"""
        try:
            com_port = self.get_com_port()
            if not com_port or com_port == "未找到串口":
                messagebox.warning(self.root, "错误", "请选择有效的COM口")
                return
            
            baudrate = int(self.baudrate_combo.get())
            databits = int(self.databits_combo.get())
            parity_map = {"None": "N", "Even": "E", "Odd": "O"}
            parity = parity_map[self.parity_combo.get()]
            stopbits = int(self.stopbits_combo.get())
            
            # 创建Modbus串口客户端
            self.modbus_client = ModbusSerialClient(
                port=com_port,
                baudrate=baudrate,
                bytesize=databits,
                parity=parity,
                stopbits=stopbits,
                timeout=1
            )
            
            if self.modbus_client.connect():
                self.plc_connected = True
                self.plc_connect_btn.config(text="断开")
                self.plc_status_label.config(text="已连接", foreground="green")
                self.update_power_buttons_state()
            else:
                messagebox.warning(self.root, "错误", "无法连接到串口设备")
                self.modbus_client = None
                
        except Exception as e:
            messagebox.showerror("错误", f"PLC连接失败: {str(e)}")
            self.modbus_client = None
    
    def disconnect_plc(self):
        """断开PLC Modbus连接"""
        if self.modbus_client:
            self.modbus_client.close()
            self.modbus_client = None
        self.plc_connected = False
        self.plc_connect_btn.config(text="连接")
        self.plc_status_label.config(text="未连接", foreground="red")
        self.update_power_buttons_state()
    
    def update_power_buttons_state(self):
        """更新电源控制按钮状态"""
        state = "normal" if self.plc_connected else "disabled"
        self.power_btn1.config(state=state)
        self.power_btn2.config(state=state)
        self.power_btn3.config(state=state)
        self.power_btn4.config(state=state)
    
    def write_plc_register(self, address, value):
        """写入PLC寄存器或线圈"""
        if not self.plc_connected:
            messagebox.warning(self.root, "警告", "请先连接PLC设备")
            return
        
        try:
            device_id = int(self.device_id_var.get())
            register_type = self.register_type_var.get()
            
            # 转换为Modbus地址（从0开始）
            modbus_address = address - 1
            
            # 根据类型选择写入方式
            result = None
            if register_type == "线圈":
                bool_value = bool(value)
                result = self.modbus_client.write_coil(modbus_address, bool_value, device_id=device_id)
                actual_value = bool_value
            else:
                int_value = int(value)
                result = self.modbus_client.write_register(modbus_address, int_value, device_id=device_id)
                actual_value = int_value
            
            # 检查结果
            if result and not result.isError():
                pass  # 写入成功，不弹窗
            else:
                error_msg = str(result) if result else "未知错误"
                messagebox.showerror("错误", f"写入失败\n地址: {address}\n值: {value}\n错误: {error_msg}")
                
        except ValueError as e:
            messagebox.showerror("错误", f"参数错误: {str(e)}")
        except ModbusException as e:
            messagebox.showerror("错误", f"Modbus错误: {str(e)}")
        except Exception as e:
            messagebox.showerror("错误", f"写入异常: {str(e)}")
    
    def test_read_register(self):
        """测试读取寄存器（用于调试）"""
        if not self.plc_connected:
            messagebox.warning(self.root, "警告", "请先连接PLC设备")
            return
        
        try:
            device_id = int(self.device_id_var.get())
            register_type = self.register_type_var.get()
            
            # 测试读取地址2049, 2050, 2053, 2054
            test_addresses = [2049, 2050, 2053, 2054]
            results = []
            
            for address in test_addresses:
                modbus_address = address - 1
                try:
                    if register_type == "线圈":
                        result = self.modbus_client.read_coils(modbus_address, count=1, device_id=device_id)
                        if result and not result.isError():
                            value = result.bits[0] if result.bits else None
                            results.append(f"地址 {address:05d}: <{1 if value else 0}>")
                        else:
                            error_msg = str(result) if result else "未知错误"
                            results.append(f"地址 {address:05d}: 读取失败 - {error_msg}")
                    else:
                        result = self.modbus_client.read_holding_registers(modbus_address, count=1, device_id=device_id)
                        if result and not result.isError():
                            value = result.registers[0] if result.registers else None
                            results.append(f"地址 {address:05d}: <{value}>")
                        else:
                            error_msg = str(result) if result else "未知错误"
                            results.append(f"地址 {address:05d}: 读取失败 - {error_msg}")
                    time.sleep(0.05)
                except Exception as e:
                    results.append(f"地址 {address:05d}: 异常 - {str(e)}")
            
            result_text = "\n".join(results)
            messagebox.showinfo("测试读取结果", result_text)
            
        except Exception as e:
            messagebox.showerror("错误", f"测试读取异常: {str(e)}")
    
    def scan_pcan_devices(self):
        """扫描PCAN-USB设备"""
        # 简化版本，直接使用PCAN_USBBUS1
        if hasattr(self, 'pcan_device_combo'):
            self.pcan_device_combo['values'] = ["PCAN-USB1"]
            self.pcan_device_combo.current(0)
    
    def on_pcan_device_select(self, event):
        """PCAN设备选择事件"""
        pass
    
    def toggle_can_connection(self):
        """切换CAN连接状态"""
        if not self.can_connected:
            self.connect_can()
        else:
            self.disconnect_can()
    
    def connect_can(self):
        """连接PCAN设备"""
        try:
            if not self.can_comm.initialized:
                result = self.can_comm.init_can()
                if result:
                    self.can_connected = True
                    self.can_connect_btn.config(text="断开")
                    self.can_status_var.set("已连接")
                    self.can_status_label.config(foreground="green")
                else:
                    self.can_connected = False
                    self.can_status_var.set("连接失败")
                    self.can_status_label.config(foreground="red")
                    messagebox.showerror("错误", "PCAN连接失败")
            else:
                self.can_connected = True
                self.can_connect_btn.config(text="断开")
                self.can_status_var.set("已连接")
                self.can_status_label.config(foreground="green")
        except Exception as e:
            self.can_connected = False
            self.can_status_var.set("连接失败")
            self.can_status_label.config(foreground="red")
            messagebox.showerror("错误", f"PCAN连接失败: {str(e)}")
    
    def disconnect_can(self):
        """断开PCAN设备连接"""
        if self.can_comm.initialized:
            self.can_comm.running = False
            if self.can_comm.receive_thread:
                self.can_comm.receive_thread.join(timeout=1.0)
            self.can_comm.pcan.Uninitialize(self.can_comm.channel)
            self.can_comm.initialized = False
        
        self.can_connected = False
        self.can_connect_btn.config(text="连接")
        self.can_status_var.set("未连接")
        self.can_status_label.config(foreground="red")
    
    def reset_can_bus(self):
        """重置CAN总线"""
        if not self.can_connected:
            messagebox.warning(self.root, "警告", "请先连接PCAN设备")
            return
        
        if self.can_comm.initialized:
            self.can_comm.running = False
            if self.can_comm.receive_thread:
                self.can_comm.receive_thread.join(timeout=1.0)
            self.can_comm.pcan.Uninitialize(self.can_comm.channel)
            self.can_comm.initialized = False
            time.sleep(0.1)
        
        result = self.can_comm.init_can()
        if result:
            messagebox.showinfo("成功", "CAN总线重置成功")
        else:
            messagebox.showerror("错误", "CAN总线重置失败")
    
    def search_motors_can(self):
        """搜索电机（CAN版本）- 参考搜索设备模块的方式"""
        if not self.can_connected:
            messagebox.warning(self.root, "警告", "请先连接PCAN设备")
            return
        
        # 清空下拉框
        self.motor_can_combo['values'] = []
        self.motor_can_var.set("")
        self.can_comm.discovered_motors = []
        
        # 在新线程中搜索
        threading.Thread(target=self._search_motors_thread, daemon=True).start()
    
    def _search_motors_thread(self):
        """搜索电机线程"""
        found_motors = self.can_comm.search_motors()
        time.sleep(3.0)  # 等待响应（延长到3秒）
        
        if self.can_comm.discovered_motors:
            # 参考搜索设备模块的格式：f"{mid} ({uid})"
            motors = [f"{mid} ({uid})" for mid, uid in self.can_comm.discovered_motors]
            self.root.after(0, lambda m=motors: self.motor_can_combo.config(values=m))
        else:
            self.root.after(0, lambda: messagebox.showwarning("警告", "未搜索到电机"))
    
    def on_motor_select_can(self, event):
        """选择电机（CAN版本）- 参考搜索设备模块的方式"""
        selected = self.motor_can_var.get()
        if selected:
            try:
                # 解析格式："ID (unique_id)" -> 提取ID
                motor_id = int(selected.split()[0])
                self.can_comm.current_motor_id = motor_id
                # 同时设置self.selected_motor_id，确保自动上报功能能正确检测
                self.selected_motor_id = motor_id
            except (ValueError, IndexError):
                # 静默处理解析错误
                pass
    
    def toggle_motor(self):
        """使能/禁能电机"""
        if not self.can_connected:
            messagebox.showwarning("警告", "请先连接PCAN设备")
            return
        
        if not self.can_comm.current_motor_id:
            messagebox.showwarning("警告", "请先选择电机")
            return
        
        if not self.motor_enabled:
            # 使能电机
            threading.Thread(target=self._enable_motor_thread, daemon=True).start()
        else:
            # 禁能电机
            threading.Thread(target=self._disable_motor_thread, daemon=True).start()
    
    def _enable_motor_thread(self):
        """使能电机线程"""
        success, error = self.can_comm.enable_motor(mode=1)  # 模式1=运控
        
        if success:
            self.motor_enabled = True
            self.root.after(0, lambda: self.enable_button.config(text="禁能电机"))
        else:
            error_msg = error if error else "使能失败"
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("错误", msg))
    
    def _disable_motor_thread(self):
        """禁能电机线程"""
        # 停止PI控制
        if self.pi_control_running:
            self.pi_control_running = False
            if self.pi_control_thread:
                self.pi_control_thread.join(timeout=1.0)
            self.can_comm.send_mpc_command(0.0, 0.0, 0.0)
        
        success, error = self.can_comm.disable_motor()
        
        if success:
            self.motor_enabled = False
            self.root.after(0, lambda: self.enable_button.config(text="使能电机"))
            # 停止发送控制命令
            self.can_comm.send_mpc_command(0.0, 0.0, 0.0)
        else:
            error_msg = error if error else "禁能失败"
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("错误", msg))
    
    def set_target_speed(self):
        """设定目标速度"""
        try:
            target_speed = float(self.target_speed_var.get())
            with self.pi_control_lock:
                self.target_speed = target_speed
            print(f"目标速度已设定为: {target_speed} rad/s")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的速度值")
    
    def toggle_pi_control(self):
        """启动/停止PI控制"""
        if not self.pi_control_running:
            # 启动PI控制
            if not self.can_comm.current_motor_id:
                messagebox.showerror("错误", "请先选择要控制的电机")
                return
            
            # 重置积分项
            with self.pi_control_lock:
                self.sumerror_spd = 0.0
            
            self.pi_control_running = True
            self.pi_control_btn.config(text="停止PI控制")
            
            # 启动PI控制线程
            self.pi_control_thread = threading.Thread(target=self.pi_control_loop)
            self.pi_control_thread.daemon = True
            self.pi_control_thread.start()
            print("PI控制已启动（200Hz）")
        else:
            # 停止PI控制
            self.pi_control_running = False
            self.pi_control_btn.config(text="启动PI控制")
            print("PI控制已停止")
    
    def extend_leg(self):
        """伸腿：设置目标速度为1，启动PI控制3秒"""
        if not self.can_comm.current_motor_id:
            messagebox.showerror("错误", "请先选择要控制的电机")
            return
        
        # 如果PI控制正在运行，先停止
        if self.pi_control_running:
            self.pi_control_running = False
            time.sleep(0.1)  # 等待线程停止
        
        # 设置目标速度为1
        with self.pi_control_lock:
            self.target_speed = 1.0
            self.sumerror_spd = 0.0  # 重置积分项
        
        # 更新UI显示
        self.target_speed_var.set("1.0")
        
        # 启动PI控制
        self.pi_control_running = True
        self.pi_control_btn.config(text="停止PI控制")
        
        # 启动PI控制线程
        self.pi_control_thread = threading.Thread(target=self.pi_control_loop)
        self.pi_control_thread.daemon = True
        self.pi_control_thread.start()
        
        print("伸腿：PI控制已启动，目标速度1.0 rad/s")
        
        # 3秒后自动停止
        def stop_after_3s():
            time.sleep(3.0)
            if self.pi_control_running:
                self.pi_control_running = False
                self.root.after(0, lambda: self.pi_control_btn.config(text="启动PI控制"))
                print("伸腿：PI控制已自动停止（3秒）")
        
        threading.Thread(target=stop_after_3s, daemon=True).start()
    
    def kick_leg(self):
        """踢腿：设置目标速度为-1，启动PI控制3秒"""
        if not self.can_comm.current_motor_id:
            messagebox.showerror("错误", "请先选择要控制的电机")
            return
        
        # 如果PI控制正在运行，先停止
        if self.pi_control_running:
            self.pi_control_running = False
            time.sleep(0.1)  # 等待线程停止
        
        # 设置目标速度为-1
        with self.pi_control_lock:
            self.target_speed = -1.0
            self.sumerror_spd = 0.0  # 重置积分项
        
        # 更新UI显示
        self.target_speed_var.set("-1.0")
        
        # 启动PI控制
        self.pi_control_running = True
        self.pi_control_btn.config(text="停止PI控制")
        
        # 启动PI控制线程
        self.pi_control_thread = threading.Thread(target=self.pi_control_loop)
        self.pi_control_thread.daemon = True
        self.pi_control_thread.start()
        
        print("踢腿：PI控制已启动，目标速度-1.0 rad/s")
        
        # 3秒后自动停止
        def stop_after_3s():
            time.sleep(3.0)
            if self.pi_control_running:
                self.pi_control_running = False
                self.root.after(0, lambda: self.pi_control_btn.config(text="启动PI控制"))
                print("踢腿：PI控制已自动停止（3秒）")
        
        threading.Thread(target=stop_after_3s, daemon=True).start()
    
    def pi_control_loop(self):
        """PI控制循环，以200Hz频率运行"""
        # 200Hz = 每5ms执行一次
        control_interval = 1.0 / 200.0  # 5ms
        
        while self.pi_control_running:
            loop_start_time = time.time()
            
            try:
                # 获取当前速度和目标速度（线程安全）
                with self.pi_control_lock:
                    current_speed = self.current_speed
                    target_speed = self.target_speed
                
                # 计算速度误差
                errspd = target_speed - current_speed
                
                # 更新积分项：sumerror_spd += 0.05 * errspd
                with self.pi_control_lock:
                    self.sumerror_spd += 0.05 * errspd
                    sumerror_spd = self.sumerror_spd
                
                # 计算扭矩：tor = 0.1 * errspd + 0.05 * sumerror_spd
                tor = 0.1 * errspd + 0.05 * sumerror_spd
                
                # 限制扭矩在有效范围内
                tor = max(-3, min(3, tor))
                
                # 发送MPC命令（使用当前角度，保持角度不变，速度设为0，只控制扭矩）
                self.can_comm.send_mpc_command(0.0, 0.0, tor)
                
            except Exception as e:
                print(f"PI控制循环异常: {e}")
            
            # 计算执行时间，确保以200Hz频率运行
            elapsed_time = time.time() - loop_start_time
            sleep_time = max(0, control_interval - elapsed_time)
            if sleep_time > 0:
                time.sleep(sleep_time)
        self.can_comm.send_mpc_command(0.0, 0.0, 0.0)
    def update_scope(self):
        """更新示波器显示"""
        show_flags = {
            'angle': self.show_angle.get(),
            'speed': self.show_speed.get(),
            'torque': self.show_torque.get(),
            'temp': self.show_temp.get()
        }
        self.oscilloscope.update_plot(show_flags, self.points_var.get())
    
    def update_self_check_scope(self):
        """更新自检示波器显示"""
        try:
            show_flags = {
                'current_a': self.show_current_a.get(),
                'current_b': self.show_current_b.get(),
                'current_c': self.show_current_c.get(),
                'main_angle': self.show_main_angle.get(),
                'sub_angle': self.show_sub_angle.get()
            }
            self.self_check_oscilloscope.update_plot(show_flags, self.self_check_points_var.get())
            # 显式刷新canvas以确保显示更新
            if hasattr(self, 'self_check_canvas'):
                self.self_check_canvas.draw_idle()  # 使用draw_idle代替draw，减轻UI负担
        except Exception:
            # 静默处理异常，避免GUI线程崩溃
            pass

    def update_gui(self):
        # 性能调试变量
        if not hasattr(self, '_perf_stats'):
            self._perf_stats = {
                'last_update_time': time.time(),
                'data_count': 0,
                'plot_count': 0,
                'last_log_time': time.time()
            }
        
        # 处理电机发现（已移除顶部搜索设备控件，此部分不再需要）
        while not motor_queue.empty():
            try:
                motor_queue.get_nowait()
            except queue.Empty:
                pass

        # 处理反馈数据
        try:
            # 限制一次处理的数据量，避免长时间阻塞GUI线程
            processed_count = 0
            max_processed = 50  # 每次循环最多处理50条数据
            need_redraw = False
            
            while not data_queue.empty() and processed_count < max_processed:
                try:
                    feedback = data_queue.get_nowait()
                    self.oscilloscope.update_data(feedback)
                    need_redraw = True  # 标记需要重绘
                    
                    # 新增：更新状态和故障显示
                    status_code = feedback.get('status', -1)
                    fault_code = feedback.get('fault', -1)
                    self.status_display.config(text=self.status_map.get(status_code, f"未知({status_code})"))
                    self.fault_display.config(text=self.fault_map.get(fault_code, f"无" if fault_code == 0 else f"未知({fault_code})"))
                    
                    # 新增：更新当前速度和角度（用于PI控制）
                    current_speed = feedback.get('speed', 0.0)
                    current_angle = feedback.get('angle', 0.0)
                    with self.pi_control_lock:
                        self.current_speed = current_speed
                        self.current_angle = current_angle
                    # 更新UI显示
                    self.current_speed_label.config(text=f"{current_speed:.2f}")
                    
                    processed_count += 1
                    self._perf_stats['data_count'] += 1
                except queue.Empty:
                    break
            
            # 只在有新数据时更新绘图
            if need_redraw:
                start_time = time.time()
                self.oscilloscope.update_plot(
                    {
                        'angle': self.show_angle.get(),
                        'speed': self.show_speed.get(),
                        'torque': self.show_torque.get(),
                        'temperature': self.show_temp.get()
                    },
                    self.points_var.get()
                )
                plot_time = time.time() - start_time
                self._perf_stats['plot_count'] += 1
                
                # 每秒打印一次性能统计
                current_time = time.time()
                if current_time - self._perf_stats['last_log_time'] >= 1.0:
                    data_rate = self._perf_stats['data_count'] / (current_time - self._perf_stats['last_log_time'])
                    update_rate = self._perf_stats['plot_count'] / (current_time - self._perf_stats['last_log_time'])
                    print(f"性能统计 - 数据处理率: {data_rate:.1f}Hz, 绘图更新率: {update_rate:.1f}Hz, 单次绘图耗时: {plot_time*1000:.2f}ms")
                    self._perf_stats['data_count'] = 0
                    self._perf_stats['plot_count'] = 0
                    self._perf_stats['last_log_time'] = current_time
                    
        except Exception as e:
            # 静默处理异常，避免GUI线程崩溃
            print(f"GUI更新异常: {e}")

        # 处理响应消息（移除弹窗）
        while not response_queue.empty():
            try:
                resp = response_queue.get_nowait()
                # 移除所有弹窗，但保留必要的数据更新
                if resp[0] == "version":
                    self.version_label.config(text=resp[1])
                elif resp[0] == "kp":
                    self.kp_var.set(resp[1])
                elif resp[0] == "kd":
                    self.kd_var.set(resp[1])
                # 错误和响应消息不显示弹窗
            except queue.Empty:
                pass
        
        # 处理自检数据
        try:
            # 限制一次处理的数据量，避免长时间阻塞GUI线程
            processed_count = 0
            max_processed = 50  # 每次循环最多处理50条数据
            
            while not self_check_queue.empty() and processed_count < max_processed:
                try:
                    raw_data = self_check_queue.get_nowait()
                    
                    # 更新自检示波器数据
                    self.self_check_oscilloscope.update_data(raw_data)
                    processed_count += 1
                except queue.Empty:
                    break
                except Exception:
                    # 静默处理单个数据处理异常
                    pass
            
            # 检查是否正在显示自检页面
            is_self_check_page_selected = False
            if hasattr(self, 'notebook') and hasattr(self, 'self_check_page'):
                try:
                    selected_tab = self.notebook.select()
                    self_check_page_str = str(self.self_check_page)
                    is_self_check_page_selected = (selected_tab == self_check_page_str)
                except:
                    pass
            
            # 无论是否在自检页面，只要有数据就更新自检示波器的显示
            # 这样与普通示波器的行为保持一致
            if processed_count > 0:
                self.update_self_check_scope()
        except Exception:
            # 静默处理整体自检数据处理异常
            pass

        self.root.after(10, self.update_gui)

if __name__ == "__main__":
    root = tk.Tk()
    app = MotorControlGUI(root)
    root.mainloop()
