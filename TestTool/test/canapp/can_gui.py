"""
CAN通信GUI界面
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
from datetime import datetime
from can_sender import CANProtocolSender, CANMessage, USBCAN2

class CANGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CAN通信工具")
        self.root.geometry("900x700")
        
        self.sender = None
        self.receive_count = 0
        
        self.create_widgets()
        
    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # ========== 设备连接区域 ==========
        conn_frame = ttk.LabelFrame(main_frame, text="设备连接", padding="10")
        conn_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(conn_frame, text="设备类型:").grid(row=0, column=0, padx=5)
        self.device_type_var = tk.StringVar(value="4")
        ttk.Entry(conn_frame, textvariable=self.device_type_var, width=10).grid(row=0, column=1, padx=5)
        
        ttk.Label(conn_frame, text="设备索引:").grid(row=0, column=2, padx=5)
        self.device_index_var = tk.StringVar(value="0")
        ttk.Entry(conn_frame, textvariable=self.device_index_var, width=10).grid(row=0, column=3, padx=5)
        
        ttk.Label(conn_frame, text="通道:").grid(row=0, column=4, padx=5)
        self.channel_var = tk.StringVar(value="0")
        ttk.Entry(conn_frame, textvariable=self.channel_var, width=10).grid(row=0, column=5, padx=5)
        
        ttk.Label(conn_frame, text="波特率:").grid(row=0, column=6, padx=5)
        self.baud_rate_var = tk.StringVar(value="500000")
        ttk.Entry(conn_frame, textvariable=self.baud_rate_var, width=10).grid(row=0, column=7, padx=5)
        
        self.connect_btn = ttk.Button(conn_frame, text="连接设备", command=self.connect_device)
        self.connect_btn.grid(row=0, column=8, padx=5)
        
        self.disconnect_btn = ttk.Button(conn_frame, text="断开设备", command=self.disconnect_device, state=tk.DISABLED)
        self.disconnect_btn.grid(row=0, column=9, padx=5)
        
        self.status_label = ttk.Label(conn_frame, text="状态: 未连接", foreground="red")
        self.status_label.grid(row=1, column=0, columnspan=10, pady=5, sticky=tk.W)
        
        # ========== 快速发送区域 ==========
        quick_frame = ttk.LabelFrame(main_frame, text="快速发送（预设消息）", padding="10")
        quick_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 第一行：写入发送参数（不变）
        ttk.Label(quick_frame, text="写入发送参数:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(quick_frame, text="帧ID: 00 00 06 01", font=("Courier", 9)).grid(row=0, column=1, padx=5)
        ttk.Label(quick_frame, text="数据: 23 00 61 2A 00 08 01 00", font=("Courier", 9)).grid(row=0, column=2, padx=5)
        ttk.Button(quick_frame, text="发送", command=self.send_quick_msg1).grid(row=0, column=3, padx=5)
        
        # 第二行：写入应答参数（修改）
        ttk.Label(quick_frame, text="写入应答参数:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Label(quick_frame, text="帧ID: 00 00 06 01", font=("Courier", 9)).grid(row=1, column=1, padx=5)
        ttk.Label(quick_frame, text="数据: 23 00 61 2A 00 00 01 00", font=("Courier", 9)).grid(row=1, column=2, padx=5)
        ttk.Button(quick_frame, text="发送", command=self.send_quick_msg2).grid(row=1, column=3, padx=5)
        
        # 第三行：新增
        ttk.Label(quick_frame, text="消息3:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Label(quick_frame, text="帧ID: 00 00 06 01", font=("Courier", 9)).grid(row=2, column=1, padx=5)
        ttk.Label(quick_frame, text="数据: 2F 00 61 05 02 00 00 00", font=("Courier", 9)).grid(row=2, column=2, padx=5)
        ttk.Button(quick_frame, text="发送", command=self.send_quick_msg3).grid(row=2, column=3, padx=5)
        
        # 第四行：新增
        ttk.Label(quick_frame, text="消息4:").grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Label(quick_frame, text="帧ID: 00 00 06 02", font=("Courier", 9)).grid(row=3, column=1, padx=5)
        ttk.Label(quick_frame, text="数据: 23 00 61 2A 00 00 01 00", font=("Courier", 9)).grid(row=3, column=2, padx=5)
        ttk.Button(quick_frame, text="发送", command=self.send_quick_msg4).grid(row=3, column=3, padx=5)
        
        # 第五行：新增
        ttk.Label(quick_frame, text="消息5:").grid(row=4, column=0, sticky=tk.W, pady=5)
        ttk.Label(quick_frame, text="帧ID: 00 00 06 02", font=("Courier", 9)).grid(row=4, column=1, padx=5)
        ttk.Label(quick_frame, text="数据: 23 00 61 2A 00 08 01 00", font=("Courier", 9)).grid(row=4, column=2, padx=5)
        ttk.Button(quick_frame, text="发送", command=self.send_quick_msg5).grid(row=4, column=3, padx=5)
        
        # ========== 自定义消息发送区域 ==========
        custom_frame = ttk.LabelFrame(main_frame, text="自定义消息发送", padding="10")
        custom_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(custom_frame, text="帧ID:").grid(row=0, column=0, sticky=tk.W)
        self.frame_id_var = tk.StringVar(value="00 00 06 01")
        self.frame_id_entry = ttk.Entry(custom_frame, textvariable=self.frame_id_var, width=30)
        self.frame_id_entry.grid(row=0, column=1, padx=5, sticky=(tk.W, tk.E))
        ttk.Label(custom_frame, text="(格式: 00 00 06 01 或 0x00000601)", font=("", 8), foreground="gray").grid(row=0, column=2, sticky=tk.W)
        
        ttk.Label(custom_frame, text="数据域:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.data_var = tk.StringVar(value="23 00 61 2A 00 08 01 00")
        self.data_entry = ttk.Entry(custom_frame, textvariable=self.data_var, width=30)
        self.data_entry.grid(row=1, column=1, padx=5, sticky=(tk.W, tk.E))
        ttk.Label(custom_frame, text="(格式: 23 00 61 2A 00 08 01 00)", font=("", 8), foreground="gray").grid(row=1, column=2, sticky=tk.W)
        
        btn_frame = ttk.Frame(custom_frame)
        btn_frame.grid(row=2, column=0, columnspan=3, pady=5)
        ttk.Button(btn_frame, text="发送自定义消息", command=self.send_custom_message).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="示例1:写入发送参数", command=self.load_example1).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="示例2:写入应答参数", command=self.load_example2).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="清空", command=self.clear_inputs).pack(side=tk.LEFT, padx=5)
        
        # ========== 接收数据区域 ==========
        receive_frame = ttk.LabelFrame(main_frame, text="接收数据", padding="10")
        receive_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        receive_frame.columnconfigure(0, weight=1)
        receive_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # 接收数据表格
        columns = ("Time", "ID", "Type", "Format", "DLC", "Data", "Count")
        self.receive_tree = ttk.Treeview(receive_frame, columns=columns, show="headings", height=10)
        self.receive_tree.heading("Time", text="时间")
        self.receive_tree.heading("ID", text="帧ID")
        self.receive_tree.heading("Type", text="帧类型")
        self.receive_tree.heading("Format", text="帧格式")
        self.receive_tree.heading("DLC", text="DLC")
        self.receive_tree.heading("Data", text="数据")
        self.receive_tree.heading("Count", text="帧数量")
        
        self.receive_tree.column("Time", width=120)
        self.receive_tree.column("ID", width=80)
        self.receive_tree.column("Type", width=80)
        self.receive_tree.column("Format", width=80)
        self.receive_tree.column("DLC", width=50)
        self.receive_tree.column("Data", width=200)
        self.receive_tree.column("Count", width=60)
        
        scrollbar = ttk.Scrollbar(receive_frame, orient="vertical", command=self.receive_tree.yview)
        self.receive_tree.configure(yscrollcommand=scrollbar.set)
        
        self.receive_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # 接收控制按钮
        recv_btn_frame = ttk.Frame(receive_frame)
        recv_btn_frame.grid(row=1, column=0, columnspan=2, pady=5)
        
        self.start_receive_btn = ttk.Button(recv_btn_frame, text="开始接收", command=self.start_receiving)
        self.start_receive_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_receive_btn = ttk.Button(recv_btn_frame, text="停止接收", command=self.stop_receiving, state=tk.DISABLED)
        self.stop_receive_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(recv_btn_frame, text="清空接收数据", command=self.clear_receive_data).pack(side=tk.LEFT, padx=5)
        
        self.receive_count_label = ttk.Label(recv_btn_frame, text="接收帧数: 0")
        self.receive_count_label.pack(side=tk.LEFT, padx=20)
        
        # ========== 日志区域 ==========
        log_frame = ttk.LabelFrame(main_frame, text="发送日志", padding="10")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=8, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        ttk.Button(log_frame, text="清空日志", command=self.clear_log).grid(row=1, column=0, pady=5)
        
    def log(self, message, level="INFO"):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] [{level}] {message}\n"
        self.log_text.insert(tk.END, log_msg)
        self.log_text.see(tk.END)
    
    def connect_device(self):
        """连接设备"""
        try:
            device_type = int(self.device_type_var.get())
            device_index = int(self.device_index_var.get())
            channel = int(self.channel_var.get())
            baud_rate = int(self.baud_rate_var.get())
            
            self.sender = CANProtocolSender(device_type, device_index, channel)
            
            if self.sender.connect(baud_rate):
                self.status_label.config(text="状态: 已连接", foreground="green")
                self.connect_btn.config(state=tk.DISABLED)
                self.disconnect_btn.config(state=tk.NORMAL)
                self.start_receive_btn.config(state=tk.NORMAL)
                self.log("设备连接成功")
            else:
                self.status_label.config(text="状态: 连接失败", foreground="red")
                self.log("设备连接失败", "ERROR")
                self.log("提示：请检查：1)设备USB是否连接 2)驱动是否安装 3)设备索引是否正确", "ERROR")
                self.sender = None
                messagebox.showwarning("连接失败", 
                    "设备连接失败！\n\n请检查：\n"
                    "1. CAN设备USB是否已连接\n"
                    "2. 设备驱动是否已安装\n"
                    "3. 设备索引是否正确（如果连接了多个设备，尝试改为1、2等）\n"
                    "4. 设备类型是否正确（USBCAN1=3, USBCAN2=4, USBCANFD=6）\n\n"
                    "建议：先用示例程序Ecantest测试设备是否能正常工作")
        except Exception as e:
            messagebox.showerror("错误", f"连接设备失败: {e}")
            self.log(f"连接设备失败: {e}", "ERROR")
    
    def disconnect_device(self):
        """断开设备"""
        if self.sender:
            self.stop_receiving()
            self.sender.disconnect()
            self.sender = None
        self.status_label.config(text="状态: 未连接", foreground="red")
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        self.start_receive_btn.config(state=tk.DISABLED)
        self.log("设备已断开")
    
    def send_quick_msg1(self):
        """发送快速消息1：写入发送参数"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        frame_id = "00 00 06 01"
        data = "23 00 61 2A 00 08 01 00"
        self.log(f"快速消息1 - 帧ID: {frame_id}, 数据: {data}")
        if self.sender.send(frame_id, data):
            self.log("发送成功", "SUCCESS")
        else:
            self.log("发送失败", "ERROR")
    
    def send_quick_msg2(self):
        """发送快速消息2：写入应答参数（修改后）"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        frame_id = "00 00 06 01"
        data = "23 00 61 2A 00 00 01 00"
        self.log(f"快速消息2 - 帧ID: {frame_id}, 数据: {data}")
        if self.sender.send(frame_id, data):
            self.log("发送成功", "SUCCESS")
        else:
            self.log("发送失败", "ERROR")
    
    def send_quick_msg3(self):
        """发送快速消息3"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        frame_id = "00 00 06 01"
        data = "2F 00 61 05 02 00 00 00"
        self.log(f"快速消息3 - 帧ID: {frame_id}, 数据: {data}")
        if self.sender.send(frame_id, data):
            self.log("发送成功", "SUCCESS")
        else:
            self.log("发送失败", "ERROR")
    
    def send_quick_msg4(self):
        """发送快速消息4"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        frame_id = "00 00 06 02"
        data = "23 00 61 2A 00 00 01 00"
        self.log(f"快速消息4 - 帧ID: {frame_id}, 数据: {data}")
        if self.sender.send(frame_id, data):
            self.log("发送成功", "SUCCESS")
        else:
            self.log("发送失败", "ERROR")
    
    def send_quick_msg5(self):
        """发送快速消息5"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        frame_id = "00 00 06 02"
        data = "23 00 61 2A 00 08 01 00"
        self.log(f"快速消息5 - 帧ID: {frame_id}, 数据: {data}")
        if self.sender.send(frame_id, data):
            self.log("发送成功", "SUCCESS")
        else:
            self.log("发送失败", "ERROR")
    
    def send_custom_message(self):
        """发送自定义消息"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        frame_id = self.frame_id_var.get().strip()
        data = self.data_var.get().strip()
        
        try:
            self.log(f"帧ID: {frame_id}, 数据: {data}")
            if self.sender.send(frame_id, data):
                self.log("发送成功", "SUCCESS")
            else:
                self.log("发送失败", "ERROR")
        except Exception as e:
            messagebox.showerror("错误", f"发送消息失败: {e}")
            self.log(f"发送消息失败: {e}", "ERROR")
    
    def load_example1(self):
        """加载示例1"""
        self.frame_id_var.set("00 00 06 01")
        self.data_var.set("23 00 61 2A 00 08 01 00")
    
    def load_example2(self):
        """加载示例2"""
        self.frame_id_var.set("00 00 05 81")
        self.data_var.set("60 00 61 2A 00 00 00 00")
    
    def clear_inputs(self):
        """清空输入"""
        self.frame_id_var.set("")
        self.data_var.set("")
    
    def start_receiving(self):
        """开始接收"""
        if not self.sender:
            messagebox.showwarning("警告", "请先连接设备")
            return
        
        self.sender.start_receiving(self.on_message_received, interval_ms=30)
        self.start_receive_btn.config(state=tk.DISABLED)
        self.stop_receive_btn.config(state=tk.NORMAL)
        self.log("开始接收数据")
    
    def stop_receiving(self):
        """停止接收"""
        if self.sender:
            self.sender.stop_receiving()
        self.start_receive_btn.config(state=tk.NORMAL)
        self.stop_receive_btn.config(state=tk.DISABLED)
        self.log("停止接收数据")
    
    def on_message_received(self, message: CANMessage):
        """接收到消息的回调"""
        self.receive_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # 判断帧格式
        frame_format = "扩展" if message.frame_id > 0x7FF else "标准"
        
        # 格式化数据
        data_str = ' '.join(f'{b:02X}' for b in message.data)
        
        # 添加到表格
        self.root.after(0, self.add_received_message, {
            'time': timestamp,
            'id': f"0x{message.frame_id:X}",
            'type': '数据帧',
            'format': frame_format,
            'dlc': len(message.data),
            'data': data_str,
            'count': self.receive_count
        })
    
    def add_received_message(self, msg_info):
        """添加接收到的消息到表格（在主线程中调用）"""
        self.receive_tree.insert("", tk.END, values=(
            msg_info['time'],
            msg_info['id'],
            msg_info['type'],
            msg_info['format'],
            msg_info['dlc'],
            msg_info['data'],
            msg_info['count']
        ))
        self.receive_tree.see(tk.END)
        self.receive_count_label.config(text=f"接收帧数: {self.receive_count}")
    
    def clear_receive_data(self):
        """清空接收数据"""
        for item in self.receive_tree.get_children():
            self.receive_tree.delete(item)
        self.receive_count = 0
        self.receive_count_label.config(text="接收帧数: 0")
    
    def clear_log(self):
        """清空日志"""
        self.log_text.delete(1.0, tk.END)
    
    def on_closing(self):
        """关闭窗口"""
        self.disconnect_device()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CANGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

