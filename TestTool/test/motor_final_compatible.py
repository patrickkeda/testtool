"""
电机控制与数据采集系统 - 完全兼容版本
自动适配pymodbus的不同版本
"""
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pymodbus.client import ModbusTcpClient
import threading
import time
import csv
from datetime import datetime

class MotorControlApp:
    """电机控制和数据采集程序"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("电机控制与数据采集系统")
        self.root.geometry("1000x700")
        
        self.client = None
        self.is_connected = False
        self.is_monitoring = False
        self.is_recording = False
        self.monitor_thread = None
        
        self.data_records = []
        
        # pymodbus版本兼容性标记
        self.read_method = None
        self.write_method = None
        
        self.create_widgets()
    
    def create_widgets(self):
        """创建界面"""
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(5, weight=1)
        
        # 连接设置
        conn_frame = ttk.LabelFrame(main_frame, text="连接设置", padding="10")
        conn_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(conn_frame, text="IP:").grid(row=0, column=0, padx=5)
        self.ip_var = tk.StringVar(value="192.168.0.22")
        ttk.Entry(conn_frame, textvariable=self.ip_var, width=15).grid(row=0, column=1, padx=5)
        
        ttk.Label(conn_frame, text="端口:").grid(row=0, column=2, padx=5)
        self.port_var = tk.StringVar(value="502")
        ttk.Entry(conn_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, padx=5)
        
        self.connect_btn = ttk.Button(conn_frame, text="连接", command=self.connect)
        self.connect_btn.grid(row=0, column=4, padx=5)
        
        self.disconnect_btn = ttk.Button(conn_frame, text="断开", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_btn.grid(row=0, column=5, padx=5)
        
        self.conn_status = ttk.Label(conn_frame, text="● 未连接", foreground="red")
        self.conn_status.grid(row=0, column=6, padx=10)
        
        # 电机控制
        control_frame = ttk.LabelFrame(main_frame, text="电机控制", padding="10")
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(control_frame, text="控制:", font=('', 10, 'bold')).grid(row=0, column=0, padx=5)
        
        self.run_btn = ttk.Button(control_frame, text="运行", state=tk.DISABLED, width=12)
        self.run_btn.grid(row=0, column=1, padx=5)
        self.run_btn.bind('<Button-1>', lambda e: self.motor_run_press())
        self.run_btn.bind('<ButtonRelease-1>', lambda e: self.motor_run_release())
        
        self.stop_btn = ttk.Button(control_frame, text="停止", state=tk.DISABLED, width=12)
        self.stop_btn.grid(row=0, column=2, padx=5)
        self.stop_btn.bind('<Button-1>', lambda e: self.motor_stop_press())
        self.stop_btn.bind('<ButtonRelease-1>', lambda e: self.motor_stop_release())
        
        self.reset_btn = ttk.Button(control_frame, text="复位", state=tk.DISABLED, width=12)
        self.reset_btn.grid(row=0, column=3, padx=5)
        self.reset_btn.bind('<Button-1>', lambda e: self.motor_reset_press())
        self.reset_btn.bind('<ButtonRelease-1>', lambda e: self.motor_reset_release())
        
        # 序号写入控制
        seq_frame = ttk.LabelFrame(main_frame, text="序号写入（41095）", padding="10")
        seq_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(seq_frame, text="序号:", font=('', 10, 'bold')).grid(row=0, column=0, padx=5)
        
        self.seq_btn1 = ttk.Button(seq_frame, text="写入 1", command=lambda: self.write_sequence_number(1), 
                                   state=tk.DISABLED, width=12)
        self.seq_btn1.grid(row=0, column=1, padx=5)
        
        self.seq_btn2 = ttk.Button(seq_frame, text="写入 2", command=lambda: self.write_sequence_number(2), 
                                   state=tk.DISABLED, width=12)
        self.seq_btn2.grid(row=0, column=2, padx=5)
        
        self.seq_btn3 = ttk.Button(seq_frame, text="写入 3", command=lambda: self.write_sequence_number(3), 
                                   state=tk.DISABLED, width=12)
        self.seq_btn3.grid(row=0, column=3, padx=5)
        
        self.seq_status = ttk.Label(seq_frame, text="当前: --", width=15)
        self.seq_status.grid(row=0, column=4, padx=10)
        
        # 实时参数
        params_frame = ttk.LabelFrame(main_frame, text="实时参数（40101-40105）", padding="10")
        params_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=5)
        
        params = [
            ("角度:", "angle_label", "°"),
            ("角速度:", "velocity_label", "rad/s"),
            ("扭矩:", "torque_label", "Nm"),
            ("温度:", "temp_label", "℃"),
            ("扭矩仪:", "torque_meter_label", "Nm")
        ]
        
        for i, (label_text, var_name, unit) in enumerate(params):
            ttk.Label(params_frame, text=label_text).grid(row=0, column=i*3, sticky=tk.E, padx=5)
            label = ttk.Label(params_frame, text="--", foreground="blue", font=('', 12, 'bold'), width=8)
            label.grid(row=0, column=i*3+1, padx=2)
            ttk.Label(params_frame, text=unit).grid(row=0, column=i*3+2, sticky=tk.W, padx=5)
            setattr(self, var_name, label)
        
        # 数据记录
        rec_frame = ttk.LabelFrame(main_frame, text="数据记录", padding="10")
        rec_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(rec_frame, text="读取间隔:").grid(row=0, column=0, padx=5)
        self.interval_var = tk.StringVar(value="10")
        ttk.Entry(rec_frame, textvariable=self.interval_var, width=8).grid(row=0, column=1, padx=5)
        ttk.Label(rec_frame, text="ms").grid(row=0, column=2, sticky=tk.W)
        
        self.start_record_btn = ttk.Button(rec_frame, text="开始记录", command=self.start_recording, 
                                          state=tk.DISABLED, width=12)
        self.start_record_btn.grid(row=0, column=3, padx=10)
        
        self.stop_record_btn = ttk.Button(rec_frame, text="停止记录", command=self.stop_recording, 
                                         state=tk.DISABLED, width=12)
        self.stop_record_btn.grid(row=0, column=4, padx=5)
        
        ttk.Button(rec_frame, text="导出CSV", command=self.export_csv, width=12).grid(row=0, column=5, padx=5)
        ttk.Button(rec_frame, text="清空数据", command=self.clear_data, width=12).grid(row=0, column=6, padx=5)
        
        self.record_count_label = ttk.Label(rec_frame, text="记录数: 0")
        self.record_count_label.grid(row=0, column=7, padx=10)
        
        # 数据表格
        table_frame = ttk.LabelFrame(main_frame, text="数据记录表格", padding="10")
        table_frame.grid(row=5, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        
        columns = ('时间戳', '角度(°)', '角速度(rad/s)', '扭矩(Nm)', '温度(℃)', '扭矩仪(Nm)', '运行', '停止')
        
        self.data_tree = ttk.Treeview(table_frame, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.data_tree.heading(col, text=col)
            if col == '时间戳':
                self.data_tree.column(col, width=150)
            else:
                self.data_tree.column(col, width=100)
        
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.data_tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.data_tree.xview)
        self.data_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        self.data_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        # 状态栏
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=6, column=0, sticky=(tk.W, tk.E), pady=5)
        
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var, relief=tk.SUNKEN).pack(fill=tk.X)
    
    def log(self, message):
        """日志"""
        self.status_var.set(message)
        print(f"[{time.strftime('%H:%M:%S')}] {message}")
    
    def safe_read_registers(self, address, count):
        """安全读取寄存器 - 兼容不同版本"""
        try:
            # 尝试方式1: read_holding_registers(address, count)
            return self.client.read_holding_registers(address, count)
        except TypeError:
            try:
                # 尝试方式2: read_holding_registers(address=address, count=count)
                return self.client.read_holding_registers(address=address, count=count)
            except:
                try:
                    # 尝试方式3: 只传address，count用默认或其他方式
                    return self.client.read_holding_registers(address)
                except:
                    return None
    
    def safe_read_coils(self, address, count):
        """安全读取线圈"""
        try:
            return self.client.read_coils(address, count)
        except TypeError:
            try:
                return self.client.read_coils(address=address, count=count)
            except:
                try:
                    return self.client.read_coils(address)
                except:
                    return None
    
    def safe_write_coil(self, address, value):
        """安全写入线圈 - 兼容不同版本和地址格式"""
        # 尝试多种调用方式，参考41095的处理方式
        methods_to_try = [
            lambda: self.client.write_coil(address, value),
            lambda: self.client.write_coil(address=address, value=value),
        ]
        
        for method in methods_to_try:
            try:
                resp = method()
                if resp and not resp.isError():
                    return resp
            except (TypeError, AttributeError):
                continue
            except Exception as e:
                # 记录错误但继续尝试
                # print(f"写入线圈地址{address}时出错: {e}")
                continue
        
        return None
    
    def safe_write_register(self, address, value, unit=1):
        """安全写入寄存器 - 兼容不同版本"""
        methods_to_try = [
            lambda: self.client.write_register(address, value, unit=unit),
            lambda: self.client.write_register(address, value),
            lambda: self.client.write_register(address=address, value=value, unit=unit),
            lambda: self.client.write_register(address=address, value=value),
            lambda: self.client.write_registers(address, [value], unit=unit),
            lambda: self.client.write_registers(address, [value]),
            lambda: self.client.write_registers(address=address, values=[value], unit=unit),
            lambda: self.client.write_registers(address=address, values=[value]),
        ]
        
        for method in methods_to_try:
            try:
                resp = method()
                if resp:
                    return resp
            except (TypeError, AttributeError):
                continue
            except Exception as e:
                # 记录错误但继续尝试其他方法
                continue
        
        return None
    
    def connect(self):
        """连接PLC"""
        try:
            ip = self.ip_var.get().strip()
            port = int(self.port_var.get().strip())
            
            self.log(f"正在连接到 {ip}:{port}...")
            
            self.client = ModbusTcpClient(host=ip, port=port, timeout=5)
            
            if self.client.connect():
                self.is_connected = True
                self.conn_status.config(text="● 已连接", foreground="green")
                self.connect_btn.config(state=tk.DISABLED)
                self.disconnect_btn.config(state=tk.NORMAL)
                self.run_btn.config(state=tk.NORMAL)
                self.stop_btn.config(state=tk.NORMAL)
                self.reset_btn.config(state=tk.NORMAL)
                self.start_record_btn.config(state=tk.NORMAL)
                self.seq_btn1.config(state=tk.NORMAL)
                self.seq_btn2.config(state=tk.NORMAL)
                self.seq_btn3.config(state=tk.NORMAL)
                
                self.log(f"✓ 已连接到 {ip}:{port}")
                
                # 测试读取方法
                self.detect_api_version()
                
                # 启动监控
                self.is_monitoring = True
                self.monitor_thread = threading.Thread(target=self.monitor_loop, daemon=True)
                self.monitor_thread.start()
            else:
                self.log("✗ 连接失败")
                messagebox.showerror("错误", "无法连接到PLC")
        except Exception as e:
            self.log(f"✗ 连接异常: {e}")
    
    def detect_api_version(self):
        """检测pymodbus API版本"""
        self.log("检测pymodbus版本...")
        
        # 测试读取方法
        try:
            resp = self.client.read_holding_registers(100, 1)
            self.read_method = "v3_positional"  # 支持位置参数
            self.log("✓ 使用标准API")
        except TypeError:
            try:
                resp = self.client.read_holding_registers(address=100, count=1)
                self.read_method = "v3_keyword"  # 支持关键字参数
                self.log("✓ 使用关键字API")
            except:
                # 可能需要其他方式
                self.read_method = "unknown"
                self.log("⚠️  API版本未知，将尝试多种方式")
    
    def disconnect(self):
        """断开连接"""
        self.is_monitoring = False
        self.is_recording = False
        if self.client:
            self.client.close()
        
        self.is_connected = False
        self.conn_status.config(text="● 未连接", foreground="red")
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.reset_btn.config(state=tk.DISABLED)
        self.start_record_btn.config(state=tk.DISABLED)
        self.stop_record_btn.config(state=tk.DISABLED)
        self.seq_btn1.config(state=tk.DISABLED)
        self.seq_btn2.config(state=tk.DISABLED)
        self.seq_btn3.config(state=tk.DISABLED)
        
        self.log("已断开连接")
    
    def motor_run_press(self):
        """电机运行 - 按下时写线圈协议地址105为1"""
        resp = self.safe_write_coil(105, True)
        if resp and not resp.isError():
            self.log("✓ 电机运行按下 (协议地址105=1)")
        else:
            self.log("⚠️  电机运行按下可能未生效")
    
    def motor_run_release(self):
        """电机运行 - 松开时写线圈协议地址105为0"""
        resp = self.safe_write_coil(105, False)
        if resp and not resp.isError():
            self.log("✓ 电机运行松开 (协议地址105=0)")
        else:
            self.log("⚠️  电机运行松开可能未生效")
    
    def motor_stop_press(self):
        """电机停止 - 按下时写线圈协议地址106为1"""
        resp = self.safe_write_coil(106, True)
        if resp and not resp.isError():
            self.log("✓ 电机停止按下 (协议地址106=1)")
        else:
            self.log("⚠️  电机停止按下可能未生效")
    
    def motor_stop_release(self):
        """电机停止 - 松开时写线圈协议地址106为0"""
        resp = self.safe_write_coil(106, False)
        if resp and not resp.isError():
            self.log("✓ 电机停止松开 (协议地址106=0)")
        else:
            self.log("⚠️  电机停止松开可能未生效")
    
    def motor_reset_press(self):
        """电机复位 - 按下时写线圈协议地址109为1"""
        resp = self.safe_write_coil(109, True)
        if resp and not resp.isError():
            self.log("✓ 电机复位按下 (协议地址109=1)")
        else:
            self.log("⚠️  电机复位按下可能未生效")
    
    def motor_reset_release(self):
        """电机复位 - 松开时写线圈协议地址109为0"""
        resp = self.safe_write_coil(109, False)
        if resp and not resp.isError():
            self.log("✓ 电机复位松开 (协议地址109=0)")
        else:
            self.log("⚠️  电机复位松开可能未生效")
    
    def write_sequence_number(self, number):
        """写入序号到地址41095"""
        if number not in [1, 2, 3]:
            self.log("⚠️  序号必须是1、2或3")
            return
        
        if not self.is_connected or not self.client:
            self.log("⚠️  未连接到PLC，无法写入")
            return
        
        # 使用协议地址41094
        addr = 41094
        desc = "协议地址41094"
        
        try:
            self.log(f"尝试写入序号 {number} 到地址 {addr} ({desc})...")
            resp = self.safe_write_register(addr, number)
            if resp:
                # 检查响应是否成功
                if hasattr(resp, 'isError'):
                    if not resp.isError():
                        # 验证写入：读取回值确认（使用协议地址1094）
                        time.sleep(0.2)  # 延迟确保写入完成
                        verify_resp = self.safe_read_registers(addr, 1)
                        if verify_resp and not verify_resp.isError() and verify_resp.registers:
                            actual_value = verify_resp.registers[0]
                            if actual_value == number:
                                self.log(f"✓ 序号 {number} 写入成功并验证 (地址: {addr}, {desc})")
                                self.seq_status.config(text=f"当前: {number}", foreground="green")
                            else:
                                self.log(f"⚠️  写入地址 {addr} 但验证失败 (期望: {number}, 实际: {actual_value})")
                                self.seq_status.config(text="当前: --", foreground="red")
                        else:
                            self.log(f"✓ 序号 {number} 写入成功 (地址: {addr}, {desc})，但无法验证")
                            self.seq_status.config(text=f"当前: {number}", foreground="green")
                    else:
                        error_msg = getattr(resp, 'message', str(resp))
                        error_code = getattr(resp, 'exception_code', '')
                        self.log(f"✗ 写入地址 {addr} 失败: {error_msg} (代码: {error_code})")
                        self.seq_status.config(text="当前: --", foreground="red")
                else:
                    # 没有isError方法，尝试验证
                    time.sleep(0.2)
                    verify_resp = self.safe_read_registers(addr, 1)
                    if verify_resp and not verify_resp.isError() and verify_resp.registers:
                        if verify_resp.registers[0] == number:
                            self.log(f"✓ 序号 {number} 写入成功并验证 (地址: {addr}, {desc})")
                            self.seq_status.config(text=f"当前: {number}", foreground="green")
                        else:
                            self.log(f"✓ 序号 {number} 写入成功 (地址: {addr}, {desc})，但验证值不匹配")
                            self.seq_status.config(text=f"当前: {number}", foreground="green")
                    else:
                        self.log(f"✓ 序号 {number} 写入成功 (地址: {addr}, {desc})，但无法验证")
                        self.seq_status.config(text=f"当前: {number}", foreground="green")
            else:
                self.log(f"✗ 地址 {addr} ({desc}): 无响应")
                self.seq_status.config(text="当前: --", foreground="red")
        except Exception as e:
            error_detail = str(e)
            self.log(f"✗ 地址 {addr} ({desc}) 异常: {error_detail}")
            self.seq_status.config(text="当前: --", foreground="red")
    
    def start_recording(self):
        """开始记录"""
        self.is_recording = True
        self.start_record_btn.config(state=tk.DISABLED)
        self.stop_record_btn.config(state=tk.NORMAL)
        self.log("开始记录数据...")
    
    def stop_recording(self):
        """停止记录"""
        self.is_recording = False
        self.start_record_btn.config(state=tk.NORMAL)
        self.stop_record_btn.config(state=tk.DISABLED)
        self.log("已停止记录")
    
    def monitor_loop(self):
        """监控循环"""
        try:
            interval = int(self.interval_var.get()) / 1000.0
        except:
            interval = 0.01
        
        last_record_time = time.time()
        
        # 尝试不同的寄存器地址
        reg_addresses_to_try = [
            (100, "40101-40105"),  # 协议地址100
            (101, "直接101"),      # 直接使用101
            (40100, "完整40100"),  # 完整地址
            (40101, "完整40101")   # 完整地址
        ]
        
        working_address = None
        
        while self.is_monitoring:
            try:
                # 读取线圈状态
                # coils[0]: 运行(105), coils[1]: 停止(106), coils[2]: 复位(109)
                coils = [False, False, False]
                try:
                    # 读取运行状态(105)
                    run_resp = self.safe_read_coils(105, 1)
                    if run_resp and not run_resp.isError():
                        coils[0] = run_resp.bits[0] if run_resp.bits else False
                    
                    # 读取停止状态(106)
                    stop_resp = self.safe_read_coils(106, 1)
                    if stop_resp and not stop_resp.isError():
                        coils[1] = stop_resp.bits[0] if stop_resp.bits else False
                    
                    # 读取复位状态(109)
                    reset_resp = self.safe_read_coils(109, 1)
                    if reset_resp and not reset_resp.isError():
                        coils[2] = reset_resp.bits[0] if reset_resp.bits else False
                except Exception as e:
                    pass
                
                # 读取保持寄存器
                motor_data = None
                
                if working_address is not None:
                    # 使用已知有效的地址
                    try:
                        regs_resp = self.safe_read_registers(working_address, 5)
                        if regs_resp and not regs_resp.isError():
                            motor_data = self.parse_motor_data(regs_resp.registers)
                    except:
                        working_address = None  # 重新尝试
                else:
                    # 尝试找到有效的地址
                    for addr, desc in reg_addresses_to_try:
                        try:
                            regs_resp = self.safe_read_registers(addr, 5)
                            if regs_resp and not regs_resp.isError():
                                motor_data = self.parse_motor_data(regs_resp.registers)
                                if motor_data:
                                    working_address = addr
                                    self.log(f"✓ 找到有效地址: {addr} ({desc})")
                                    break
                        except Exception as e:
                            continue
                
                # 更新显示
                if motor_data:
                    self.root.after(0, lambda: self.update_display(motor_data, coils))
                    
                    # 记录数据
                    current_time = time.time()
                    if self.is_recording and (current_time - last_record_time) >= interval:
                        self.root.after(0, lambda: self.record_data(motor_data, coils))
                        last_record_time = current_time
                
                time.sleep(max(interval, 0.01))
                
            except Exception as e:
                print(f"监控错误: {e}")
                time.sleep(0.1)
    
    def parse_motor_data(self, registers):
        """解析电机数据"""
        try:
            data = {}
            # 处理前3个参数：角度、角速度、扭矩（都放大10倍）
            for i, key in enumerate(['angle', 'velocity', 'torque']):
                raw = registers[i]
                # 转换为带符号整数
                if raw > 32767:
                    raw = raw - 65536
                # 所有值都放大10倍，需要除以10
                data[key] = round(raw / 10.0, 2)
            
            # 处理温度（第4个参数，地址40104，不放大10倍，不要小数）
            raw = registers[3]
            if raw > 32767:
                raw = raw - 65536
            data['temperature'] = int(raw)  # 温度不放大10倍，不要小数
            
            # 处理扭矩仪（第5个参数，地址40105，放大10倍，保留1位小数）
            raw = registers[4]
            if raw > 32767:
                raw = raw - 65536
            data['torque_meter'] = round(raw / 10.0, 1)
            
            # 验证数据合理性
            if -360 <= data['angle'] <= 360 and 0 <= data['temperature'] <= 150:
                return data
            return None
        except:
            return None
    
    def update_display(self, motor_data, coils):
        """更新显示"""
        self.angle_label.config(text=f"{motor_data['angle']}")
        self.velocity_label.config(text=f"{motor_data['velocity']}")
        self.torque_label.config(text=f"{motor_data['torque']}")
        self.temp_label.config(text=f"{motor_data['temperature']}")
        self.torque_meter_label.config(text=f"{motor_data['torque_meter']}")
    
    def record_data(self, motor_data, coils):
        """记录数据"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        record = {
            '时间戳': timestamp,
            '角度(°)': motor_data['angle'],
            '角速度(rad/s)': motor_data['velocity'],
            '扭矩(Nm)': motor_data['torque'],
            '温度(℃)': motor_data['temperature'],
            '扭矩仪(Nm)': motor_data['torque_meter'],
            '运行': 1 if coils[0] else 0,
            '停止': 1 if coils[1] else 0
        }
        
        self.data_records.append(record)
        
        values = tuple(record.values())
        self.data_tree.insert('', 0, values=values)
        
        items = self.data_tree.get_children()
        if len(items) > 100:
            self.data_tree.delete(items[-1])
        
        self.record_count_label.config(text=f"记录数: {len(self.data_records)}")
    
    def export_csv(self):
        """导出CSV"""
        if not self.data_records:
            messagebox.showwarning("提示", "没有数据可导出")
            return
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=f"电机数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=self.data_records[0].keys())
                    writer.writeheader()
                    writer.writerows(self.data_records)
                
                self.log(f"✓ 已导出 {len(self.data_records)} 条数据到 {filename}")
                messagebox.showinfo("成功", f"已导出 {len(self.data_records)} 条数据")
            except Exception as e:
                messagebox.showerror("错误", f"导出失败: {e}")
    
    def clear_data(self):
        """清空数据"""
        if not self.data_records:
            return
        
        if messagebox.askyesno("确认", "确定要清空所有数据吗？"):
            self.data_records = []
            for item in self.data_tree.get_children():
                self.data_tree.delete(item)
            self.record_count_label.config(text="记录数: 0")
            self.log("已清空数据")


if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = MotorControlApp(root)
        print("✓ 程序启动成功")
        root.mainloop()
    except Exception as e:
        print(f"\n✗ 程序启动失败: {e}")
        import traceback
        traceback.print_exc()
        input("\n按Enter键退出...")

