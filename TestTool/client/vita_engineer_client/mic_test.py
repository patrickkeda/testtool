import paramiko
import io

# ================= 配置区域 =================
# 1. 机器网络拓扑配置
S100_IP = '192.168.126.2'   # 跳板机
X5_IP = '192.168.127.10'    # 目标机
USERNAME = 'root'           # 用户名相同

# 2. 共享的 id_ed25519 私钥内容（写死）
PRIVATE_KEY_STR = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACDQzz/TqfHpzHWgLr0X9rLvRJm5eGR2yfYRoAIVA+1VOwAAAJhqal3sampd
7AAAAAtzc2gtZWQyNTUxOQAAACDQzz/TqfHpzHWgLr0X9rLvRJm5eGR2yfYRoAIVA+1VOw
AAAEDw5quHp8vbuDhe6Z7vkGgRnG78gNgZiVK/rzIjofCbqtDPP9Op8enMdaAuvRf2su9E
mbl4ZHbJ9hGgAhUD7VU7AAAAEWRldkB2aXRhOmV2dGJvYXJkAQIDBA==
-----END OPENSSH PRIVATE KEY-----"""

# 3. 需要在 X5 上执行的命令
COMMAND = "arecord -D remap8ch -c 8 -r 16000 -f S16_LE -d 5 /tmp/test.wav"

# ================= 核心逻辑 =================
def check_x5_audio_record():
    # 初始化两个 SSH 客户端（一个给 s100，一个给 x5）
    jump_client = paramiko.SSHClient()
    target_client = paramiko.SSHClient()
    
    # 相当于 StrictHostKeyChecking=no，均不检查主机指纹，防止刷机后指纹变更报错
    jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    target_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        # 将字符串转为文件对象并加载为 Ed25519 密钥对，复用于两个连接
        key_file_obj = io.StringIO(PRIVATE_KEY_STR)
        pkey = paramiko.Ed25519Key.from_private_key(key_file_obj)

        # ---------------- 第一步：连接跳转机 s100 ----------------
        jump_client.connect(hostname=S100_IP, port=22, username=USERNAME, pkey=pkey)
        
        # ---------------- 第二步：打通到 x5 的隧道 ----------------
        jump_transport = jump_client.get_transport()
        # 开启一个 TCP 转发通道 (等效于 SSH ProxyJump 通道)
        channel = jump_transport.open_channel(
            kind="direct-tcpip",
            dest_addr=(X5_IP, 22),       # 目标地址：x5 的 22 端口
            src_addr=('127.0.0.1', 0)    # 源地址（占位即可，paramiko 需要这个参数）
        )

        # ---------------- 第三步：连接目标机 x5 ----------------
        # 关键点：sock=channel 告诉 target_client 不要走本地网络，而是走刚建好的隧道
        target_client.connect(
            hostname=X5_IP, 
            port=22, 
            username=USERNAME, 
            pkey=pkey, 
            sock=channel
        )

        # ---------------- 第四步：执行命令并获取结果 ----------------
        stdin, stdout, stderr = target_client.exec_command(COMMAND)
        
        # 读取输出内容 (arecord 的主要输出在 stderr 里)
        out = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')
        full_output = out + err
        
        # ---------------- 第五步：结果判断 ----------------
        if "Recording WAVE" in full_output:
            print("✅ [状态: 正常] X5 录音命令执行成功！")
            print("设备返回信息:\n" + full_output.strip())
            return True
            
        elif "audio open error" in full_output or "No such file or directory" in full_output:
            print("❌ [状态: 异常] X5 找不到声卡或打开音频设备失败！")
            print("设备返回错误:\n" + full_output.strip())
            return False
            
        else:
            print("⚠️ [状态: 未知] 出现未预期的输出！")
            print("设备返回信息:\n" + full_output.strip())
            return False

    except paramiko.AuthenticationException:
        print("❌ 认证失败，请检查私钥内容是否正确。")
    except Exception as e:
        print(f"❌ 运行过程中发生错误: {e}")
    finally:
        # 清理连接释放资源，顺序是先关 x5，再关 s100
        target_client.close()
        jump_client.close()

if __name__ == "__main__":
    check_x5_audio_record()