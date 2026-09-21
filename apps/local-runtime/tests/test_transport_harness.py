import pytest

from contracts.local_runtime import LocalRuntimeCapability
from helpers import make_request
from runtime import InProcessLocalRuntimeTransport


@pytest.mark.asyncio
async def test_pr1_client_round_trips_through_in_process_runtime(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    transport = InProcessLocalRuntimeTransport(service)
    result = await transport.execute(make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "from-transport.txt", "content": "ok", "overwrite": False},
    ))
    assert result.status == "completed"
    assert (tmp_path / "from-transport.txt").read_text(encoding="utf-8") == "ok"
