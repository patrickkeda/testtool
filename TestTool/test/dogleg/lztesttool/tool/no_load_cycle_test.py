import sys
import os
import math
import threading
import time
import queue
import struct
import tkinter as tk
from tkinter import ttk, messagebox

# 优先从脚本所在目录加载 PCANBasic（便于随程序一起拷贝到其他电脑）
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from PCANBasic import *

# 全局常量
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

# 参数地址
ADDR_KP = 0x1005
ADDR_KD = 0x1006
ADDR_ZERO_OFFSET = 0x1007  # 零位偏移地址

# 响应类型
RESPONSE_SUCCESS = 0x00
RESPONSE_ERROR = 0x01
RESPONSE_TIMEOUT = 0x02

class ModifiedCANCommunicator:
    """修改版CAN通信类，支持搜索电机"""
    def __init__(self):
        self.pcan = PCANBasic()
        self.channel = PCAN_USBBUS1
        self.is_fd = False
        self.bitrate = PCAN_BAUD_1M
        self.initialized = False
        self.current_motor_id = None
        
        # 电机搜索相关
        self.discovered_motors = []
        self.running = False
        self.receive_thread = None
        
        # 故障码按位定义映射表
        self.fault_bit_map = {
            0: "过载",
            1: "过流",
            2: "过温",
            3: "欠压",
            4: "过压",
            5: "编码器故障",
            6: "过载预警",
            7: "默认位(1)"
        }

    def init_can(self):
        """初始化CAN总线，启动接收线程"""
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
                return False, f"CAN总线初始化失败：{err_msg}"
        except Exception as e:
            return False, f"CAN库加载失败：{str(e)}"
    
    def receive_loop(self):
        """接收CAN消息循环，只处理电机发现消息"""
        while self.running and self.initialized:
            try:
                sts, msg, timestamp = self.pcan.Read(self.channel)
                if sts == PCAN_ERROR_OK:
                    self.parse_message(msg)
                elif sts != PCAN_ERROR_QRCVEMPTY:
                    try:
                        err_msg = self.pcan.GetErrorText(sts, 0x09)[1].decode('utf-8')
                        print(f"接收错误：{err_msg}")
                    except Exception:
                        print(f"接收错误：{sts}")
            except Exception as e:
                print(f"接收线程异常：{str(e)}")
    
    def parse_message(self, msg):
        """解析CAN消息，只处理电机发现响应"""
        try:
            msg_type = int(msg.MSGTYPE)
            msg_id = int(msg.ID)
            msg_len = int(msg.LEN)
            
            # 检查是否为扩展帧
            is_extended = (msg_type & PCAN_MESSAGE_EXTENDED.value) != 0
            
            if is_extended:
                # 解析29位ID
                bit28_24 = (msg_id >> 24) & 0x1F  # Bit28~24
                bit23_8 = (msg_id >> 8) & 0xFFFF  # bit23~8
                bit7_0 = msg_id & 0xFF  # bit7~0
                
                # 处理自研电机发现应答（原协议）
                func_code = (msg_id >> 16) & 0xFF  # 功能码
                dir_bit = (msg_id >> 24) & 0x1F
                motor_id = (msg_id >> 8) & 0xFF  # 电机ID在15-8位
                
                # 设备发现应答 - 自研电机
                if dir_bit == 0x01 and func_code == 0x00:
                    unique_id = ''.join(f"{byte:02X}" for byte in msg.DATA[:8])
                    if (motor_id, unique_id) not in self.discovered_motors:
                        self.discovered_motors.append((motor_id, unique_id))
                
                # 设备发现应答 - 灵足电机
                # 根据协议：bit28~24=0x0, bit7~0=0xFE, bit23~8是目标电机CAN_ID
                elif bit28_24 == 0x00 and bit7_0 == 0xFE:
                    target_motor_id = bit23_8  # bit23~8是目标电机CAN_ID
                    unique_id = ''.join(f"{byte:02X}" for byte in msg.DATA[:8])
                    if (target_motor_id, unique_id) not in self.discovered_motors:
                        self.discovered_motors.append((target_motor_id, unique_id))
        except Exception as e:
            print(f"解析消息异常: {e}")

    def set_motor_id(self, motor_id):
        """设置当前电机ID"""
        self.current_motor_id = motor_id
    
    def search_motors(self):
        """搜索电机"""
        if not self.initialized:
            if isinstance(self.init_can(), tuple):
                success, error_msg = self.init_can()
                if not success:
                    return []
        
        # 清空之前的发现结果
        self.discovered_motors = []
        
        # 批量处理CAN消息发送，减少循环中的延迟
        batch_size = 1
        
        for batch_start in range(1, 128, batch_size):
            batch_end = min(batch_start + batch_size - 1, 127)
            
            for can_id in range(batch_start, batch_end + 1):
                try:
                    msg = TPCANMsg()
                    msg.ID = (0x00 << 24) | (0x00 << 16) | (can_id)  # 仅保留ID的低16位
                    msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value  # 扩展帧
                    msg.LEN = 8
                    msg.DATA = (c_ubyte * 8)(*[0x00]*8)
                    
                    # 发送消息
                    self.pcan.Write(self.channel, msg)
                except Exception:
                    # 静默处理发送错误
                    pass
            
            # 批次间使用更短的延迟
            if batch_end < 127:
                time.sleep(0.002)  # 减少为2ms
        
        # 等待电机响应
        time.sleep(0.5)
        
        # 返回发现的电机ID列表
        return [motor[0] for motor in self.discovered_motors]

    def actual_to_protocol(self, value, min_val, max_val):
        """将实际值转换为协议值"""
        return int(((value - min_val) / (max_val - min_val)) * PROTOCOL_MAX)

    def enable_motor_self_made(self, motor_id, mode=1):
        """启用自研电机"""
        if not self.initialized:
            return False
        
        try:
            msg = TPCANMsg()
            msg.ID = (0x00 << 24) | (0x04 << 16) | (0x00 << 8) | motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            msg.DATA = (c_ubyte * 8)(mode, *[0x00]*7)
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            return False
    
    def enable_motor_robstride(self, motor_id, mode=1):
        """启用灵足电机（通信类型3：电机使能运行）"""
        if not self.initialized:
            return False
        
        try:
            # 灵足电机协议：29位ID，Bit28~bit24=0x3，bit7~0=目标电机CAN_ID
            # bit23~8: bit15~8用来标识主机CAN_ID（这里使用0x0000）
            host_can_id = 0x0000  # 主机CAN_ID，这里使用默认值0x0000
            
            msg = TPCANMsg()
            msg.ID = (0x03 << 24) | (host_can_id << 8) | motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            msg.DATA = (c_ubyte * 8)(*[0x00]*8)  # 数据区为8个0
            
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            print(f"启用灵足电机异常: {str(e)}")
            return False
    
    def enable_motor(self, motor_id, mode=1, is_robstride=False):
        """启用电机（统一接口）"""
        if is_robstride:
            return self.enable_motor_robstride(motor_id, mode)
        else:
            return self.enable_motor_self_made(motor_id, mode)
    
    def disable_motor_self_made(self, motor_id):
        """禁用自研电机"""
        if not self.initialized:
            return False
        
        try:
            msg = TPCANMsg()
            msg.ID = (0x00 << 24) | (0x05 << 16) | (0x00 << 8) | motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            msg.DATA = (c_ubyte * 8)(0x00, *[0x00]*7)
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            return False
    
    def disable_motor_robstride(self, motor_id):
        """禁用灵足电机（通信类型4：电机停止运行）"""
        if not self.initialized:
            return False
        
        try:
            # 灵足电机协议：29位ID，Bit28~bit24=0x4，bit7~0=目标电机CAN_ID
            # bit23~8: 未明确使用，这里使用0x0000
            unused_bits = 0x0000  # bit23~8未明确使用，使用默认值0x0000
            
            msg = TPCANMsg()
            msg.ID = (0x04 << 24) | (unused_bits << 8) | motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            msg.DATA = (c_ubyte * 8)(*[0x00]*8)  # 数据区为8个0
            
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            print(f"禁用灵足电机异常: {str(e)}")
            return False
    
    def disable_motor(self, motor_id, is_robstride=False):
        """禁用电机（统一接口）"""
        if is_robstride:
            return self.disable_motor_robstride(motor_id)
        else:
            return self.disable_motor_self_made(motor_id)

    def send_param_write_self_made(self, addr, data):
        """发送自研电机参数写入命令"""
        if not self.initialized or not self.current_motor_id:
            return False
        
        try:
            msg = TPCANMsg()
            msg.ID = (0x00 << 24) | (0x03 << 16) | (0x00 << 8) | self.current_motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            
            # 构造数据
            msg.DATA = (c_ubyte * 8)(
                addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF, (addr >> 24) & 0xFF,
                data[0], data[1], data[2], data[3]
            )
            
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            return False
    
    def send_param_write_robstride(self, addr, data):
        """发送灵足电机参数写入命令"""
        return True
    
    def send_param_write(self, addr, data, is_robstride=False):
        """发送参数写入命令（统一接口）"""
        if is_robstride:
            return self.send_param_write_robstride(addr, data)
        else:
            return self.send_param_write_self_made(addr, data)

    def set_zero_offset_self_made(self, offset, motor_id):
        """设置自研电机零位偏移"""
        if not self.initialized:
            return False
        
        try:
            # 将偏移量转换为4字节数据
            data = struct.pack('<f', offset)
            
            msg = TPCANMsg()
            msg.ID = (0x00 << 24) | (0x07 << 16) | (0x00 << 8) | motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            
            # 构造数据
            msg.DATA = (c_ubyte * 8)(
                ADDR_ZERO_OFFSET & 0xFF, (ADDR_ZERO_OFFSET >> 8) & 0xFF, 
                (ADDR_ZERO_OFFSET >> 16) & 0xFF, (ADDR_ZERO_OFFSET >> 24) & 0xFF,
                data[0], data[1], data[2], data[3]
            )
            
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            return False
    
    def set_zero_offset_robstride(self, offset, motor_id):
        """设置灵足电机零位偏移（通信类型6：设置电机机械零位）"""
        if not self.initialized:
            return False
        
        try:
            # 灵足电机协议：29位ID，Bit28~bit24=0x6，bit7~0=目标电机CAN_ID
            # bit23~8: bit15~8用来标识主机CAN_ID（这里使用0x0000）
            host_can_id = 0x0000  # 主机CAN_ID，这里使用默认值0x0000
            
            msg = TPCANMsg()
            msg.ID = (0x06 << 24) | (host_can_id << 8) | motor_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            
            # 数据区：Byte0=1，其余为0
            msg.DATA = (c_ubyte * 8)(1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
            
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            print(f"设置灵足电机零位异常: {str(e)}")
            return False
    
    def set_zero_offset(self, offset, motor_id, is_robstride=False):
        """设置零位偏移（统一接口）"""
        if is_robstride:
            return self.set_zero_offset_robstride(offset, motor_id)
        else:
            return self.set_zero_offset_self_made(offset, motor_id)

    def send_mpc_command_self_made(self, angle, speed, torque):
        """发送自研电机MPC命令"""
        if not self.initialized or not self.current_motor_id:
            return False
        
        try:
            proto_angle = self.actual_to_protocol(angle, ANGLE_MIN, ANGLE_MAX)
            proto_speed = self.actual_to_protocol(speed, SPEED_MIN, SPEED_MAX)
            proto_torque = self.actual_to_protocol(torque, TORQUE_MIN, TORQUE_MAX)
            
            msg = TPCANMsg()
            msg.ID = (0x02 << 8) | self.current_motor_id
            msg.MSGTYPE = PCAN_MESSAGE_STANDARD.value
            msg.LEN = 6
            msg.DATA = (c_ubyte * 8)(
                (proto_angle) & 0xFF, (proto_angle >> 8) & 0xFF,
                (proto_speed) & 0xFF, (proto_speed >> 8) & 0xFF,
                (proto_torque) & 0xFF, (proto_torque >> 8) & 0xFF,
                0x00, 0x00
            )
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            return False

    def send_mpc_command_robstride(self, angle, speed, torque):
        """发送灵足电机MPC命令"""
        if not self.initialized or not self.current_motor_id:
            return False
        
        try:
            # 灵足电机协议：29位ID，Bit28~bit24=0x1，bit7~0=目标电机CAN_ID
            # 数据区：
            # Byte0~1: 目标角度 (0~65535)对应(-4π~4π)
            # Byte2~3: 目标角速度 (0~65535)对应(-44rad/s~44rad/s)
            # Byte4~5: Kp (0~65535)对应(0.0~500.0)
            # Byte6~7: Kd (0~65535)对应(0.0~5.0)
            # 所有数据为大端格式（高字节在前，低字节在后）
            
            # 计算协议值
            # 角度：-4π~4π 映射到 0~65535
            angle_min = -4 * math.pi
            angle_max = 4 * math.pi
            proto_angle = self.actual_to_protocol(angle, angle_min, angle_max)
            
            # 速度：-44rad/s~44rad/s 映射到 0~65535
            speed_min = -44.0
            speed_max = 44.0
            proto_speed = self.actual_to_protocol(speed, speed_min, speed_max)
            
            # 扭矩：-17Nm~17Nm 映射到 0~65535 (在ID的bit23~8位)
            torque_min = -17.0
            torque_max = 17.0
            proto_torque = self.actual_to_protocol(torque, torque_min, torque_max)
            
            # Kp：0.0~500.0 映射到 0~65535
            kp_value = 30.0  # 默认值30
            kp_min = 0.0
            kp_max = 500.0
            proto_kp = self.actual_to_protocol(kp_value, kp_min, kp_max)
            
            # Kd：0.0~5.0 映射到 0~65535
            kd_value = 1.0  # 默认值1
            kd_min = 0.0
            kd_max = 5.0
            proto_kd = self.actual_to_protocol(kd_value, kd_min, kd_max)
            
            # 构建29位ID
            # Bit28~24=0x1, bit23~8=proto_torque, bit7~0=目标电机CAN_ID
            msg_id = (0x01 << 24) | (proto_torque << 8) | self.current_motor_id
            
            msg = TPCANMsg()
            msg.ID = msg_id
            msg.MSGTYPE = PCAN_MESSAGE_EXTENDED.value
            msg.LEN = 8
            
            # 数据区为大端格式（高字节在前，低字节在后）
            msg.DATA = (c_ubyte * 8)(
                (proto_angle >> 8) & 0xFF, (proto_angle) & 0xFF,  # 角度大端
                (proto_speed >> 8) & 0xFF, (proto_speed) & 0xFF,  # 速度大端
                (proto_kp >> 8) & 0xFF, (proto_kp) & 0xFF,        # Kp大端
                (proto_kd >> 8) & 0xFF, (proto_kd) & 0xFF         # Kd大端
            )
            
            self.pcan.Write(self.channel, msg)
            return True
        except Exception as e:
            print(f"发送灵足电机MPC命令异常: {str(e)}")
            return False

class NoLoadCycleTest:
    """空载周期测试应用"""
    def __init__(self, root):
        self.root = root
        self.root.title("空载周期测试")
        self.root.geometry("450x350")
        self.root.resizable(False, False)
        
        # 当前状态变量
        self.current_motor_id = tk.StringVar(value="1")
        self.current_process = tk.StringVar(value="空闲")
        self.is_running = False
        self.mpc_thread = None
        
        # 电机类型选择
        self.is_robstride_motor = tk.BooleanVar(value=False)
        
        # 电机ID选择相关
        self.found_motors = []
        self.motor_id_var = tk.StringVar(value="")
        self.motor_id_list = None
        
        # 初始化CAN通信
        self.can_comm = ModifiedCANCommunicator()
        init_result = self.can_comm.init_can()
        if isinstance(init_result, tuple):
            success, error_msg = init_result
            if not success:
                messagebox.showerror("错误", error_msg)
                self.root.quit()
        
        self.create_layout()
        
        # 绑定电机ID选择事件
        self.motor_id_list.bind("<<ComboboxSelected>>", self.on_motor_id_selected)
    
    def create_layout(self):
        """创建GUI布局"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 电机ID搜索和选择
        ttk.Label(main_frame, text="电机ID:").grid(row=0, column=0, padx=5, pady=10, sticky=tk.E)
        self.motor_id_list = ttk.Combobox(main_frame, textvariable=self.motor_id_var, state="readonly", width=10)
        self.motor_id_list.grid(row=0, column=1, padx=5, pady=10, sticky=tk.W)
        search_button = ttk.Button(main_frame, text="搜索电机", command=self.search_motors, width=10)
        search_button.grid(row=0, column=2, padx=5, pady=10, sticky=tk.W)
        
        # 电机类型选择
        ttk.Checkbutton(main_frame, text="灵足电机", variable=self.is_robstride_motor).grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky=tk.W)
        
        # 状态显示
        ttk.Label(main_frame, text="当前状态:").grid(row=2, column=0, padx=5, pady=10, sticky=tk.E)
        ttk.Label(main_frame, textvariable=self.current_process).grid(row=2, column=1, padx=5, pady=10, sticky=tk.W)
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=20)
        
        # 开始按钮
        self.start_button = ttk.Button(button_frame, text="开始测试", command=self.start_test, width=15)
        self.start_button.pack(side=tk.LEFT, padx=10)
        
        # 停止按钮
        self.stop_button = ttk.Button(button_frame, text="停止测试", command=self.stop_test, width=15, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=10)
    
    def start_test(self):
        """开始测试"""
        try:
            motor_id = int(self.current_motor_id.get())
            if motor_id < 1 or motor_id > 127:
                messagebox.showerror("错误", "电机ID必须在1-127之间")
                return
            
            self.current_process.set("准备中...")
            
            # 设置当前电机ID
            self.can_comm.set_motor_id(motor_id)
            
            # 1. 设置当前角度为0位
            if not self.set_zero_offset(0.0, motor_id):
                messagebox.showerror("错误", "设置零位失败")
                self.current_process.set("空闲")
                return
            self.current_process.set("零位已设置...")
            time.sleep(0.1)
            
            # 2. 设置KP=30, KD=1
            # 设置KP
            kp_value = 30.0
            kp_bytes = struct.pack('<f', kp_value)
            if not self.send_param_write(ADDR_KP, kp_bytes):
                messagebox.showerror("错误", "设置KP失败")
                self.current_process.set("空闲")
                return
            
            # 设置KD
            kd_value = 1.0
            kd_bytes = struct.pack('<f', kd_value)
            if not self.send_param_write(ADDR_KD, kd_bytes):
                messagebox.showerror("错误", "设置KD失败")
                self.current_process.set("空闲")
                return
            
            self.current_process.set("参数已设置...")
            time.sleep(0.1)
            
            # 3. 使能电机
            if not self.enable_motor(motor_id):
                messagebox.showerror("错误", "电机使能失败")
                self.current_process.set("空闲")
                return
            
            # 4. 启动MPC发送线程
            self.is_running = True
            self.mpc_thread = threading.Thread(target=self.send_mpc_thread)
            self.mpc_thread.daemon = True
            self.mpc_thread.start()
            
            # 更新UI状态
            self.current_process.set("运行中")
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            
        except ValueError:
            messagebox.showerror("错误", "电机ID必须是数字")
        except Exception as e:
            messagebox.showerror("错误", f"开始测试失败：{str(e)}")
            self.current_process.set("空闲")
    
    def search_motors(self):
        """搜索电机ID"""
        self.current_process.set("搜索中...")
        self.root.update_idletasks()
        
        try:
            # 调用CAN通信类的搜索电机方法
            self.found_motors = self.can_comm.search_motors()
            
            if self.found_motors:
                # 设置下拉框选项
                self.motor_id_list['values'] = self.found_motors
                self.motor_id_list.current(0)
                self.current_motor_id.set(str(self.found_motors[0]))
                self.current_process.set(f"找到{len(self.found_motors)}个电机")
            else:
                # 清空下拉框
                self.motor_id_list['values'] = []
                self.motor_id_list.current(-1)
                self.motor_id_var.set("")
                self.current_motor_id.set("")
                self.current_process.set("未找到电机")
                messagebox.showinfo("提示", "未搜索到任何电机")
        except Exception as e:
            self.current_process.set("搜索失败")
            messagebox.showerror("错误", f"搜索电机失败：{str(e)}")
    
    def on_motor_id_selected(self, event):
        """电机ID选择事件"""
        selected_id = self.motor_id_var.get()
        if selected_id:
            self.current_motor_id.set(selected_id)
    
    def stop_test(self):
        """停止测试"""
        try:
            self.current_process.set("停止中...")
            
            # 1. 停止MPC发送
            self.is_running = False
            if self.mpc_thread and self.mpc_thread.is_alive():
                self.mpc_thread.join(timeout=1.0)
            
            # 2. 禁能电机
            if self.current_motor_id.get():
                motor_id = int(self.current_motor_id.get())
                if not self.disable_motor(motor_id):
                    messagebox.showerror("错误", "电机禁能失败")
            
            # 更新UI状态
            self.current_process.set("空闲")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            
        except Exception as e:
            messagebox.showerror("错误", f"停止测试失败：{str(e)}")
            self.current_process.set("空闲")
    
    def set_zero_offset(self, offset, motor_id):
        """设置零位偏移（根据电机类型选择不同的发送函数）"""
        is_robstride = self.is_robstride_motor.get()
        return self.can_comm.set_zero_offset(offset, motor_id, is_robstride)
    
    def send_param_write(self, addr, data):
        """发送参数写入命令（根据电机类型选择不同的发送函数）"""
        is_robstride = self.is_robstride_motor.get()
        return self.can_comm.send_param_write(addr, data, is_robstride)
    
    def enable_motor(self, motor_id, mode=1):
        """启用电机（根据电机类型选择不同的发送函数）"""
        is_robstride = self.is_robstride_motor.get()
        return self.can_comm.enable_motor(motor_id, mode, is_robstride)
    
    def disable_motor(self, motor_id):
        """禁用电机（根据电机类型选择不同的发送函数）"""
        is_robstride = self.is_robstride_motor.get()
        return self.can_comm.disable_motor(motor_id, is_robstride)
    
    def send_mpc_command(self, angle, speed, torque):
        """发送MPC命令（根据电机类型选择不同的发送函数）"""
        if self.is_robstride_motor.get():
            return self.can_comm.send_mpc_command_robstride(angle, speed, torque)
        else:
            return self.can_comm.send_mpc_command_self_made(angle, speed, torque)
    
    def send_mpc_thread(self):
        """MPC命令发送线程"""
        try:
            start_time = time.time()
            frequency = 2.0  # 正弦波频率2Hz
            amplitude = PI / 4  # 幅值pi/4
            sample_rate = 200.0  # 采样频率200Hz
            sample_interval = 1.0 / sample_rate
            
            while self.is_running:
                # 计算当前时间
                current_time = time.time() - start_time
                
                # 生成正弦波角度
                target_angle = amplitude * math.sin(2 * PI * frequency * current_time)
                
                # 计算速度（角度的导数）
                target_speed = amplitude * 2 * PI * frequency * math.cos(2 * PI * frequency * current_time)
                
                # 扭矩设为0
                target_torque = 0.0
                
                # 发送MPC命令
                self.send_mpc_command(target_angle, target_speed, target_torque)
                
                # 等待采样间隔
                time.sleep(sample_interval)
        
        except Exception as e:
            print(f"MPC发送线程异常: {str(e)}")
            self.is_running = False
            self.root.after(0, lambda: messagebox.showerror("错误", f"MPC发送异常：{str(e)}"))
            self.root.after(0, self.reset_ui)
    
    def reset_ui(self):
        """重置UI状态"""
        self.current_process.set("空闲")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def on_closing(self):
        """窗口关闭事件"""
        if self.is_running:
            self.stop_test()
        self.root.destroy()

def main():
    """主函数"""
    root = tk.Tk()
    app = NoLoadCycleTest(root)
    
    # 处理窗口关闭事件
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    
    root.mainloop()

if __name__ == "__main__":
    main()