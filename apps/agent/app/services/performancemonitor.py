"""
性能监控和优化工具
监控系统性能，提供优化建议
"""
import logging
import time
import psutil
from typing import Dict, List, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.metrics_history = defaultdict(lambda: deque(maxlen=1000))  # 保留最近1000条记录
        self.alerts = []  # 告警记录
        
    def record_metric(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Dict] = None
    ):
        """
        记录性能指标
        
        Args:
            metric_name: 指标名称
            value: 指标值
            tags: 标签（可选）
        """
        metric = {
            "name": metric_name,
            "value": value,
            "tags": tags or {},
            "timestamp": datetime.now().isoformat()
        }
        
        self.metrics_history[metric_name].append(metric)
        
        # 检查是否需要告警
        self._check_alerts(metric_name, value)
    
    def _check_alerts(self, metric_name: str, value: float):
        """检查是否需要告警"""
        # 定义告警阈值
        thresholds = {
            "response_time": 5.0,  # 响应时间超过5秒告警
            "cpu_usage": 80.0,  # CPU使用率超过80%告警
            "memory_usage": 85.0,  # 内存使用率超过85%告警
            "error_rate": 0.1,  # 错误率超过10%告警
            "request_rate": 1000.0  # 请求速率超过1000/秒告警
        }
        
        threshold = thresholds.get(metric_name)
        if threshold and value > threshold:
            alert = {
                "metric_name": metric_name,
                "value": value,
                "threshold": threshold,
                "level": "warning" if value < threshold * 1.5 else "critical",
                "timestamp": datetime.now().isoformat()
            }
            
            self.alerts.append(alert)
            logger.warning(f"性能告警: {metric_name}={value}, 阈值={threshold}")
    
    def get_system_metrics(self) -> Dict:
        """获取系统性能指标"""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                "cpu": {
                    "usage_percent": cpu_percent,
                    "count": psutil.cpu_count(),
                    "freq": psutil.cpu_freq().current if psutil.cpu_freq() else None
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "used": memory.used,
                    "usage_percent": memory.percent
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "usage_percent": (disk.used / disk.total) * 100
                },
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"获取系统指标失败: {e}")
            return {}
    
    def get_metric_statistics(
        self,
        metric_name: str,
        hours: int = 1
    ) -> Dict:
        """获取指标统计"""
        metrics = list(self.metrics_history.get(metric_name, []))
        
        if not metrics:
            return {
                "count": 0,
                "avg": 0,
                "min": 0,
                "max": 0,
                "p95": 0,
                "p99": 0
            }
        
        # 过滤最近N小时的数据
        if hours > 0:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            metrics = [
                m for m in metrics
                if datetime.fromisoformat(m["timestamp"]) > cutoff_time
            ]
        
        if not metrics:
            return {
                "count": 0,
                "avg": 0,
                "min": 0,
                "max": 0,
                "p95": 0,
                "p99": 0
            }
        
        values = [m["value"] for m in metrics]
        values.sort()
        
        count = len(values)
        avg = sum(values) / count
        min_val = values[0]
        max_val = values[-1]
        p95 = values[int(count * 0.95)] if count > 0 else 0
        p99 = values[int(count * 0.99)] if count > 0 else 0
        
        return {
            "count": count,
            "avg": avg,
            "min": min_val,
            "max": max_val,
            "p95": p95,
            "p99": p99
        }
    
    def get_recent_alerts(self, limit: int = 10) -> List[Dict]:
        """获取最近的告警"""
        return self.alerts[-limit:] if limit > 0 else self.alerts
    
    def get_performance_summary(self) -> Dict:
        """获取性能摘要"""
        summary = {
            "system": self.get_system_metrics(),
            "metrics": {},
            "alerts": {
                "recent": len([a for a in self.alerts if self._is_recent_alert(a)]),
                "critical": len([a for a in self.alerts if a.get("level") == "critical"]),
                "warning": len([a for a in self.alerts if a.get("level") == "warning"])
            }
        }
        
        # 获取主要指标的统计
        main_metrics = ["response_time", "cpu_usage", "memory_usage", "error_rate", "request_rate"]
        for metric_name in main_metrics:
            if metric_name in self.metrics_history:
                summary["metrics"][metric_name] = self.get_metric_statistics(metric_name, hours=1)
        
        return summary
    
    def _is_recent_alert(self, alert: Dict, hours: int = 1) -> bool:
        """判断告警是否在最近N小时内"""
        try:
            alert_time = datetime.fromisoformat(alert["timestamp"])
            return (datetime.now() - alert_time) < timedelta(hours=hours)
        except:
            return False
    
    def clear_old_metrics(self, days: int = 7):
        """清理旧指标（保留最近N天）"""
        cutoff_time = datetime.now() - timedelta(days=days)
        
        for metric_name in list(self.metrics_history.keys()):
            metrics = list(self.metrics_history[metric_name])
            filtered = [
                m for m in metrics
                if datetime.fromisoformat(m["timestamp"]) > cutoff_time
            ]
            
            if len(filtered) < len(metrics):
                self.metrics_history[metric_name] = deque(filtered, maxlen=1000)
                logger.info(f"清理 {metric_name} 的旧指标: {len(metrics)} -> {len(filtered)}")


class PerformanceOptimizer:
    """性能优化器"""
    
    def __init__(self, monitor: PerformanceMonitor):
        self.monitor = monitor
    
    def analyze_and_suggest(self) -> Dict:
        """分析性能并给出优化建议"""
        system_metrics = self.monitor.get_system_metrics()
        suggestions = []
        
        # CPU使用率分析
        cpu_usage = system_metrics.get("cpu", {}).get("usage_percent", 0)
        if cpu_usage > 80:
            suggestions.append({
                "type": "cpu",
                "level": "warning" if cpu_usage < 90 else "critical",
                "message": f"CPU使用率过高 ({cpu_usage:.1f}%)",
                "suggestion": "考虑增加CPU资源或优化计算密集型任务"
            })
        
        # 内存使用率分析
        memory_usage = system_metrics.get("memory", {}).get("usage_percent", 0)
        if memory_usage > 85:
            suggestions.append({
                "type": "memory",
                "level": "warning" if memory_usage < 95 else "critical",
                "message": f"内存使用率过高 ({memory_usage:.1f}%)",
                "suggestion": "考虑增加内存或优化内存使用，清理缓存"
            })
        
        # 响应时间分析
        response_time_stats = self.monitor.get_metric_statistics("response_time", hours=1)
        if response_time_stats["avg"] > 3.0:
            suggestions.append({
                "type": "response_time",
                "level": "warning" if response_time_stats["avg"] < 5.0 else "critical",
                "message": f"平均响应时间过长 ({response_time_stats['avg']:.2f}秒)",
                "suggestion": "优化API响应速度，考虑使用缓存或异步处理"
            })
        
        # 错误率分析
        error_rate_stats = self.monitor.get_metric_statistics("error_rate", hours=1)
        if error_rate_stats["avg"] > 0.05:
            suggestions.append({
                "type": "error_rate",
                "level": "warning" if error_rate_stats["avg"] < 0.1 else "critical",
                "message": f"错误率过高 ({error_rate_stats['avg']*100:.2f}%)",
                "suggestion": "检查错误日志，修复常见错误"
            })
        
        return {
            "suggestions": suggestions,
            "timestamp": datetime.now().isoformat()
        }


# 全局性能监控器实例
performance_monitor = PerformanceMonitor()
performance_optimizer = PerformanceOptimizer(performance_monitor)





