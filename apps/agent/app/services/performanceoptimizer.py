"""
性能优化服务
优化系统各个模块的性能
"""
import logging
import asyncio
from typing import Dict, List, Optional
import time
from collections import defaultdict
import psutil

logger = logging.getLogger(__name__)


class PerformanceOptimizer:
    """性能优化器"""
    
    def __init__(self):
        self.performance_metrics = defaultdict(list)
        self.optimization_suggestions = []
        self.cache_hits = 0
        self.cache_misses = 0
    
    def optimize_system_performance(self) -> Dict:
        """
        优化系统性能
        
        Returns:
            优化结果和建议
        """
        optimizations = []
        
        # 1. 检查系统资源
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        # 2. 根据资源情况提供优化建议
        if cpu_percent > 80:
            optimizations.append({
                "type": "cpu",
                "issue": "CPU使用率过高",
                "suggestion": "减少并发任务，优化算法复杂度",
                "priority": "high"
            })
        
        if memory.percent > 85:
            optimizations.append({
                "type": "memory",
                "issue": "内存使用率过高",
                "suggestion": "清理缓存，优化数据结构",
                "priority": "high"
            })
        
        # 3. 优化建议
        suggestions = self._generate_optimization_suggestions()
        
        return {
            "system_resources": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available": memory.available
            },
            "optimizations": optimizations,
            "suggestions": suggestions,
            "cache_efficiency": self._calculate_cache_efficiency()
        }
    
    def optimize_multimodal_processing(
        self,
        processing_tasks: List[Dict]
    ) -> Dict:
        """
        优化多模态处理性能
        
        Args:
            processing_tasks: 处理任务列表
        
        Returns:
            优化结果
        """
        # 1. 任务优先级排序
        prioritized_tasks = sorted(
            processing_tasks,
            key=lambda x: x.get("priority", 5),
            reverse=True
        )
        
        # 2. 并行处理（如果资源允许）
        max_parallel = min(len(prioritized_tasks), psutil.cpu_count())
        
        # 3. 批处理相似任务
        batched_tasks = self._batch_similar_tasks(prioritized_tasks)
        
        return {
            "optimized_tasks": prioritized_tasks,
            "max_parallel": max_parallel,
            "batched_groups": len(batched_tasks),
            "estimated_time_reduction": 0.3  # 假设减少30%时间
        }
    
    def optimize_concurrent_processing(
        self,
        concurrent_limit: int = 10
    ) -> Dict:
        """
        优化并发处理性能
        
        Args:
            concurrent_limit: 并发限制
        
        Returns:
            优化配置
        """
        # 根据系统资源动态调整并发数
        cpu_count = psutil.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024**3)
        
        # 计算最优并发数
        optimal_concurrent = min(
            concurrent_limit,
            cpu_count * 2,  # CPU核心数的2倍
            int(memory_gb * 2)  # 每GB内存2个并发
        )
        
        return {
            "optimal_concurrent": optimal_concurrent,
            "current_limit": concurrent_limit,
            "system_resources": {
                "cpu_count": cpu_count,
                "memory_gb": round(memory_gb, 2)
            },
            "recommendation": "optimal" if optimal_concurrent == concurrent_limit else "adjust"
        }
    
    def optimize_voice_processing(
        self,
        audio_data: bytes,
        sample_rate: int = 16000
    ) -> Dict:
        """
        优化语音处理性能
        
        Args:
            audio_data: 音频数据
            sample_rate: 采样率
        
        Returns:
            优化结果
        """
        # 1. 降采样（如果采样率过高）
        if sample_rate > 16000:
            optimized_sample_rate = 16000
            optimization_applied = "downsampling"
        else:
            optimized_sample_rate = sample_rate
            optimization_applied = "none"
        
        # 2. 音频长度检查
        duration = len(audio_data) / (sample_rate * 2)  # 假设16位PCM
        
        # 3. 如果音频过长，分段处理
        if duration > 10.0:  # 超过10秒
            segment_size = int(10.0 * sample_rate * 2)
            segments = len(audio_data) // segment_size
            optimization_applied = f"segmentation ({segments} segments)"
        else:
            segments = 1
        
        return {
            "original_sample_rate": sample_rate,
            "optimized_sample_rate": optimized_sample_rate,
            "duration": duration,
            "segments": segments,
            "optimization_applied": optimization_applied,
            "estimated_speedup": 1.2 if optimization_applied != "none" else 1.0
        }
    
    def optimize_generation_quality(
        self,
        generation_type: str,
        quality_level: str = "balanced"
    ) -> Dict:
        """
        优化生成质量
        
        Args:
            generation_type: 生成类型（text/image/video）
            quality_level: 质量级别（speed/balanced/quality）
        
        Returns:
            优化配置
        """
        quality_configs = {
            "text": {
                "speed": {
                    "max_tokens": 200,
                    "temperature": 0.7,
                    "top_p": 0.9
                },
                "balanced": {
                    "max_tokens": 500,
                    "temperature": 0.8,
                    "top_p": 0.95
                },
                "quality": {
                    "max_tokens": 1000,
                    "temperature": 0.9,
                    "top_p": 0.99
                }
            },
            "image": {
                "speed": {
                    "resolution": "512x512",
                    "steps": 20
                },
                "balanced": {
                    "resolution": "1024x1024",
                    "steps": 50
                },
                "quality": {
                    "resolution": "2048x2048",
                    "steps": 100
                }
            },
            "video": {
                "speed": {
                    "duration": 5,
                    "fps": 24
                },
                "balanced": {
                    "duration": 10,
                    "fps": 30
                },
                "quality": {
                    "duration": 15,
                    "fps": 60
                }
            }
        }
        
        config = quality_configs.get(generation_type, {}).get(quality_level, {})
        
        return {
            "generation_type": generation_type,
            "quality_level": quality_level,
            "config": config,
            "estimated_time": self._estimate_generation_time(generation_type, quality_level)
        }
    
    def _batch_similar_tasks(self, tasks: List[Dict]) -> List[List[Dict]]:
        """批处理相似任务"""
        batches = []
        current_batch = []
        current_type = None
        
        for task in tasks:
            task_type = task.get("type", "unknown")
            
            if task_type == current_type and len(current_batch) < 5:
                current_batch.append(task)
            else:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [task]
                current_type = task_type
        
        if current_batch:
            batches.append(current_batch)
        
        return batches
    
    def _generate_optimization_suggestions(self) -> List[str]:
        """生成优化建议"""
        suggestions = []
        
        cache_efficiency = self._calculate_cache_efficiency()
        if cache_efficiency < 0.5:
            suggestions.append("缓存命中率较低，建议增加缓存大小或优化缓存策略")
        
        if len(self.performance_metrics) > 0:
            avg_latency = sum(m.get("latency", 0) for m in self.performance_metrics.get("all", [])) / max(len(self.performance_metrics.get("all", [])), 1)
            if avg_latency > 1.0:
                suggestions.append("平均延迟较高，建议优化算法或增加并发处理")
        
        return suggestions
    
    def _calculate_cache_efficiency(self) -> float:
        """计算缓存效率"""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total
    
    def _estimate_generation_time(self, generation_type: str, quality_level: str) -> float:
        """估算生成时间（秒）"""
        base_times = {
            "text": {"speed": 1.0, "balanced": 2.0, "quality": 5.0},
            "image": {"speed": 5.0, "balanced": 15.0, "quality": 30.0},
            "video": {"speed": 30.0, "balanced": 60.0, "quality": 120.0}
        }
        
        return base_times.get(generation_type, {}).get(quality_level, 2.0)


# 全局性能优化器实例
performance_optimizer = PerformanceOptimizer()





