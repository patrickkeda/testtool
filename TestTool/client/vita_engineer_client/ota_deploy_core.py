#!/usr/bin/env python3
"""兼容层：请使用 ota_deploy。本模块转发公开 API，供旧代码 ``from ota_deploy_core import ...``。"""

from ota_deploy import *  # noqa: F401,F403
