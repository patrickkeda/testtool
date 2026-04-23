"""
CAN协议发送器
基于示例代码的ECanVci64.dll实现
"""

import os
import sys
import ctypes
from ctypes import cdll, c_uint, c_byte, c_ubyte, Structure, byref, POINTER, c_uint16

# 设备类型常量
USBCAN1 = 3
USBCAN2 = 4
USBCANFD = 6

# 状态常量
STATUS_ERR = 0
STATUS_OK = 1


class BoardInfo(Structure):
    """设备信息结构体"""
    _fields_ = [
        ("hw_Version", ctypes.c_ushort),
        ("fw_Version", ctypes.c_ushort),
        ("dr_Version", ctypes.c_ushort),
        ("in_Version", ctypes.c_ushort),
        ("irq_Num", ctypes.c_ushort),
        ("can_Num", ctypes.c_byte),
        ("str_Serial_Num", ctypes.c_byte * 20),
        ("str_hw_Type", ctypes.c_byte * 40),
        ("Reserved", ctypes.c_byte * 4),
    ]


class CAN_OBJ(Structure):
    """CAN消息结构体（注意：数据字段是小写data）"""
    _fields_ = [
        ("ID", c_uint),
        ("TimeStamp", c_uint),
        ("TimeFlag", c_byte),
        ("SendType", c_byte),
        ("RemoteFlag", c_byte),
        ("ExternFlag", c_byte),
        ("DataLen", c_byte),
        ("data", c_ubyte * 8),  # 注意是小写data
        ("Reserved", c_byte * 3),
    ]


