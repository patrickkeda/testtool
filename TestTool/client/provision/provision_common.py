import io

import paramiko


S100_IP = "192.168.125.2"
USERNAME = "root"

PRIVATE_KEY_STR = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACDQzz/TqfHpzHWgLr0X9rLvRJm5eGR2yfYRoAIVA+1VOwAAAJhqal3sampd
7AAAAAtzc2gtZWQyNTUxOQAAACDQzz/TqfHpzHWgLr0X9rLvRJm5eGR2yfYRoAIVA+1VOw
AAAEDw5quHp8vbuDhe6Z7vkGgRnG78gNgZiVK/rzIjofCbqtDPP9Op8enMdaAuvRf2su9E
mbl4ZHbJ9hGgAhUD7VU7AAAAEWRldkB2aXRhOmV2dGJvYXJkAQIDBA==
-----END OPENSSH PRIVATE KEY-----"""

PROVISION_BIN = "/usr/hobot/bin/provision_tool"


def create_s100_ssh_client() -> paramiko.SSHClient:
	ssh_client = paramiko.SSHClient()
	ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
	key_file_obj = io.StringIO(PRIVATE_KEY_STR)
	pkey = paramiko.Ed25519Key.from_private_key(key_file_obj)
	ssh_client.connect(hostname=S100_IP, port=22, username=USERNAME, pkey=pkey)
	return ssh_client


def run_cmd(ssh_client: paramiko.SSHClient, command: str) -> tuple[int, str]:
	stdin, stdout, stderr = ssh_client.exec_command(command)
	exit_code = stdout.channel.recv_exit_status()
	out = stdout.read().decode("utf-8", errors="ignore")
	err = stderr.read().decode("utf-8", errors="ignore")
	return exit_code, (out + err).strip()
