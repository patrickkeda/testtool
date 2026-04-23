"""
生成SN测试步骤

SN规则（总长度19位）：
1-7位  : 固定前缀（默认 A010005）
8-10位 : 固定工厂/站点码（默认 AHQ）
11-14位: 当前日期编码 YY + M + D
         YY: 年份后两位 00-99
         M : 月份 A-L 表示 1-12
         D : 日期 1-9 用数字，10->A，11->B ... 31->V
15位   : 固定 'A'
16-19位: 流水号 0001-9999（每天归零，从0001开始递增）

流水号持久化：
默认保存在 Result/sn_counter.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from ...base import BaseStep, StepResult
from ...context import Context


class GenerateSNStep(BaseStep):
    """生成SN步骤（无UI）"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            prefix = str(params.get("prefix", "A010005"))
            mid = str(params.get("mid", "AHQ"))
            fixed_15 = str(params.get("fixed_15", "A"))
            counter_file = str(params.get("counter_file", "Result/sn_counter.json"))

            if len(prefix) != 7:
                return self.create_failure_result(f"SN前7位prefix长度必须为7，当前: '{prefix}'({len(prefix)})")
            if len(mid) != 3:
                return self.create_failure_result(f"SN第8-10位mid长度必须为3，当前: '{mid}'({len(mid)})")
            if len(fixed_15) != 1:
                return self.create_failure_result(f"SN第15位fixed_15长度必须为1，当前: '{fixed_15}'({len(fixed_15)})")

            date_code = self._encode_today()
            serial = self._next_serial(counter_file, date_code)

            sn = f"{prefix}{mid}{date_code}{fixed_15}{serial:04d}"
            if len(sn) != 19:
                return self.create_failure_result(f"生成SN长度异常: {len(sn)}，SN='{sn}'")

            ctx.set_sn(sn)
            ctx.log_info(f"生成SN成功: {sn} (date_code={date_code}, serial={serial:04d})")

            return self.create_success_result(
                {
                    "sn": sn,
                    "prefix": prefix,
                    "mid": mid,
                    "date_code": date_code,
                    "fixed_15": fixed_15,
                    "serial": f"{serial:04d}",
                    "counter_file": counter_file,
                },
                f"生成SN成功: {sn}",
            )
        except Exception as e:
            ctx.log_error(f"生成SN异常: {e}", exc_info=True)
            return self.create_failure_result(f"生成SN异常: {e}", error=str(e))

    @staticmethod
    def _encode_today(now: datetime | None = None) -> str:
        """按规则编码当天日期：YY + month_code + day_code"""
        now = now or datetime.now()
        yy = f"{now.year % 100:02d}"

        month_code = GenerateSNStep._encode_month(now.month)
        day_code = GenerateSNStep._encode_day(now.day)
        return f"{yy}{month_code}{day_code}"

    @staticmethod
    def _encode_month(month: int) -> str:
        # A=1, B=2, ... L=12
        if month < 1 or month > 12:
            raise ValueError(f"非法月份: {month}")
        return chr(ord("A") + month - 1)

    @staticmethod
    def _encode_day(day: int) -> str:
        # 1-9 => '1'-'9', 10=>A, 11=>B ... 31=>V
        if day < 1 or day > 31:
            raise ValueError(f"非法日期: {day}")
        alphabet = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        # day=1 -> index 0
        return alphabet[day - 1]

    @staticmethod
    def _read_counter(path: Path) -> Tuple[str, int]:
        if not path.exists():
            return "", 0
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            last_date = str(data.get("date_code", ""))
            last_serial = int(data.get("serial", 0))
            return last_date, last_serial
        except Exception:
            # 文件损坏或格式异常时，从0开始重新计数（不抛异常，避免流程整体失败）
            return "", 0

    @staticmethod
    def _write_counter(path: Path, date_code: str, serial: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"date_code": date_code, "serial": serial}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _next_serial(counter_file: str, date_code: str) -> int:
        path = Path(counter_file)
        last_date, last_serial = GenerateSNStep._read_counter(path)
        if last_date != date_code:
            next_serial = 1
        else:
            next_serial = last_serial + 1

        if next_serial < 1 or next_serial > 9999:
            raise ValueError(f"流水号超范围: {next_serial:04d} (date_code={date_code})")

        GenerateSNStep._write_counter(path, date_code, next_serial)
        return next_serial

