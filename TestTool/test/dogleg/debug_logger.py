#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""调试日志记录器 - 用于批处理脚本"""
import json
import sys
import os
from datetime import datetime

import os
import sys

# 获取脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, ".cursor")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, "debug.log")

def log(hypothesis_id, location, message, data=None):
    """记录调试日志"""
    try:
        entry = {
            "id": f"log_{int(datetime.now().timestamp() * 1000)}",
            "timestamp": int(datetime.now().timestamp() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "sessionId": "debug-session",
            "runId": os.environ.get("RUN_ID", "run1"),
            "hypothesisId": hypothesis_id
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # 静默失败，不影响主流程
        pass

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        hypothesis_id = sys.argv[1]
        location = sys.argv[2]
        message = sys.argv[3]
        data_str = sys.argv[4] if len(sys.argv) > 4 else "{}"
        try:
            data = json.loads(data_str) if data_str else {}
        except:
            data = {"raw": data_str}
        log(hypothesis_id, location, message, data)
