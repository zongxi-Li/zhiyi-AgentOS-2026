import tempfile
import copy
from pathlib import Path
import pytest

from app.services.globalmodelmanager import GlobalModelManager, ParameterDecoderUnavailable


class TestGlobalModelManager:
    def setup_method(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.manager = GlobalModelManager(
            model_storage_dir=str(Path(self._tmpdir.name) / "test_global_models"),
            parameter_decoder=lambda update: copy.deepcopy(update["testParameters"]),
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

        for client_id in clients:
            # Aggregation owns the numeric update; cryptography belongs to the
            # explicitly injected decoder, not the removed legacy singleton.
            encrypted = {"testParameters": {"embedding_dim": [0.1] * 768, "hidden_size": [0.05] * 1024}}
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


@pytest.mark.parametrize("decoder", [None, "failed"])
def test_unavailable_or_failed_decoder_preserves_model_and_pending_updates(tmp_path, decoder):
    def fail(_update):
        raise ValueError("decoder rejected the update")
    manager = GlobalModelManager(str(tmp_path), parameter_decoder=fail if decoder else None)
    manager.initialize_base_model("text_generation", {"weights": [1.0]}, {})
    manager.register_client("client", {})
    manager.collect_update("client", {"encrypted": "opaque"}, {"data_size": 1})
    model, pending, history = manager.current_model, copy.deepcopy(manager.pending_updates), list(manager.version_history)
    with pytest.raises(ParameterDecoderUnavailable if decoder is None else ValueError):
        manager.aggregate_updates(min_clients=1)
    assert manager.current_model is model
    assert manager.pending_updates == pending and manager.version_history == history


async def test_aggregate_api_reports_unavailable_decoder(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.api import federatedglobal
    manager = GlobalModelManager(str(tmp_path))
    manager.initialize_base_model("text_generation", {"weights": [1.0]}, {})
    manager.register_client("client", {})
    manager.collect_update("client", {"encrypted": "opaque"}, {"data_size": 1})
    monkeypatch.setattr(federatedglobal, "global_model_manager", manager)
    app = FastAPI()
    app.include_router(federatedglobal.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/global-model/aggregate", params={"min_clients": 1})
    assert response.status_code == 503
    assert "opaque" not in response.text
    assert len(manager.pending_updates) == 1