class INIT_CONFIG(Structure):
    """初始化配置结构体"""
    _fields_ = [
        ("acccode", ctypes.c_uint32),
        ("accmask", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("filter", c_byte),
        ("timing0", c_byte),
        ("timing1", c_byte),
        ("mode", c_byte),
    ]


class CANMessage:
    """CAN消息封装类"""
    def __init__(self, frame_id: int, data: list):
        self.frame_id = frame_id
        self.data = data
    
    @staticmethod
    def from_hex_string(frame_id_str: str, data_str: str):
        """从十六进制字符串创建CAN消息"""
        # 解析帧ID（支持多种格式）
        frame_id_str = frame_id_str.strip().replace(' ', '').replace('0x', '').replace('0X', '')
        frame_id = int(frame_id_str, 16)
        
        # 解析数据（支持多种格式）
        data_str = data_str.strip().replace(' ', '')
        if data_str:
            # 确保是偶数个字符
            if len(data_str) % 2 != 0:
                data_str = '0' + data_str
            data = [int(data_str[i:i+2], 16) for i in range(0, len(data_str), 2)]
        else:
            data = []
        
        return CANMessage(frame_id, data)
    
    def to_hex_string(self):
        """转换为十六进制字符串"""
        id_str = f"{self.frame_id:08X}"
        data_str = ' '.join(f"{b:02X}" for b in self.data)
        return id_str, data_str


class GCANDevice:
    """GCAN设备类（基于示例代码）"""
    def __init__(self, device_type: int = USBCAN2, device_index: int = 0, channel: int = 0, allow_simulation: bool = True):
        self.device_type = device_type
        self.device_index = device_index
        self.channel = channel
        self.dll = None
        self.allow_simulation = allow_simulation
        self._load_dll()
    
    def _load_dll(self):
        """加载DLL

        兼容多种运行方式：
        1) 在 test/canapp 目录下直接运行 can_gui.py（当前工作目录包含 DLL）
        2) 从项目根目录运行主程序，通过 steps.can_steps 动态导入本模块
        3) PyInstaller 打包后的环境（DLL 在 _internal/test/canapp/ 或 sys._MEIPASS/test/canapp/）

        为此，这里会同时在以下位置查找 ECanVci64.dll / ECANFDVCI64.dll：
        - PyInstaller 临时目录 (sys._MEIPASS)
        - 当前工作目录 (os.getcwd())
        - 本文件所在目录 (os.path.dirname(__file__))
        - exe 所在目录的 _internal/test/canapp/（打包后的标准位置）
        """
        # 搜索目录列表
        search_dirs = []
        
        # 1. PyInstaller 打包环境：sys._MEIPASS 指向临时解压目录
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            meipass_dir = sys._MEIPASS
            search_dirs.append(meipass_dir)
            # 在 _MEIPASS 下查找 test/canapp 目录
            canapp_in_meipass = os.path.join(meipass_dir, 'test', 'canapp')
            if os.path.exists(canapp_in_meipass):
                search_dirs.append(canapp_in_meipass)
        
        # 2. 打包后的标准位置：exe 所在目录的 _internal/test/canapp/
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            internal_canapp = os.path.join(exe_dir, '_internal', 'test', 'canapp')
            if os.path.exists(internal_canapp):
                search_dirs.append(internal_canapp)
            # 也尝试直接在 _internal 目录查找
            internal_dir = os.path.join(exe_dir, '_internal')
            if os.path.exists(internal_dir):
                search_dirs.append(internal_dir)
        
        # 3. 当前工作目录
        cwdx = os.getcwd()
        if cwdx not in search_dirs:
            search_dirs.append(cwdx)
        
        # 4. 模块所在目录
        module_dir = os.path.dirname(os.path.abspath(__file__))
        if module_dir not in search_dirs:
            search_dirs.append(module_dir)
        
        dll_names = ["ECanVci64.dll", "ECANFDVCI64.dll"]
        
        # 记录所有尝试的路径和错误
        attempted_paths = []
        last_error = None
        
        for base_dir in search_dirs:
            for dll_name in dll_names:
                dll_path = os.path.join(base_dir, dll_name)
                attempted_paths.append(dll_path)
                if os.path.exists(dll_path):
                    try:
                        self.dll = cdll.LoadLibrary(dll_path)
                        print(f"[CAN] 成功加载DLL: {dll_name} (from {base_dir})")
                        return
                    except OSError as e:
                        last_error = e
                        error_code = getattr(e, 'winerror', None) or getattr(e, 'errno', None)
                        print(f"[CAN] 尝试加载 {dll_name} 失败: {e}")
                        if error_code:
                            print(f"[CAN]   错误代码: {error_code}")
                            if error_code == 126:  # ERROR_MOD_NOT_FOUND
                                print(f"[CAN]   诊断: DLL依赖的库未找到，可能需要安装Visual C++运行库")
                            elif error_code == 193:  # ERROR_BAD_EXE_FORMAT
                                print(f"[CAN]   诊断: DLL格式错误，可能是32位/64位不匹配")
                        continue
                    except Exception as e:
                        last_error = e
                        print(f"[CAN] 尝试加载 {dll_name} 失败: {e}")
                        continue
        
        # 如果都失败了，提供详细的错误信息
        error_msg = "无法加载CAN DLL文件\n\n"
        error_msg += "已尝试的路径:\n"
        for path in attempted_paths:
            exists = "存在" if os.path.exists(path) else "不存在"
            error_msg += f"  - {path} ({exists})\n"
        
        if last_error:
            error_msg += f"\n最后错误: {last_error}\n"
        
        error_msg += "\n可能的原因:\n"
        error_msg += "1. DLL文件未正确打包到 _internal/test/canapp/ 目录\n"
        error_msg += "2. DLL依赖的Visual C++运行库未安装（需要VC++ Redistributable）\n"
        error_msg += "3. CAN设备驱动未安装\n"
        error_msg += "4. DLL文件损坏或版本不匹配\n"
        error_msg += "5. 32位/64位不匹配（需要64位DLL）\n"
        
        print(f"[CAN] {error_msg}")
        
        if not self.allow_simulation:
            raise RuntimeError(error_msg)
        
        self.dll = None
        print("[CAN] 警告: 无法加载DLL文件，将使用模拟模式")
    
    def open(self) -> bool:
        """打开设备"""
        if self.dll is None:
            print("模拟模式: 打开设备")
            return True
        
        try:
            result = self.dll.OpenDevice(self.device_type, self.device_index, 0)
            if result == STATUS_OK:
                print(f"成功打开设备: type={self.device_type}, index={self.device_index}")
                return True
            else:
                print(f"打开设备失败，返回码: {result}")
                print(f"  设备类型: {self.device_type} (USBCAN1=3, USBCAN2=4, USBCANFD=6)")
                print(f"  设备索引: {self.device_index}")
                print("  可能原因:")
                print("    1. CAN设备未物理连接（请检查USB连接）")
                print("    2. 设备驱动未安装或未正确安装")
                print("    3. 设备索引不正确（如果连接了多个设备，尝试其他索引如1、2等）")
                print("    4. 设备类型不正确（如果使用USBCAN1，请改为3；如果使用USBCANFD，请改为6）")
                return False
        except Exception as e:
            print(f"打开设备失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def init_can(self, baud_rate: int = 500000) -> bool:
        """初始化CAN通道"""
        if self.dll is None:
            print(f"模拟模式: 初始化CAN通道 {self.channel}, 波特率={baud_rate}")
            return True
        
        try:
            # 波特率到timing0/timing1的转换
            timing0, timing1 = self._get_timing(baud_rate)
            
            init_config = INIT_CONFIG()
            init_config.acccode = 0
            init_config.accmask = 0xFFFFFFFF
            init_config.reserved = 0
            init_config.filter = 0
            init_config.timing0 = timing0
            init_config.timing1 = timing1
            init_config.mode = 0
            
            result = self.dll.InitCAN(self.device_type, self.device_index, self.channel, byref(init_config))
            if result == STATUS_OK:
                print(f"成功初始化CAN通道: channel={self.channel}, baud_rate={baud_rate}")
                return True
            else:
                print(f"初始化CAN失败，返回码: {result}")
                return False
        except Exception as e:
            print(f"初始化CAN失败: {e}")
            return False
    
    def _get_timing(self, baud: int):
        """根据波特率返回timing0和timing1"""
        baud_map = {
            1000000: (0, 0x14),
            800000: (0, 0x16),
            666000: (0x80, 0xb6),
            500000: (0, 0x1C),
            400000: (0x80, 0xfa),
            250000: (0x01, 0x1C),
            200000: (0x81, 0xfa),
            125000: (0x03, 0x1C),
            100000: (0x04, 0x1C),
            80000: (0x83, 0xff),
            50000: (0x09, 0x1C),
        }
        return baud_map.get(baud, (0, 0x1C))  # 默认500K
    
    def start_can(self) -> bool:
        """启动CAN通道"""
        if self.dll is None:
            print(f"模拟模式: 启动CAN通道 {self.channel}")
            return True
        
        try:
            result = self.dll.StartCAN(self.device_type, self.device_index, self.channel)
            if result == STATUS_OK:
                print(f"成功启动CAN通道: channel={self.channel}")
                return True
            else:
                print(f"启动CAN失败，返回码: {result}")
                return False
        except Exception as e:
            print(f"启动CAN失败: {e}")
            return False
    
    def send_message(self, message: CANMessage) -> bool:
        """发送CAN消息"""
        if self.dll is None:
            print(f"模拟模式: 发送消息 ID=0x{message.frame_id:08X}, 数据={' '.join(f'{b:02X}' for b in message.data)}")
            return True
        
        try:
            can_obj = CAN_OBJ()
            can_obj.ID = message.frame_id
            can_obj.TimeStamp = 0
            can_obj.TimeFlag = 0
            can_obj.SendType = 0
            can_obj.RemoteFlag = 0
            can_obj.ExternFlag = 0
            can_obj.DataLen = min(len(message.data), 8)
            
            for i in range(min(len(message.data), 8)):
                can_obj.data[i] = message.data[i]
            
            if message.frame_id > 0x7FF:
                can_obj.ExternFlag = 1
            
            result = self.dll.Transmit(self.device_type, self.device_index, self.channel, byref(can_obj), c_uint16(1))
            
            if result == STATUS_OK:
                print(f"成功发送CAN消息: 帧ID=0x{message.frame_id:08X}, 数据={' '.join(f'{b:02X}' for b in message.data)}")
                return True
            else:
                print(f"发送CAN消息失败，返回码: {result}")
                return False
        except Exception as e:
            print(f"发送消息失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def receive_message(self, timeout_ms: int = 0, max_count: int = 1):
        """接收CAN消息"""
        if self.dll is None:
            return []
        
        try:
            recv_buffer = (CAN_OBJ * max_count)()
            result = self.dll.Receive(self.device_type, self.device_index, self.channel, byref(recv_buffer), max_count, timeout_ms)
            
            if result == STATUS_OK:
                messages = []
                for i in range(max_count):
                    can_obj = recv_buffer[i]
                    if can_obj.DataLen > 0:
                        frame_id = can_obj.ID
                        data = [can_obj.data[j] for j in range(can_obj.DataLen)]
                        msg = CANMessage(frame_id, data)
                        messages.append(msg)
                return messages
            else:
                return []
        except Exception as e:
            print(f"接收消息失败: {e}")
            return []
    
    def close(self):
        """关闭设备"""
        if self.dll is None:
            print("模拟模式: 关闭设备")
            return
        
        try:
            result = self.dll.CloseDevice(self.device_type, self.device_index, 0)
            if result == STATUS_OK:
                print("成功关闭设备")
            else:
                print(f"关闭设备失败，返回码: {result}")
        except Exception as e:
            print(f"关闭设备失败: {e}")


class CANProtocolSender:
    """CAN协议发送器封装类"""
    def __init__(self, device_type: int = USBCAN2, device_index: int = 0, channel: int = 0):
        self.device = GCANDevice(device_type, device_index, channel)
        self.receiving = False
        self.receive_callback = None
    
    def connect(self, baud_rate: int = 500000) -> bool:
        """连接设备
        
        Returns
        -------
        bool
            True if connection successful, False otherwise
            
        Raises
        ------
        RuntimeError
            If DLL is not loaded and simulation is not allowed
        """
        # 检查DLL是否加载
        if self.device.dll is None:
            error_msg = "CAN DLL未加载。可能的原因：\n"
            error_msg += "1. DLL文件未找到或路径不正确\n"
            error_msg += "2. DLL依赖的Visual C++运行库未安装\n"
            error_msg += "3. CAN设备驱动未安装\n"
            error_msg += "4. DLL文件损坏或版本不匹配"
            print(f"[CAN] 错误: {error_msg}")
            raise RuntimeError(error_msg)
        
        # 步骤1: 打开设备
        print(f"[CAN] 步骤1: 正在打开设备 (type={self.device.device_type}, index={self.device.device_index})...")
        if not self.device.open():
            error_msg = f"打开CAN设备失败 (type={self.device.device_type}, index={self.device.device_index})"
            print(f"[CAN] 错误: {error_msg}")
            print(f"[CAN] 诊断建议:")
            print(f"[CAN]   1. 检查CAN设备是否已连接并安装驱动")
            print(f"[CAN]   2. 检查设备管理器中CAN设备是否正常识别")
            print(f"[CAN]   3. 确认device_type和device_index参数正确")
            return False
        
        # 步骤2: 初始化CAN
        print(f"[CAN] 步骤2: 正在初始化CAN通道 (channel={self.device.channel}, baudrate={baud_rate})...")
        if not self.device.init_can(baud_rate):
            error_msg = f"初始化CAN通道失败 (channel={self.device.channel}, baudrate={baud_rate})"
            print(f"[CAN] 错误: {error_msg}")
            print(f"[CAN] 诊断建议:")
            print(f"[CAN]   1. 检查波特率设置是否正确")
            print(f"[CAN]   2. 检查CAN设备是否支持该波特率")
            print(f"[CAN]   3. 检查通道号是否正确")
            self.device.close()
            return False
        
        # 步骤3: 启动CAN
        print(f"[CAN] 步骤3: 正在启动CAN通道...")
        if not self.device.start_can():
            error_msg = "启动CAN通道失败"
            print(f"[CAN] 错误: {error_msg}")
            print(f"[CAN] 诊断建议:")
            print(f"[CAN]   1. 检查CAN总线是否正常")
            print(f"[CAN]   2. 检查是否有其他程序占用CAN设备")
            self.device.close()
            return False
        
        print(f"[CAN] ✓ CAN设备连接成功")
        return True
    
    def send(self, frame_id: str, data: str) -> bool:
        """发送CAN消息"""
        message = CANMessage.from_hex_string(frame_id, data)
        return self.device.send_message(message)
    
    def disconnect(self):
        """断开连接"""
        self.stop_receiving()
        if self.device:
            self.device.close()
    
    def start_receiving(self, callback, interval_ms: int = 30):
        """开始接收消息"""
        if self.receiving:
            return
        
        self.receiving = True
        self.receive_callback = callback
        import threading
        thread = threading.Thread(target=self._receive_loop, args=(interval_ms,), daemon=True)
        thread.start()
    
    def stop_receiving(self):
        """停止接收消息"""
        self.receiving = False
    
    def _receive_loop(self, interval_ms: int):
        """接收循环"""
        import time
        while self.receiving:
            messages = self.device.receive_message(timeout_ms=0, max_count=50)
            for msg in messages:
                if self.receive_callback:
                    self.receive_callback(msg)
            time.sleep(interval_ms / 1000.0)
    
    def receive_messages(self, timeout_ms: int = 100, max_count: int = 10):
        """接收CAN消息（一次性）"""
        if not self.device:
            return []
        return self.device.receive_message(timeout_ms, max_count)

