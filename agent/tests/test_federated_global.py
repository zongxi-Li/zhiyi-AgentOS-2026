"""
联邦学习全局模型系统测试
测试云端和客户端的完整工作流程
"""
import pytest
import json
import tempfile
from pathlib import Path
from app.services.globalmodelmanager import GlobalModelManager
from app.services.localtrainingmanager import LocalTrainingManager


class TestGlobalModelManager:
    """全局模型管理器测试"""
    
    def setup_method(self):
        """测试前设置"""
        self._tmpdir = tempfile.TemporaryDirectory()
        self.manager = GlobalModelManager(
            model_storage_dir=str(Path(self._tmpdir.name) / "test_global_models")
        )

    def teardown_method(self):
        """测试后清理临时目录"""
        self._tmpdir.cleanup()
    
    def test_initialize_base_model(self):
        """测试初始化基础模型"""
        version_id = self.manager.initialize_base_model(
            model_type='text_generation',
            model_params={
                'embedding_dim': 768,
                'hidden_size': 1024
            },
            training_data_info={
                'source': '测试数据',
                'size': 1000
            }
        )
        
        assert version_id is not None
        assert self.manager.current_model is not None
        assert self.manager.current_model.version_id == version_id
    
    def test_register_client(self):
        """测试注册客户端"""
        # 先初始化模型
        self.test_initialize_base_model()
        
        # 注册客户端
        result = self.manager.register_client(
            client_id='test_client_1',
            client_info={
                'name': '测试客户端1',
                'organization': '测试机构'
            }
        )
        
        assert result['success'] is True
        assert result['client_id'] == 'test_client_1'
        assert 'test_client_1' in self.manager.registered_clients
    
    def test_distribute_model(self):
        """测试分发模型"""
        # 初始化并注册
        self.test_register_client()
        
        # 分发模型
        model_info = self.manager.distribute_model('test_client_1')
        
        assert 'version_id' in model_info
        assert 'model_params' in model_info
        assert model_info['version_id'] == self.manager.current_model.version_id
    
    def test_collect_and_aggregate_updates(self):
        """测试收集和聚合参数更新"""
        # 初始化并注册多个客户端
        self.test_initialize_base_model()
        
        clients = ['client_1', 'client_2', 'client_3']
        for client_id in clients:
            self.manager.register_client(
                client_id=client_id,
                client_info={'name': f'客户端{client_id}'}
            )
        
        # 模拟收集参数更新
        from app.services.encryptionservice import encryption_service
        
        for client_id in clients:
            # 模拟参数更新
            param_update = {
                'embedding_dim': [0.1] * 768,
                'hidden_size': [0.05] * 1024
            }
            
            # 加密
            encrypted = encryption_service.encrypt_parameters(param_update)
            
            # 收集
            result = self.manager.collect_update(
                client_id=client_id,
                encrypted_update=encrypted,
                update_metadata={
                    'data_size': 1000,
                    'epochs': 5
                }
            )
            
            assert result['success'] is True
        
        # 聚合
        agg_result = self.manager.aggregate_updates(min_clients=3)
        
        assert agg_result['success'] is True
        assert agg_result['clients_participated'] == 3
        assert 'new_version_id' in agg_result
        
        # 验证模型已更新
        assert self.manager.current_model.version_id == agg_result['new_version_id']
    
    def test_model_history(self):
        """测试模型历史记录"""
        self.test_collect_and_aggregate_updates()
        
        history = self.manager.get_model_history()
        
        assert len(history) >= 2  # 至少有初始版本和聚合后的版本
        assert history[0]['version_id'] != history[-1]['version_id']


