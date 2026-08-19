"""
RAG联邦优化测试
测试RAG联邦学习优化功能
"""
import pytest
from app.services.federatedragoptimizer import (
    FederatedRAGOptimizer,
    RAGStatistics
)


class TestRAGStatistics:
    """RAG统计测试"""
    
    def test_create_statistics(self):
        """测试创建统计"""
        stats = RAGStatistics()
        
        assert stats.total_queries == 0
        assert stats.avg_retrieval_time == 0.0
        assert stats.optimal_top_k == 5
        assert stats.optimal_threshold == 0.7
    
    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        stats = RAGStatistics()
        stats.total_queries = 100
        stats.avg_retrieval_time = 0.5
        stats.optimal_top_k = 7
        stats.retrieval_success_rate = 0.85
        
        # 转换为字典
        data = stats.to_dict()
        
        assert data['total_queries'] == 100
        assert data['avg_retrieval_time'] == 0.5
        assert data['optimal_top_k'] == 7
        
        # 从字典创建
        new_stats = RAGStatistics.from_dict(data)
        
        assert new_stats.total_queries == 100
        assert new_stats.avg_retrieval_time == 0.5
        assert new_stats.optimal_top_k == 7
        assert new_stats.retrieval_success_rate == 0.85


class TestFederatedRAGOptimizer:
    """RAG联邦优化器测试"""
    
    def setup_method(self):
        """测试前设置"""
        self.optimizer = FederatedRAGOptimizer()
    
    def test_collect_client_stats(self):
        """测试收集客户端统计"""
        rag_stats = {
            'total_queries': 100,
            'avg_retrieval_time': 0.5,
            'optimal_top_k': 7,
            'optimal_threshold': 0.75,
            'retrieval_success_rate': 0.85,
            'avg_relevance_score': 0.8
        }
        
        result = self.optimizer.collect_client_stats(
            client_id='client_1',
            rag_stats=rag_stats
        )
        
        assert result['success'] is True
        assert result['client_id'] == 'client_1'
        assert result['clients_count'] == 1
        assert 'client_1' in self.optimizer.client_stats
    
    def test_analyze_retrieval_patterns(self):
        """测试分析检索模式"""
        # 添加多个客户端统计
        clients = {
            'client_1': {
                'total_queries': 100,
                'avg_retrieval_time': 0.5,
                'optimal_top_k': 7,
                'optimal_threshold': 0.75,
                'retrieval_success_rate': 0.85,
                'query_patterns': [
                    {'type': 'question', 'frequency': 50},
                    {'type': 'keyword', 'frequency': 30}
                ]
            },
            'client_2': {
                'total_queries': 150,
                'avg_retrieval_time': 0.6,
                'optimal_top_k': 5,
                'optimal_threshold': 0.70,
                'retrieval_success_rate': 0.80,
                'query_patterns': [
                    {'type': 'question', 'frequency': 60},
                    {'type': 'semantic', 'frequency': 40}
                ]
            },
            'client_3': {
                'total_queries': 120,
                'avg_retrieval_time': 0.4,
                'optimal_top_k': 6,
                'optimal_threshold': 0.72,
                'retrieval_success_rate': 0.88,
                'query_patterns': [
                    {'type': 'keyword', 'frequency': 70},
                    {'type': 'semantic', 'frequency': 20}
                ]
            }
        }
        
        for client_id, stats in clients.items():
            self.optimizer.collect_client_stats(client_id, stats)
        
        # 分析模式
        analysis = self.optimizer.analyze_retrieval_patterns()
        
        assert analysis['total_clients'] == 3
        assert analysis['total_queries'] == 370  # 100 + 150 + 120
        assert 'avg_retrieval_time' in analysis
        assert 'avg_success_rate' in analysis
        assert 'top_k_distribution' in analysis
        assert 'threshold_distribution' in analysis
        assert 'pattern_clusters' in analysis
        assert 'insights' in analysis
    
    def test_optimize_global_parameters_balanced(self):
        """测试优化全局参数（平衡策略）"""
        # 添加测试数据
        self._add_test_clients()
        
        # 优化参数
        result = self.optimizer.optimize_global_parameters(strategy='balanced')
        
        assert result['success'] is True
        assert 'params' in result
        assert 'analysis' in result
        assert 'improvement_estimation' in result
        
        params = result['params']
        assert 'top_k' in params
        assert 'similarity_threshold' in params
        assert 'reranking_strategy' in params
        assert params['optimization_strategy'] == 'balanced'
    
    def test_optimize_global_parameters_precision(self):
        """测试优化全局参数（精确率优先）"""
        self._add_test_clients()
        
        result = self.optimizer.optimize_global_parameters(strategy='precision')
        
        assert result['success'] is True
        params = result['params']
        
        # 精确率优先应该提高阈值
        assert params['similarity_threshold'] >= 0.7
        assert params['optimization_strategy'] == 'precision'
    
    def test_optimize_global_parameters_recall(self):
        """测试优化全局参数（召回率优先）"""
        self._add_test_clients()
        
        result = self.optimizer.optimize_global_parameters(strategy='recall')
        
        assert result['success'] is True
        params = result['params']
        
        # 召回率优先应该降低阈值、增加top_k
        assert params['top_k'] >= 5
        assert params['optimization_strategy'] == 'recall'
    
    def test_optimize_global_parameters_speed(self):
        """测试优化全局参数（速度优先）"""
        self._add_test_clients()
        
        result = self.optimizer.optimize_global_parameters(strategy='speed')
        
        assert result['success'] is True
        params = result['params']
        
        # 速度优先应该减少top_k
        assert params['top_k'] <= 7
        assert params['optimization_strategy'] == 'speed'
    
    def test_get_optimized_params_for_client(self):
        """测试获取客户端优化参数"""
        self._add_test_clients()
        
        # 优化全局参数
        self.optimizer.optimize_global_parameters()
        
        # 获取客户端参数
        params_result = self.optimizer.get_optimized_params_for_client('client_1')
        
        assert params_result['client_id'] == 'client_1'
        assert 'params' in params_result
        assert params_result['is_personalized'] is True
        
        # 测试不存在的客户端
        params_result2 = self.optimizer.get_optimized_params_for_client('unknown_client')
        
        assert params_result2['is_personalized'] is False
    
    def test_train_semantic_enhancement_model(self):
        """测试训练语义增强模型"""
        global_queries = [
            "什么是机器学习？",
            "如何使用Python",
            "深度学习原理",
            "人工智能应用",
            "数据科学入门"
        ]
        
        result = self.optimizer.train_semantic_enhancement_model(global_queries)
        
        assert result['success'] is True
        assert 'model_version' in result
        assert 'model_params' in result
        assert 'evaluation' in result
        
        # 验证模型版本已更新
        assert self.optimizer.global_optimal_params['semantic_model_version'] == result['model_version']
    
    def test_get_optimization_status(self):
        """测试获取优化状态"""
        # 初始状态
        status = self.optimizer.get_optimization_status()
        
        assert status['clients_count'] == 0
        assert status['has_analysis'] is False
        
        # 添加客户端后
        self._add_test_clients()
        
        status = self.optimizer.get_optimization_status()
        
        assert status['clients_count'] == 3
        assert status['has_analysis'] is True
        assert len(status['clients']) == 3
    
    def test_cluster_patterns(self):
        """测试模式聚类"""
        patterns = [
            {'type': 'question', 'frequency': 50},
            {'type': 'question', 'frequency': 60},
            {'type': 'keyword', 'frequency': 30},
            {'type': 'keyword', 'frequency': 70},
            {'type': 'semantic', 'frequency': 40}
        ]
        
        clusters = self.optimizer._cluster_patterns(patterns)
        
        assert len(clusters) == 3  # question, keyword, semantic
        
        # 验证聚类结构
        for cluster in clusters:
            assert 'type' in cluster
            assert 'count' in cluster
            assert 'percentage' in cluster
            assert 'avg_frequency' in cluster
    
    def test_generate_insights(self):
        """测试生成见解"""
        insights = self.optimizer._generate_insights(
            total_queries=300,
            avg_retrieval_time=1.5,  # 较长
            avg_success_rate=0.75,    # 偏低
            top_k_values=[5, 7, 9, 6, 8],  # 差异较大
            threshold_values=[0.7, 0.72, 0.75, 0.71],
            pattern_clusters=[
                {'type': 'question', 'count': 100, 'percentage': 50, 'avg_frequency': 55}
            ]
        )
        
        assert len(insights) > 0
        assert any('检索时间' in insight for insight in insights)
        assert any('成功率' in insight for insight in insights)
    
    def test_estimate_improvement(self):
        """测试估算改进效果"""
        analysis = {
            'avg_success_rate': 0.8,
            'avg_retrieval_time': 1.0,
            'top_k_distribution': {'std': 2.0},
            'threshold_distribution': {'std': 0.1}
        }
        
        improvement = self.optimizer._estimate_improvement(analysis)
        
        assert 'success_rate' in improvement
        assert 'retrieval_time' in improvement
        
        assert improvement['success_rate']['current'] == 0.8
        assert improvement['success_rate']['estimated'] > 0.8
        assert improvement['success_rate']['improvement'] >= 0
        
        assert improvement['retrieval_time']['current'] == 1.0
        assert improvement['retrieval_time']['estimated'] < 1.0
        assert improvement['retrieval_time']['improvement_percentage'] >= 0
    
    def _add_test_clients(self):
        """添加测试客户端数据"""
        clients = {
            'client_1': {
                'total_queries': 100,
                'avg_retrieval_time': 0.5,
                'optimal_top_k': 7,
                'optimal_threshold': 0.75,
                'retrieval_success_rate': 0.85
            },
            'client_2': {
                'total_queries': 150,
                'avg_retrieval_time': 0.6,
                'optimal_top_k': 5,
                'optimal_threshold': 0.70,
                'retrieval_success_rate': 0.80
            },
            'client_3': {
                'total_queries': 120,
                'avg_retrieval_time': 0.4,
                'optimal_top_k': 6,
                'optimal_threshold': 0.72,
                'retrieval_success_rate': 0.88
            }
        }
        
        for client_id, stats in clients.items():
            self.optimizer.collect_client_stats(client_id, stats)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

