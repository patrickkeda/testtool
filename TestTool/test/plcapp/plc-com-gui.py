#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PLC Modbus 通信控制程序
基于 ModScan32 的功能实现，支持通过串口进行 Modbus 通信控制
"""

import sys
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pymodbus.client.serial import ModbusSerialClient
from pymodbus.exceptions import ModbusException


class ModbusPointType:
    """Modbus 点类型定义"""
    COIL_STATUS = 1      # 01: 线圈状态 (Coil Status)
    INPUT_STATUS = 2     # 02: 输入状态 (Input Status)
    HOLDING_REGISTER = 3 # 03: 保持寄存器 (Holding Register)
    INPUT_REGISTER = 4   # 04: 输入寄存器 (Input Register)
    
    @staticmethod
    def get_name(point_type):
        """获取点类型名称"""
        names = {
            1: "01: COIL STATUS",
            2: "02: INPUT STATUS",
            3: "03: HOLDING REGISTER",
            4: "04: INPUT REGISTER"
        }
        return names.get(point_type, "Unknown")


class WriteDialog:
    """写操作对话框"""
    def __init__(self, parent, point_type):
        self.parent = parent
        self.point_type = point_type
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Write Coil" if point_type in [1, 2] else "Write Register")
        self.dialog.geometry("350x250")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # 居中显示
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (self.dialog.winfo_width() // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (self.dialog.winfo_height() // 2)
        self.dialog.geometry(f"+{x}+{y}")
        
        self.create_widgets()
        
    def create_widgets(self):
        """创建对话框控件"""
        frame = ttk.Frame(self.dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Node (Device Id)
        ttk.Label(frame, text="Node:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.node_var = tk.StringVar(value="1")
        node_entry = ttk.Entry(frame, textvariable=self.node_var, width=15)
        node_entry.grid(row=0, column=1, pady=5, padx=10)
        
        # Address
        ttk.Label(frame, text="Address:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.address_var = tk.StringVar(value="2049")
        address_entry = ttk.Entry(frame, textvariable=self.address_var, width=15)
        address_entry.grid(row=1, column=1, pady=5, padx=10)
        
        # Value
        value_frame = ttk.LabelFrame(frame, text="Value", padding="10")
        value_frame.grid(row=2, column=0, columnspan=2, pady=10, sticky=tk.EW)
        
        if self.point_type in [ModbusPointType.COIL_STATUS, ModbusPointType.INPUT_STATUS]:
            # 线圈类型：On/Off
            self.value_var = tk.IntVar(value=0)
            ttk.Radiobutton(value_frame, text="Off", variable=self.value_var, value=0).pack(side=tk.LEFT, padx=10)
            ttk.Radiobutton(value_frame, text="On", variable=self.value_var, value=1).pack(side=tk.LEFT, padx=10)
            self.register_value_var = None
        else:
            # 寄存器类型：输入数值
            self.value_var = None
            ttk.Label(value_frame, text="Value:").pack(side=tk.LEFT, padx=5)
            self.register_value_var = tk.StringVar(value="0")
            register_entry = ttk.Entry(value_frame, textvariable=self.register_value_var, width=15)
            register_entry.pack(side=tk.LEFT, padx=5)
        
        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(20, 10))
        
        update_btn = ttk.Button(btn_frame, text="Update", command=self.update_clicked, width=12)
        update_btn.pack(side=tk.LEFT, padx=10)
        
        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self.cancel_clicked, width=12)
        cancel_btn.pack(side=tk.LEFT, padx=10)
        
    def update_clicked(self):
        """Update按钮点击"""
        try:
            node = int(self.node_var.get())
            address = int(self.address_var.get())
            if self.point_type in [ModbusPointType.COIL_STATUS, ModbusPointType.INPUT_STATUS]:
                value = bool(self.value_var.get())
            else:
                value = int(self.register_value_var.get())
            
            self.result = (node, address, value)
            self.dialog.destroy()
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数值")
    
    def cancel_clicked(self):
        """Cancel按钮点击"""
        self.result = None
        self.dialog.destroy()


class PLCModbusGUI:
    """PLC Modbus 通信控制主窗口"""
    
    def __init__(self, root):
        self.root = root
        self.modbus_client = None
        self.is_connected = False
        
        self.number_of_reads = 0
        self.valid_responses = 0
        
        self.init_ui()
        self.scan_serial_ports()
        
    def init_ui(self):
        """初始化用户界面"""
        self.root.title("PLC Modbus 通信控制")
        self.root.geometry("900x700")
        
        # 创建主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 上半部分：控制面板
        control_frame = ttk.LabelFrame(main_frame, text="控制面板", padding="10")
        control_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 10))
        self.create_control_panel(control_frame)
        
        # 下半部分：数据显示区域
        display_frame = ttk.LabelFrame(main_frame, text="数据显示", padding="10")
        display_frame.pack(fill=tk.BOTH, expand=True)
        self.create_data_display(display_frame)
        
    def create_control_panel(self, parent):
        """创建控制面板"""
        # 第一行：COM 口和连接控制
        row0 = ttk.Frame(parent)
        row0.pack(fill=tk.X, pady=5)
        
        ttk.Label(row0, text="COM 口:").pack(side=tk.LEFT, padx=5)
        self.com_port_combo = ttk.Combobox(row0, width=20, state="readonly")
        self.com_port_combo.pack(side=tk.LEFT, padx=5)
        
        refresh_btn = ttk.Button(row0, text="刷新", command=self.scan_serial_ports, width=10)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        
        # 连接按钮和状态
        self.connect_btn = ttk.Button(row0, text="连接", command=self.toggle_connection, width=10)
        self.connect_btn.pack(side=tk.LEFT, padx=(20, 5))
        
        self.status_label = ttk.Label(row0, text="未连接", foreground="red", font=("Arial", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        # 串口参数
        ttk.Label(row0, text="波特率:").pack(side=tk.LEFT, padx=(20, 5))
        self.baudrate_combo = ttk.Combobox(row0, width=10, values=["9600", "19200", "38400", "57600", "115200"], state="readonly")
        self.baudrate_combo.current(0)
        self.baudrate_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="数据位:").pack(side=tk.LEFT, padx=(20, 5))
        self.databits_combo = ttk.Combobox(row0, width=8, values=["7", "8"], state="readonly")
        self.databits_combo.current(1)
        self.databits_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="校验位:").pack(side=tk.LEFT, padx=(20, 5))
        self.parity_combo = ttk.Combobox(row0, width=10, values=["None", "Even", "Odd"], state="readonly")
        self.parity_combo.current(0)
        self.parity_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row0, text="停止位:").pack(side=tk.LEFT, padx=(20, 5))
        self.stopbits_combo = ttk.Combobox(row0, width=8, values=["1", "2"], state="readonly")
        self.stopbits_combo.current(0)
        self.stopbits_combo.pack(side=tk.LEFT, padx=5)
        
        # 分隔线
        separator = ttk.Separator(parent, orient=tk.HORIZONTAL)
        separator.pack(fill=tk.X, pady=10)
        
        # 第二行：Modbus 参数
        row1 = ttk.Frame(parent)
        row1.pack(fill=tk.X, pady=5)
        
        ttk.Label(row1, text="Device Id:").pack(side=tk.LEFT, padx=5)
        self.device_id_var = tk.StringVar(value="1")
        device_id_entry = ttk.Entry(row1, textvariable=self.device_id_var, width=10)
        device_id_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row1, text="Address:").pack(side=tk.LEFT, padx=(20, 5))
        self.address_var = tk.StringVar(value="2049")
        address_entry = ttk.Entry(row1, textvariable=self.address_var, width=15)
        address_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row1, text="Length:").pack(side=tk.LEFT, padx=(20, 5))
        self.length_var = tk.StringVar(value="10")
        length_entry = ttk.Entry(row1, textvariable=self.length_var, width=10)
        length_entry.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row1, text="MODBUS Point Type:").pack(side=tk.LEFT, padx=(20, 5))
        self.point_type_combo = ttk.Combobox(row1, width=20, values=[
            "01: COIL STATUS",
            "02: INPUT STATUS",
            "03: HOLDING REGISTER",
            "04: INPUT REGISTER"
        ], state="readonly")
        self.point_type_combo.current(0)
        self.point_type_combo.pack(side=tk.LEFT, padx=5)
        
        # 第三行：操作按钮
        row2 = ttk.Frame(parent)
        row2.pack(fill=tk.X, pady=5)
        
        read_btn = ttk.Button(row2, text="读取", command=self.read_data, width=12)
        read_btn.pack(side=tk.LEFT, padx=5)
        
        write_btn = ttk.Button(row2, text="写入", command=self.write_data, width=12)
        write_btn.pack(side=tk.LEFT, padx=5)
        
        clear_display_btn = ttk.Button(row2, text="清除显示", command=self.clear_display, width=12)
        clear_display_btn.pack(side=tk.LEFT, padx=5)
        
        # 第四行：统计信息
        row3 = ttk.Frame(parent)
        row3.pack(fill=tk.X, pady=5)
        
        ttk.Label(row3, text="Number of Reads:").pack(side=tk.LEFT, padx=5)
        self.reads_label = ttk.Label(row3, text="0", font=("Arial", 10, "bold"))
        self.reads_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(row3, text="Valid Responses:").pack(side=tk.LEFT, padx=(20, 5))
        self.responses_label = ttk.Label(row3, text="0", font=("Arial", 10, "bold"))
        self.responses_label.pack(side=tk.LEFT, padx=5)
        
        reset_btn = ttk.Button(row3, text="Reset Ctrs", command=self.reset_counters, width=12)
        reset_btn.pack(side=tk.LEFT, padx=(20, 5))
        
    def create_data_display(self, parent):
        """创建数据显示区域"""
        self.data_display = scrolledtext.ScrolledText(
            parent,
            height=20,
            width=80,
            bg="#F0F0F0",
            font=("Courier New", 10),
            wrap=tk.NONE
        )
        self.data_display.pack(fill=tk.BOTH, expand=True)
        
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
        """获取选中的 COM 口"""
        selected = self.com_port_combo.get()
        if selected and selected != "未找到串口":
            # 提取 COM 口编号
            if "COM" in selected.upper():
                import re
                match = re.search(r'COM(\d+)', selected.upper())
                if match:
                    return f"COM{match.group(1)}"
            return selected.split(" - ")[0]
        return None
            
    def toggle_connection(self):
        """切换连接状态"""
        if not self.is_connected:
            self.connect_modbus()
        else:
            self.disconnect_modbus()
            
    def connect_modbus(self):
        """连接 Modbus"""
        try:
            com_port = self.get_com_port()
            if not com_port or com_port == "未找到串口":
                messagebox.warning(self.root, "错误", "请选择有效的 COM 口")
                return
                
            baudrate = int(self.baudrate_combo.get())
            databits = int(self.databits_combo.get())
            parity_map = {"None": "N", "Even": "E", "Odd": "O"}
            parity = parity_map[self.parity_combo.get()]
            stopbits = int(self.stopbits_combo.get())
            
            # 创建 Modbus 串口客户端
            self.modbus_client = ModbusSerialClient(
                port=com_port,
                baudrate=baudrate,
                bytesize=databits,
                parity=parity,
                stopbits=stopbits,
                timeout=1
            )
            
            if self.modbus_client.connect():
                self.is_connected = True
                self.connect_btn.config(text="断开")
                self.status_label.config(text="已连接", foreground="green")
                self.data_display.insert(tk.END, f"[连接成功] COM口: {com_port}, 波特率: {baudrate}\n")
                self.data_display.see(tk.END)
            else:
                messagebox.warning(self.root, "错误", "无法连接到串口设备")
                self.modbus_client = None
                
        except Exception as e:
            messagebox.showerror("错误", f"连接失败: {str(e)}")
            self.modbus_client = None
            
    def disconnect_modbus(self):
        """断开 Modbus 连接"""
        if self.modbus_client:
            self.modbus_client.close()
            self.modbus_client = None
        self.is_connected = False
        self.connect_btn.config(text="连接")
        self.status_label.config(text="未连接", foreground="red")
        self.data_display.insert(tk.END, "[已断开连接]\n")
        self.data_display.see(tk.END)
        
    def get_point_type(self):
        """获取选中的点类型"""
        index = self.point_type_combo.current()
        return index + 1  # 1-4 对应 COIL_STATUS, INPUT_STATUS, HOLDING_REGISTER, INPUT_REGISTER
        
    def read_data(self):
        """读取数据"""
        if not self.is_connected:
            messagebox.warning(self.root, "警告", "请先连接 Modbus 设备")
            return
            
        try:
            device_id = int(self.device_id_var.get())
            address = int(self.address_var.get())
            length = int(self.length_var.get())
            point_type = self.get_point_type()
            
            # 转换为 Modbus 地址（从 0 开始）
            modbus_address = address - 1
            
            self.number_of_reads += 1
            self.reads_label.config(text=str(self.number_of_reads))
            
            # 根据点类型读取数据
            result = None
            if point_type == ModbusPointType.COIL_STATUS:
                result = self.modbus_client.read_coils(modbus_address, count=length, device_id=device_id)
            elif point_type == ModbusPointType.INPUT_STATUS:
                result = self.modbus_client.read_discrete_inputs(modbus_address, count=length, device_id=device_id)
            elif point_type == ModbusPointType.HOLDING_REGISTER:
                result = self.modbus_client.read_holding_registers(modbus_address, count=length, device_id=device_id)
            elif point_type == ModbusPointType.INPUT_REGISTER:
                result = self.modbus_client.read_input_registers(modbus_address, count=length, device_id=device_id)
                
            if result and not result.isError():
                self.valid_responses += 1
                self.responses_label.config(text=str(self.valid_responses))
                self.display_data(address, length, point_type, result)
            else:
                error_msg = str(result) if result else "未知错误"
                self.data_display.insert(tk.END, f"[读取错误] {error_msg}\n")
                self.data_display.see(tk.END)
                
        except ValueError as e:
            messagebox.showerror("错误", f"参数错误: {str(e)}")
        except ModbusException as e:
            self.data_display.insert(tk.END, f"[Modbus错误] {str(e)}\n")
            self.data_display.see(tk.END)
        except Exception as e:
            messagebox.showerror("错误", f"读取失败: {str(e)}")
            
    def write_data(self):
        """写入数据"""
        if not self.is_connected:
            messagebox.warning(self.root, "警告", "请先连接 Modbus 设备")
            return
            
        point_type = self.get_point_type()
        
        # 打开写对话框
        dialog = WriteDialog(self.root, point_type)
        self.root.wait_window(dialog.dialog)
        
        if dialog.result is None:
            return
            
        try:
            node, address, value = dialog.result
            
            # 转换为 Modbus 地址（从 0 开始）
            modbus_address = address - 1
            
            # 根据点类型写入数据
            result = None
            if point_type == ModbusPointType.COIL_STATUS:
                # pymodbus 3.11.4 使用 device_id 参数
                result = self.modbus_client.write_coil(modbus_address, value, device_id=node)
            elif point_type == ModbusPointType.INPUT_STATUS:
                messagebox.warning(self.root, "警告", "输入状态(INPUT STATUS)是只读的，无法写入")
                return
            elif point_type == ModbusPointType.HOLDING_REGISTER:
                # pymodbus 3.11.4 使用 device_id 参数
                result = self.modbus_client.write_register(modbus_address, value, device_id=node)
            elif point_type == ModbusPointType.INPUT_REGISTER:
                messagebox.warning(self.root, "警告", "输入寄存器(INPUT REGISTER)是只读的，无法写入")
                return
                
            if result and not result.isError():
                self.data_display.insert(tk.END, f"[写入成功] Node: {node}, Address: {address}, Value: {value}\n")
                self.data_display.see(tk.END)
            else:
                error_msg = str(result) if result else "未知错误"
                self.data_display.insert(tk.END, f"[写入错误] {error_msg}\n")
                self.data_display.see(tk.END)
                
        except ModbusException as e:
            self.data_display.insert(tk.END, f"[Modbus错误] {str(e)}\n")
            self.data_display.see(tk.END)
        except Exception as e:
            messagebox.showerror("错误", f"写入失败: {str(e)}")
            
    def display_data(self, start_address, length, point_type, result):
        """显示数据"""
        # 清除旧数据显示新数据
        self.data_display.delete(1.0, tk.END)
        
        # 获取数据
        if point_type in [ModbusPointType.COIL_STATUS, ModbusPointType.INPUT_STATUS]:
            # 布尔值（线圈/输入状态）
            values = result.bits[:length]
            for i, value in enumerate(values):
                addr = start_address + i
                self.data_display.insert(tk.END, f"{addr:05d}: <{1 if value else 0}>\n")
        else:
            # 寄存器值
            values = result.registers[:length]
            for i, value in enumerate(values):
                addr = start_address + i
                self.data_display.insert(tk.END, f"{addr:05d}: <{value}>\n")
        
        self.data_display.see(tk.END)
                
    def reset_counters(self):
        """重置计数器"""
        self.number_of_reads = 0
        self.valid_responses = 0
        self.reads_label.config(text="0")
        self.responses_label.config(text="0")
        self.data_display.insert(tk.END, "[计数器已重置]\n")
        self.data_display.see(tk.END)
        
    def clear_display(self):
        """清除显示区域"""
        self.data_display.delete(1.0, tk.END)


def main():
    """主函数"""
    root = tk.Tk()
    app = PLCModbusGUI(root)
    
    # 窗口关闭事件
    def on_closing():
        app.disconnect_modbus()
        root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
