import tempfile
from pathlib import Path

from app.services.globalmodelmanager import GlobalModelManager


class TestGlobalModelManager:
    def setup_method(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.manager = GlobalModelManager(
            model_storage_dir=str(Path(self._tmpdir.name) / "test_global_models")
        )

    def teardown_method(self):
        self._tmpdir.cleanup()

    def test_initialize_base_model(self):
        version_id = self.manager.initialize_base_model(
            model_type="text_generation",
            model_params={"embedding_dim": 768, "hidden_size": 1024},
            training_data_info={"source": "test data", "size": 1000},
        )

        assert version_id is not None
        assert self.manager.current_model is not None
        assert self.manager.current_model.version_id == version_id

    def test_register_client(self):
        self.test_initialize_base_model()

        result = self.manager.register_client(
            client_id="test_client_1",
            client_info={"name": "test client", "organization": "test org"},
        )

        assert result["success"] is True
        assert result["client_id"] == "test_client_1"
        assert "test_client_1" in self.manager.registered_clients

    def test_distribute_model(self):
        self.test_register_client()

        model_info = self.manager.distribute_model("test_client_1")

        assert "version_id" in model_info
        assert "model_params" in model_info
        assert model_info["version_id"] == self.manager.current_model.version_id

    def test_collect_and_aggregate_updates(self):
        self.test_initialize_base_model()

        clients = ["client_1", "client_2", "client_3"]
        for client_id in clients:
            self.manager.register_client(
                client_id=client_id,
                client_info={"name": f"client {client_id}"},
            )

        from app.services.encryptionservice import encryption_service

        for client_id in clients:
            encrypted = encryption_service.encrypt_parameters(
                {"embedding_dim": [0.1] * 768, "hidden_size": [0.05] * 1024}
            )
            result = self.manager.collect_update(
                client_id=client_id,
                encrypted_update=encrypted,
                update_metadata={"data_size": 1000, "epochs": 5},
            )

            assert result["success"] is True

        aggregate_result = self.manager.aggregate_updates(min_clients=3)

        assert aggregate_result["success"] is True
        assert aggregate_result["clients_participated"] == 3
        assert "new_version_id" in aggregate_result
        assert self.manager.current_model.version_id == aggregate_result["new_version_id"]

    def test_model_history(self):
        self.test_collect_and_aggregate_updates()

        history = self.manager.get_model_history()

        assert len(history) >= 2
        assert history[0]["version_id"] != history[-1]["version_id"]


def test_differential_privacy():
    from app.services.encryptionservice import encryption_service

    original_params = {"weights": [1.0, 2.0, 3.0, 4.0, 5.0]}
    noisy_params = encryption_service.add_differential_privacy(
        parameters=original_params,
        epsilon=1.0,
        delta=1e-5,
    )

    assert "weights" in noisy_params
    assert len(noisy_params["weights"]) == len(original_params["weights"])


def test_parameter_encryption():
    from app.services.encryptionservice import encryption_service

    original_params = {"param1": [1.0, 2.0, 3.0], "param2": "test_value"}
    encrypted = encryption_service.encrypt_parameters(original_params)

    assert encrypted["method"] == "symmetric"
    assert encrypted["format"] == "json"
    assert "encrypted" in encrypted
    assert "param1" not in encrypted

    decrypted = encryption_service.decrypt_parameters(encrypted)

    assert "param1" in decrypted
    for original, restored in zip(original_params["param1"], decrypted["param1"]):
        assert abs(original - restored) < 0.0001
