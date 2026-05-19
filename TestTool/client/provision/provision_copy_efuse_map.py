from pathlib import Path
import os
import sys

import paramiko

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
	sys.path.insert(0, CURRENT_DIR)

from provision_common import create_s100_ssh_client


LOCAL_FILE_NAME = "efuse_map.bin.enc"
REMOTE_FILE_PATH = "/userdata/efuse_map.bin.enc"


def copy_efuse_map_to_s100() -> bool:
	local_file_path = Path(__file__).resolve().parent / LOCAL_FILE_NAME
	if not local_file_path.exists():
		print(f"❌ 未找到文件: {local_file_path}")
		return False

	ssh_client = None
	sftp_client = None
	try:
		ssh_client = create_s100_ssh_client()
		sftp_client = ssh_client.open_sftp()
		sftp_client.put(str(local_file_path), REMOTE_FILE_PATH)
		print(f"✅ 上传成功: {local_file_path} -> {REMOTE_FILE_PATH}")
		return True
	except paramiko.AuthenticationException:
		print("❌ 认证失败，请检查私钥内容是否正确。")
		return False
	except Exception as error:
		print(f"❌ 上传失败: {error}")
		return False
	finally:
		if sftp_client is not None:
			sftp_client.close()
		if ssh_client is not None:
			ssh_client.close()


if __name__ == "__main__":
	copy_efuse_map_to_s100()
