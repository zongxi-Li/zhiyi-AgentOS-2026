"""Offline repository fixtures independent of the discovery/scope API shape."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
from typing import Callable

import httpx

from adapters.hands_http import receipt_checksum


@dataclass(frozen=True)
class Repository:
    files: dict[str, str]
    listings: dict[str, list[dict[str, str]]]
    configuration_marker: str


def repository(*, source_files: int = 19, git_fanout: int = 80, cache_fanout: int = 12) -> Repository:
    """Make metadata trees large without touching the host filesystem."""
    marker = "discovery-config-actual-project-7f41"
    files = {
        "README.md": "# Review fixture\nInspect the source and its configured test command.\n",
        "package.json": json.dumps({"name": marker, "scripts": {"test": "vitest run"},
            "dependencies": {"vue": "3.5.0"}, "devDependencies": {"vitest": "3.2.0"}}, sort_keys=True),
        "pyproject.toml": '[project]\nname = "' + marker + '"\nrequires-python = ">=3.11"\n',
        ".gitignore": ".cache/\nnode_modules/\n",
        ".git/config": "[core]\nrepositoryformatversion = 0\nbare = false\n",
        ".cache/state.json": '{"cache": "generated state"}',
    }
    files.update({f"src/module_{index:02d}.py": f"def value_{index:02d}():\n    return {index}\n"
                  for index in range(source_files)})
    files.update({f".git/objects/{index:02x}/object.txt": f"object fixture {index}"
                  for index in range(git_fanout)})
    files.update({f".cache/generated_{index:02d}.json": json.dumps({"generated": index})
                  for index in range(cache_fanout)})
    entries: dict[str, dict[str, str]] = {".": {}}
    for path in files:
        parts = path.split("/")
        directory = "."
        for index, name in enumerate(parts):
            kind = "file" if index == len(parts) - 1 else "directory"
            assert entries.setdefault(directory, {}).setdefault(name, kind) == kind
            if kind == "directory":
                directory = name if directory == "." else directory + "/" + name
                entries.setdefault(directory, {})
    listings = {path: [{"name": name, "type": children[name]} for name in sorted(children)]
                for path, children in entries.items()}
    return Repository(files=files, listings=listings, configuration_marker=marker)


@dataclass
class SignedRepositoryTransport:
    """Keep the existing Hands signature/identity/idempotency implementation."""

    service: object
    repository: Repository
    forbidden_prefixes: tuple[str, ...] = ()
    before_dispatch: Callable[[dict], object] | None = None
    observations: list[dict] = field(default_factory=list)

    async def __call__(self, incoming: httpx.Request) -> httpx.Response:
        if incoming.method != "POST":
            return await self.service(incoming)
        wire = json.loads(incoming.content)
        name, path = wire["capabilityId"], wire["input"].get("path")
        if name in {"fs.list", "fs.read"}:
            assert not any(path == prefix or path.startswith(prefix + "/")
                           for prefix in self.forbidden_prefixes), (name, path)
            inventory = self.repository.listings if name == "fs.list" else self.repository.files
            assert path in inventory, ("unexpected repository path", name, path)
        snapshot = self.before_dispatch(wire) if self.before_dispatch else None
        self.observations.append({"tool": name, "path": path, "snapshot": snapshot})
        response = await self.service(incoming)
        payload = response.json()
        receipt = payload.get("receipt")
        if receipt is not None and receipt["capabilityId"] in {"fs.list", "fs.read"}:
            if name == "fs.list":
                receipt["output"]["entries"] = self.repository.listings[path]
            else:
                receipt["output"]["text"] = self.repository.files[path]
            receipt["checksum"] = receipt_checksum(receipt)
            previous_digest, _ = self.service.ledger[wire["idempotencyKey"]]
            self.service.ledger[wire["idempotencyKey"]] = previous_digest, payload
            return httpx.Response(response.status_code, json=payload)
        return response

    def paths(self, tool: str) -> Counter:
        return Counter(item["path"] for item in self.observations if item["tool"] == tool)


def install_repository(hands_stack, monkeypatch, fixture: Repository, **kwargs) -> SignedRepositoryTransport:
    transport = SignedRepositoryTransport(service=hands_stack.service, repository=fixture, **kwargs)
    client = hands_stack.runtime.local_runtime_transport._client
    monkeypatch.setattr(client, "_transport", httpx.MockTransport(transport))
    return transport
