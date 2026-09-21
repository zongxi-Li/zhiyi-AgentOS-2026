import pytest

from contracts.local_runtime import LocalRuntimeCapability
from helpers import make_request


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../outside.txt", "..", "C:/outside.txt"])
async def test_path_escape_is_rejected_before_file_operation(tmp_path, runtime_factory, path):
    service, _store, _resolver = runtime_factory(tmp_path)
    result = await service.execute(make_request(LocalRuntimeCapability.FS_READ, {"path": path}))
    assert result.status == "failed"
    assert result.error.code in {"PATH_OUTSIDE_WORKSPACE", "PATH_INVALID", "PATH_NOT_FOUND"}


@pytest.mark.asyncio
async def test_invalid_grant_cannot_mutate_filesystem(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    target = tmp_path / "should-not-exist.txt"
    request = make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": str(target), "content": "blocked", "overwrite": False},
        grant_id="missing",
    )
    result = await service.execute(request)
    assert result.error.code == "GRANT_NOT_FOUND"
    assert not target.exists()


@pytest.mark.asyncio
async def test_shell_exec_is_declared_but_never_executed(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    marker = tmp_path / "shell-marker.txt"
    result = await service.execute(make_request(
        LocalRuntimeCapability.SHELL_EXEC,
        {"command": f"echo executed > {marker}"},
    ))
    assert result.error.code == "CAPABILITY_NOT_IMPLEMENTED"
    assert not marker.exists()


@pytest.mark.asyncio
async def test_symlink_escape_is_rejected_when_supported(tmp_path, runtime_factory):
    outside = tmp_path.parent / "outside-local-runtime-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this Windows environment")
    service, _store, _resolver = runtime_factory(tmp_path)
    result = await service.execute(make_request(LocalRuntimeCapability.FS_READ, {"path": "link.txt"}))
    assert result.error.code == "PATH_OUTSIDE_WORKSPACE"
