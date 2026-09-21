import base64
import pytest

from capabilities import FileSystemPolicy
from contracts.local_runtime import LocalRuntimeCapability
from runtime.errors import RuntimeLifecycleError

from helpers import make_request


@pytest.mark.asyncio
async def test_fs_read_list_write_and_binary_read(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_bytes(b"print('ok')\n")

    read = await service.execute(make_request(LocalRuntimeCapability.FS_READ, {"path": "src/main.py"}))
    assert read.status == "completed"
    assert read.output["path"] == "src/main.py"
    assert read.output["content"] == "print('ok')\n"

    listing = await service.execute(make_request(LocalRuntimeCapability.FS_LIST, {"path": "src"}))
    assert listing.output["entries"] == [
        {"path": "src/main.py", "name": "main.py", "type": "file"}
    ]

    write = await service.execute(make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "src/new.txt", "content": "hello", "overwrite": False},
    ))
    assert write.status == "completed"
    assert (tmp_path / "src" / "new.txt").read_text(encoding="utf-8") == "hello"

    binary = base64.b64encode(b"\x00\xff").decode("ascii")
    (tmp_path / "binary.bin").write_bytes(b"\x00\xff")
    binary_read = await service.execute(make_request(
        LocalRuntimeCapability.FS_READ, {"path": "binary.bin", "binary": True}
    ))
    assert binary_read.output["content"] == binary


@pytest.mark.asyncio
async def test_write_requires_explicit_overwrite_and_can_create_parents(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    (tmp_path / "file.txt").write_text("old", encoding="utf-8")

    refused = await service.execute(make_request(
        LocalRuntimeCapability.FS_WRITE,
        {"path": "file.txt", "content": "new", "overwrite": False},
    ))
    assert refused.error.code == "FILE_EXISTS"
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "old"

    updated = await service.execute(make_request(
        LocalRuntimeCapability.FS_WRITE,
        {
            "path": "nested/file.txt",
            "content": "new",
            "overwrite": False,
            "createParents": True,
        },
    ))
    assert updated.status == "completed"
    assert (tmp_path / "nested" / "file.txt").read_text(encoding="utf-8") == "new"


@pytest.mark.asyncio
async def test_fs_patch_is_direct_and_conflict_does_not_mutate(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    target = tmp_path / "patch.txt"
    target.write_bytes(b"one\nthree\n")
    patch = "@@ -1,2 +1,2 @@\n one\n-three\n+two\n"

    result = await service.execute(make_request(
        LocalRuntimeCapability.FS_PATCH,
        {"path": "patch.txt", "patch": patch},
    ))
    assert result.status == "completed"
    assert target.read_text(encoding="utf-8") == "one\ntwo\n"

    conflict = await service.execute(make_request(
        LocalRuntimeCapability.FS_PATCH,
        {"path": "patch.txt", "patch": "@@ -1,1 +1,1 @@\n-wrong\n+bad\n"},
    ))
    assert conflict.error.code == "PATCH_CONFLICT"
    assert target.read_text(encoding="utf-8") == "one\ntwo\n"


@pytest.mark.asyncio
async def test_fs_patch_preserves_crlf_target_line_endings(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(tmp_path)
    target = tmp_path / "crlf.txt"
    target.write_bytes(b"one\r\nthree\r\n")
    result = await service.execute(make_request(
        LocalRuntimeCapability.FS_PATCH,
        {"path": "crlf.txt", "patch": "@@ -1,2 +1,2 @@\n one\n-three\n+two\n"},
    ))
    assert result.status == "completed"
    assert target.read_bytes() == b"one\r\ntwo\r\n"


@pytest.mark.asyncio
async def test_file_limits_and_lifecycle_are_enforced(tmp_path, runtime_factory):
    service, _store, _resolver = runtime_factory(
        tmp_path, policy=FileSystemPolicy(max_read_bytes=3, max_write_bytes=3, max_list_entries=1)
    )
    (tmp_path / "large.txt").write_text("four", encoding="utf-8")
    too_large = await service.execute(make_request(
        LocalRuntimeCapability.FS_READ, {"path": "large.txt"}
    ))
    assert too_large.error.code == "FILE_SIZE_LIMIT_EXCEEDED"

    service.stop()
    with pytest.raises(RuntimeLifecycleError):
        await service.execute(make_request(LocalRuntimeCapability.FS_LIST, {"path": "."}))
