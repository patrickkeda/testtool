import os
import sys

import paramiko

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
	sys.path.insert(0, CURRENT_DIR)

from provision_common import PROVISION_BIN, create_s100_ssh_client, run_cmd


def provision_step2() -> bool:
	ssh_client = paramiko.SSHClient()
	ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

	commands = [
		"chmod 777 /usr/hobot/bin/provision_tool",
		"rmmod hobot_vspi_debug > /dev/null 2>&1",
		"modprobe hobot_vspi",
		f"{PROVISION_BIN} --get-lifecycle",
		f"{PROVISION_BIN} --prov-imgs",
		f"{PROVISION_BIN} --prov-finish",
		f"{PROVISION_BIN} --get-lifecycle",
	]

	try:
		ssh_client = create_s100_ssh_client()

		for command in commands:
			print(f"[执行] {command}")
			exit_code, output = run_cmd(ssh_client, command)
			if output:
				print(output)
			if exit_code == 4 and "--get-lifecycle" in command:
				break
			if exit_code != 0 and not (
				exit_code == 3 and "--get-lifecycle" in command
			):
				print(f"❌ 命令执行失败，exit_code={exit_code}: {command}")
				return False

		print("✅ provision_step2 执行完成")
		return True

	except paramiko.AuthenticationException:
		print("❌ 认证失败，请检查私钥内容是否正确。")
		return False
	except Exception as error:
		print(f"❌ 执行过程中发生错误: {error}")
		return False
	finally:
		ssh_client.close()


if __name__ == "__main__":
	provision_step2()
