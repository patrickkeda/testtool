"""
SN判断步骤

功能：
1. 从上下文获取SN
2. 判断SN前7位，根据规则设置id
3. 如果不符合规则，报错并停止测试
"""
from ...base import BaseStep, StepResult
from ...context import Context
from typing import Dict, Any


class SNJudgmentStep(BaseStep):
    """SN判断步骤"""
    
    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        """
        执行SN判断
        
        参数：
        - rules: 判断规则列表，每个规则包含 prefix 和 id
          示例: [{"prefix": "3040001", "id": 1}, {"prefix": "3040003", "id": 2}, {"prefix": "3040004", "id": 3}]
        """
        try:
            # 1. 获取SN
            sn = ctx.get_sn()
            if not sn or sn == "NULL":
                return self.create_failure_result(
                    "SN未设置，请先执行扫描SN步骤",
                    error="SN_NOT_SET"
                )
            
            ctx.log_info(f"开始SN判断: SN={sn}")
            
            # 2. 检查SN长度
            if len(sn) < 7:
                return self.create_failure_result(
                    f"SN长度不足7位: {sn}",
                    error="SN_TOO_SHORT"
                )
            
            # 3. 获取SN前7位
            sn_prefix = sn[:7]
            ctx.log_info(f"SN前7位: {sn_prefix}")
            
            # 4. 读取判断规则
            rules = params.get("rules", [])
            
            # 如果没有提供规则，使用默认规则
            if not rules:
                rules = [
                    {"prefix": "3040001", "id": 1},
                    {"prefix": "3040003", "id": 2},
                    {"prefix": "3040004", "id": 3}
                ]
            
            # 5. 遍历规则进行匹配
            matched_id = None
            for rule in rules:
                prefix = str(rule.get("prefix", ""))
                rule_id = rule.get("id")
                
                if sn_prefix == prefix:
                    matched_id = rule_id
                    ctx.log_info(f"SN前7位匹配规则: {prefix} -> id={rule_id}")
                    break
            
            # 6. 如果未匹配到任何规则，报错
            if matched_id is None:
                error_msg = f"SN前7位 '{sn_prefix}' 不符合任何规则，停止测试"
                ctx.log_error(error_msg)
                return self.create_failure_result(
                    error_msg,
                    error="SN_PREFIX_NOT_MATCHED",
                    data={"sn": sn, "prefix": sn_prefix, "rules": rules}
                )
            
            # 7. 保存id到上下文
            ctx.set_data("id", matched_id)
            ctx.log_info(f"SN判断成功: SN={sn}, 前7位={sn_prefix}, id={matched_id}")
            
            # 8. 返回成功结果
            result_data = {
                "sn": sn,
                "prefix": sn_prefix,
                "id": matched_id
            }
            
            return self.create_success_result(
                result_data,
                f"SN判断成功: 前7位={sn_prefix}, id={matched_id}"
            )
            
        except Exception as e:
            ctx.log_error(f"SN判断执行异常: {e}", exc_info=True)
            return self.create_failure_result(
                f"SN判断执行异常: {e}",
                error=str(e)
            )



