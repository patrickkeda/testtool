"""
审计服务实现
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict

from .interfaces import IAuditService
from .models import AuditLog, AuditFilter, AuditReport

logger = logging.getLogger(__name__)


class AuditService(IAuditService):
    """审计服务实现"""
    
    def __init__(self):
        self.audit_logs: List[AuditLog] = []
        self.max_logs = 10000  # 最大日志数量
        self.retention_days = 365  # 日志保留天数
    
    async def log_event(self, user_id: str, action: str, resource: str, details: Dict[str, Any] = None, 
                       ip_address: str = "", user_agent: str = "", success: bool = True) -> bool:
        """记录审计事件"""
        try:
            # 生成审计日志ID
            log_id = str(uuid.uuid4())
            
            # 获取用户名（这里简化处理，实际应该从用户服务获取）
            username = user_id  # 简化处理
            
            # 创建审计日志
            audit_log = AuditLog(
                id=log_id,
                user_id=user_id,
                username=username,
                action=action,
                resource=resource,
                details=details or {},
                ip_address=ip_address,
                user_agent=user_agent,
                timestamp=datetime.now(),
                success=success
            )
            
            # 添加到日志列表
            self.audit_logs.append(audit_log)
            
            # 清理过期日志
            await self._cleanup_old_logs()
            
            # 限制日志数量
            if len(self.audit_logs) > self.max_logs:
                self.audit_logs = self.audit_logs[-self.max_logs:]
            
            logger.debug(f"审计事件已记录 - {action} on {resource} by {username}")
            return True
            
        except Exception as e:
            logger.error(f"记录审计事件异常: {e}")
            return False
    
    async def get_audit_logs(self, filters: AuditFilter) -> List[AuditLog]:
        """获取审计日志"""
        try:
            filtered_logs = self.audit_logs.copy()
            
            # 应用过滤条件
            if filters.user_id:
                filtered_logs = [log for log in filtered_logs if log.user_id == filters.user_id]
            
            if filters.username:
                filtered_logs = [log for log in filtered_logs if log.username == filters.username]
            
            if filters.action:
                filtered_logs = [log for log in filtered_logs if log.action == filters.action]
            
            if filters.resource:
                filtered_logs = [log for log in filtered_logs if log.resource == filters.resource]
            
            if filters.start_date:
                filtered_logs = [log for log in filtered_logs if log.timestamp >= filters.start_date]
            
            if filters.end_date:
                filtered_logs = [log for log in filtered_logs if log.timestamp <= filters.end_date]
            
            if filters.success is not None:
                filtered_logs = [log for log in filtered_logs if log.success == filters.success]
            
            if filters.ip_address:
                filtered_logs = [log for log in filtered_logs if log.ip_address == filters.ip_address]
            
            # 排序（按时间倒序）
            filtered_logs.sort(key=lambda x: x.timestamp, reverse=True)
            
            # 应用分页
            start = filters.offset
            end = start + filters.limit
            return filtered_logs[start:end]
            
        except Exception as e:
            logger.error(f"获取审计日志异常: {e}")
            return []
    
    async def generate_audit_report(self, start_date: datetime, end_date: datetime, 
                                  title: str = "审计报告") -> AuditReport:
        """生成审计报告"""
        try:
            # 创建过滤条件
            filters = AuditFilter(
                start_date=start_date,
                end_date=end_date
            )
            
            # 获取日志
            logs = await self.get_audit_logs(filters)
            
            # 统计信息
            total_events = len(logs)
            events_by_user = defaultdict(int)
            events_by_action = defaultdict(int)
            events_by_resource = defaultdict(int)
            failed_events = []
            
            for log in logs:
                events_by_user[log.username] += 1
                events_by_action[log.action] += 1
                events_by_resource[log.resource] += 1
                
                if not log.success:
                    failed_events.append(log)
            
            # 计算成功率
            success_rate = (total_events - len(failed_events)) / total_events if total_events > 0 else 0.0
            
            # 创建报告
            report = AuditReport(
                title=title,
                start_date=start_date,
                end_date=end_date,
                total_events=total_events,
                events_by_user=dict(events_by_user),
                events_by_action=dict(events_by_action),
                events_by_resource=dict(events_by_resource),
                success_rate=success_rate,
                failed_events=failed_events,
                generated_at=datetime.now()
            )
            
            logger.info(f"审计报告已生成 - {title}, 总事件数: {total_events}")
            return report
            
        except Exception as e:
            logger.error(f"生成审计报告异常: {e}")
            return AuditReport(
                title=title,
                start_date=start_date,
                end_date=end_date,
                total_events=0
            )
    
    async def get_audit_statistics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """获取审计统计信息"""
        try:
            # 创建过滤条件
            filters = AuditFilter(
                start_date=start_date,
                end_date=end_date
            )
            
            # 获取日志
            logs = await self.get_audit_logs(filters)
            
            # 基础统计
            total_events = len(logs)
            successful_events = len([log for log in logs if log.success])
            failed_events = total_events - successful_events
            success_rate = successful_events / total_events if total_events > 0 else 0.0
            
            # 按用户统计
            user_stats = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
            for log in logs:
                user_stats[log.username]["total"] += 1
                if log.success:
                    user_stats[log.username]["success"] += 1
                else:
                    user_stats[log.username]["failed"] += 1
            
            # 按操作统计
            action_stats = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
            for log in logs:
                action_stats[log.action]["total"] += 1
                if log.success:
                    action_stats[log.action]["success"] += 1
                else:
                    action_stats[log.action]["failed"] += 1
            
            # 按资源统计
            resource_stats = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0})
            for log in logs:
                resource_stats[log.resource]["total"] += 1
                if log.success:
                    resource_stats[log.resource]["success"] += 1
                else:
                    resource_stats[log.resource]["failed"] += 1
            
            # 按小时统计
            hourly_stats = defaultdict(int)
            for log in logs:
                hour = log.timestamp.hour
                hourly_stats[hour] += 1
            
            # 按日期统计
            daily_stats = defaultdict(int)
            for log in logs:
                date = log.timestamp.date()
                daily_stats[date] += 1
            
            return {
                "summary": {
                    "total_events": total_events,
                    "successful_events": successful_events,
                    "failed_events": failed_events,
                    "success_rate": success_rate
                },
                "by_user": dict(user_stats),
                "by_action": dict(action_stats),
                "by_resource": dict(resource_stats),
                "hourly_distribution": dict(hourly_stats),
                "daily_distribution": {str(k): v for k, v in daily_stats.items()},
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"获取审计统计异常: {e}")
            return {}
    
    async def _cleanup_old_logs(self):
        """清理过期日志"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            original_count = len(self.audit_logs)
            self.audit_logs = [log for log in self.audit_logs if log.timestamp >= cutoff_date]
            cleaned_count = original_count - len(self.audit_logs)
            
            if cleaned_count > 0:
                logger.info(f"已清理 {cleaned_count} 条过期审计日志")
                
        except Exception as e:
            logger.error(f"清理过期日志异常: {e}")
    
    async def get_recent_events(self, limit: int = 100) -> List[AuditLog]:
        """获取最近的事件"""
        try:
            # 按时间倒序排序，取最新的记录
            sorted_logs = sorted(self.audit_logs, key=lambda x: x.timestamp, reverse=True)
            return sorted_logs[:limit]
        except Exception as e:
            logger.error(f"获取最近事件异常: {e}")
            return []
    
    async def get_failed_events(self, limit: int = 100) -> List[AuditLog]:
        """获取失败的事件"""
        try:
            failed_logs = [log for log in self.audit_logs if not log.success]
            sorted_logs = sorted(failed_logs, key=lambda x: x.timestamp, reverse=True)
            return sorted_logs[:limit]
        except Exception as e:
            logger.error(f"获取失败事件异常: {e}")
            return []
    
    async def get_user_activity(self, user_id: str, days: int = 30) -> List[AuditLog]:
        """获取用户活动"""
        try:
            start_date = datetime.now() - timedelta(days=days)
            filters = AuditFilter(
                user_id=user_id,
                start_date=start_date
            )
            return await self.get_audit_logs(filters)
        except Exception as e:
            logger.error(f"获取用户活动异常: {e}")
            return []
    
    async def get_security_events(self, limit: int = 100) -> List[AuditLog]:
        """获取安全相关事件"""
        try:
            security_actions = ["login", "logout", "password_change", "user_create", "user_delete", "permission_change"]
            security_logs = [log for log in self.audit_logs if log.action in security_actions]
            sorted_logs = sorted(security_logs, key=lambda x: x.timestamp, reverse=True)
            return sorted_logs[:limit]
        except Exception as e:
            logger.error(f"获取安全事件异常: {e}")
            return []
    
    async def export_audit_logs(self, filters: AuditFilter, format: str = "json") -> str:
        """导出审计日志"""
        try:
            logs = await self.get_audit_logs(filters)
            
            if format == "json":
                import json
                return json.dumps([{
                    "id": log.id,
                    "user_id": log.user_id,
                    "username": log.username,
                    "action": log.action,
                    "resource": log.resource,
                    "details": log.details,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "timestamp": log.timestamp.isoformat(),
                    "success": log.success
                } for log in logs], indent=2, ensure_ascii=False)
            elif format == "csv":
                import csv
                import io
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["ID", "用户ID", "用户名", "操作", "资源", "IP地址", "时间", "成功"])
                for log in logs:
                    writer.writerow([
                        log.id,
                        log.user_id,
                        log.username,
                        log.action,
                        log.resource,
                        log.ip_address,
                        log.timestamp.isoformat(),
                        log.success
                    ])
                return output.getvalue()
            else:
                raise ValueError(f"不支持的导出格式: {format}")
                
        except Exception as e:
            logger.error(f"导出审计日志异常: {e}")
            return ""
    
    async def get_audit_summary(self) -> Dict[str, Any]:
        """获取审计摘要"""
        try:
            total_logs = len(self.audit_logs)
            successful_logs = len([log for log in self.audit_logs if log.success])
            failed_logs = total_logs - successful_logs
            
            # 最近24小时的活动
            recent_cutoff = datetime.now() - timedelta(hours=24)
            recent_logs = [log for log in self.audit_logs if log.timestamp >= recent_cutoff]
            
            # 最活跃的用户
            user_activity = defaultdict(int)
            for log in self.audit_logs:
                user_activity[log.username] += 1
            
            most_active_user = max(user_activity.items(), key=lambda x: x[1]) if user_activity else ("无", 0)
            
            return {
                "total_logs": total_logs,
                "successful_logs": successful_logs,
                "failed_logs": failed_logs,
                "success_rate": successful_logs / total_logs if total_logs > 0 else 0.0,
                "recent_24h": len(recent_logs),
                "most_active_user": most_active_user[0],
                "most_active_count": most_active_user[1],
                "oldest_log": min(self.audit_logs, key=lambda x: x.timestamp).timestamp if self.audit_logs else None,
                "newest_log": max(self.audit_logs, key=lambda x: x.timestamp).timestamp if self.audit_logs else None
            }
            
        except Exception as e:
            logger.error(f"获取审计摘要异常: {e}")
            return {}