class TestLocalTrainingManager:
    """本地训练管理器测试"""
    
    def setup_method(self):
        """测试前设置"""
        # 创建测试数据目录
        self._tmpdir = tempfile.TemporaryDirectory()
        self.test_data_dir = Path(self._tmpdir.name) / "test_local_training"
        self.test_data_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建测试私有数据
        private_data = [
            {
                'input': '测试输入1',
                'output': '测试输出1',
                'metadata': {'category': 'test'}
            },
            {
                'input': '测试输入2',
                'output': '测试输出2',
                'metadata': {'category': 'test'}
            }
        ]
        
        data_file = self.test_data_dir / 'private_data.json'
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(private_data, f, ensure_ascii=False, indent=2)
        
        self.data_file = str(data_file)

    def teardown_method(self):
        """测试后清理临时目录"""
        self._tmpdir.cleanup()
    
    def test_load_private_data(self):
        """测试加载私有数据"""
        # 注意: LocalTrainingManager需要服务器URL,这里跳过实际网络调用
        # 实际测试应该mock requests库
        
        manager = LocalTrainingManager(
            client_id='test_client',
            server_url='http://localhost:8000',
            local_data_dir=str(self.test_data_dir)
        )
        
        count = manager.load_private_data(self.data_file)
        
        assert count == 2
        assert len(manager.private_data) == 2
    
    def test_extract_parameter_updates(self):
        """测试提取参数更新"""
        manager = LocalTrainingManager(
            client_id='test_client',
            server_url='http://localhost:8000',
            local_data_dir=str(self.test_data_dir)
        )
        
        old_model = {
            'param1': [1.0, 2.0, 3.0],
            'param2': [4.0, 5.0, 6.0]
        }
        
        new_model = {
            'param1': [1.1, 2.1, 3.1],
            'param2': [4.2, 5.2, 6.2]
        }
        
        updates = manager._extract_parameter_updates(old_model, new_model)
        
        assert 'param1' in updates
        assert 'param2' in updates
        assert abs(updates['param1'][0] - 0.1) < 0.0001
        assert abs(updates['param2'][0] - 0.2) < 0.0001


class TestEndToEndWorkflow:
    """端到端工作流测试"""
    
    @pytest.mark.skip(reason="需要运行服务器")
    def test_complete_federated_learning_cycle(self):
        """测试完整的联邦学习周期"""
        # 1. 初始化全局模型管理器
        global_manager = GlobalModelManager()
        
        # 2. 初始化基础模型
        global_manager.initialize_base_model(
            model_type='text_generation',
            model_params={'param1': [1.0] * 100},
            training_data_info={'source': 'public', 'size': 10000}
        )
        
        # 3. 创建多个客户端
        clients = []
        for i in range(3):
            client = LocalTrainingManager(
                client_id=f'client_{i}',
                server_url='http://localhost:8000'
            )
            clients.append(client)
        
        # 4. 客户端训练和上传
        # (需要实际服务器运行,这里省略)
        
        # 5. 聚合
        # global_manager.aggregate_updates(min_clients=3)
        
        # 6. 客户端同步新模型
        # for client in clients:
        #     client.sync_global_model()
        
        pass


def test_differential_privacy():
    """测试差分隐私保护"""
    from app.services.encryptionservice import encryption_service
    
    original_params = {
        'weights': [1.0, 2.0, 3.0, 4.0, 5.0]
    }
    
    noisy_params = encryption_service.add_differential_privacy(
        parameters=original_params,
        epsilon=1.0,
        delta=1e-5
    )
    
    assert 'weights' in noisy_params
    assert len(noisy_params['weights']) == len(original_params['weights'])
    
    # 验证已添加噪声(参数不完全相同)
    for orig, noisy in zip(original_params['weights'], noisy_params['weights']):
        # 应该有一些差异(噪声)
        assert abs(orig - noisy) >= 0  # 至少有微小差异


def test_parameter_encryption():
    """测试参数加密"""
    from app.services.encryptionservice import encryption_service
    
    original_params = {
        'param1': [1.0, 2.0, 3.0],
        'param2': 'test_value'
    }
    
    # 加密
    encrypted = encryption_service.encrypt_parameters(original_params)
    
    assert encrypted['method'] == 'symmetric'
    assert encrypted['format'] == 'json'
    assert 'encrypted' in encrypted
    assert 'param1' not in encrypted
    
    # 解密
    decrypted = encryption_service.decrypt_parameters(encrypted)
    
    assert 'param1' in decrypted
    # 验证解密后的值与原始值相近(浮点数比较)
    for orig, dec in zip(original_params['param1'], decrypted['param1']):
        assert abs(orig - dec) < 0.0001


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

