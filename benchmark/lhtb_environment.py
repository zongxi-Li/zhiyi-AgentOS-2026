"""Thin Docker adapter for the official LHTB task/environment contract.

The Harbor Python package is intentionally not imported here.  The local
checkout does not have Harbor's Python dependency set installed, while the
official task image already contains the complete task environment.  This
adapter therefore uses Docker only for lifecycle/transport and executes the
official ``tests/test.sh`` verifier unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback is unsupported in CI
    tomllib = None  # type: ignore[assignment]

from adapters.terminal_runtime import TerminalResult, utc_now


SUPPORTED_TASK_ID = "langchain-version-migration"


class LHTBEnvironmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class LHTBTaskSpec:
    task_id: str
    task_dir: Path
    instruction: str
    task_config: dict[str, Any]
    image: str
    agent_timeout_sec: float
    verifier_timeout_sec: float
    cpus: int
    memory_mb: int
    allow_internet: bool
    agent_healthcheck: str
    verifier_healthcheck: str

    @classmethod
    def load(cls, lhtb_root: str | Path, task_id: str = SUPPORTED_TASK_ID) -> "LHTBTaskSpec":
        if task_id != SUPPORTED_TASK_ID:
            raise ValueError(f"phase 1 only supports {SUPPORTED_TASK_ID}")
        if tomllib is None:
            raise RuntimeError("Python tomllib is required to load LHTB task.toml")
        root = Path(lhtb_root).resolve()
        task_dir = root / "tasks" / task_id
        config_path = task_dir / "task.toml"
        instruction_path = task_dir / "instruction.md"
        if not config_path.is_file() or not instruction_path.is_file():
            raise FileNotFoundError(f"LHTB task files not found under {task_dir}")
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        environment = dict(config.get("environment") or {})
        verifier = dict(config.get("verifier") or {})
        verifier_environment = dict(verifier.get("environment") or {})
        agent_health = dict(environment.get("healthcheck") or {})
        verifier_health = dict(verifier_environment.get("healthcheck") or {})
        return cls(
            task_id=task_id,
            task_dir=task_dir,
            instruction=instruction_path.read_text(encoding="utf-8"),
            task_config=config,
            image=str(environment.get("docker_image") or "").strip(),
            agent_timeout_sec=float((config.get("agent") or {}).get("timeout_sec", 0)),
            verifier_timeout_sec=float(verifier.get("timeout_sec", 0)),
            cpus=int(environment.get("cpus", 1)),
            memory_mb=int(environment.get("memory_mb", 1024)),
            allow_internet=bool(environment.get("allow_internet", False)),
            agent_healthcheck=str(agent_health.get("command") or "true"),
            verifier_healthcheck=str(verifier_health.get("command") or "true"),
        )


@dataclass(frozen=True)
class LHTBVerifierResult:
    verified: bool
    reward: float
    passed_gates: int
    total_gates: int
    details: dict[str, Any]
    verifier_exit_code: int


class DockerTaskEnvironment:
    """Persistent task container with commands constrained to ``/app``."""

    def __init__(self, spec: LHTBTaskSpec) -> None:
        self.spec = spec
        self.container_name = f"agentos-lhtb-{uuid.uuid4().hex[:16]}"
        self.container_id: str | None = None
        self._closed = False

    def _docker(self, args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
        process = subprocess.run(
            ["docker", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if process.returncode != 0:
            raise LHTBEnvironmentError(
                f"docker {' '.join(args[:3])} failed with {process.returncode}: "
                f"{process.stderr[-1000:]}"
            )
        return process

    def start(self) -> None:
        if not self.spec.image:
            raise LHTBEnvironmentError("task.toml has no environment docker_image")
        network_args = [] if self.spec.allow_internet else ["--network", "none"]
        self._docker(
            [
                "create",
                "--name",
                self.container_name,
                *network_args,
                "--cpus",
                str(self.spec.cpus),
                "--memory",
                f"{self.spec.memory_mb}m",
                "--entrypoint",
                "/bin/sh",
                self.spec.image,
                "-c",
                "while :; do sleep 3600; done",
            ],
            timeout=1800.0,
        )
        started = self._docker(["start", self.container_name])
        self.container_id = started.stdout.strip() or self.container_name
        self._docker(
            ["exec", "--workdir", "/app", self.container_id, "/bin/sh", "-lc", self.spec.agent_healthcheck],
            timeout=30.0,
        )

    async def exec(
        self,
        *,
        command: str,
        cwd: str,
        env: Mapping[str, str],
        timeout_sec: float,
    ) -> TerminalResult:
        if self.container_id is None:
            raise LHTBEnvironmentError("task container is not running")
        started = asyncio.get_running_loop().time()
        started_at = utc_now()
        args = ["docker", "exec", "--workdir", cwd]
        for key, value in env.items():
            args.extend(["--env", f"{key}={value}"])
        args.extend([self.container_id, "/bin/sh", "-lc", command])
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        status = "completed"
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            if process.returncode is None:
                process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            status = "timeout"
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
            await process.communicate()
            status = "unknown"
            raise
        return_code = process.returncode
        if status == "completed" and return_code != 0:
            status = "failed"
        return TerminalResult(
            action_id="environment-exec",
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            return_code=return_code,
            started_at=started_at,
            completed_at=utc_now(),
            elapsed_ms=round((asyncio.get_running_loop().time() - started) * 1000),
            status=status,  # type: ignore[arg-type]
        )

    def export_workspace(self, destination: str | Path) -> Path:
        if self.container_id is None:
            raise LHTBEnvironmentError("task container is not running")
        path = Path(destination).resolve()
        path.mkdir(parents=True, exist_ok=True)
        self._docker(["cp", f"{self.container_id}:/app/.", str(path)])
        return path

    def _copy_tests(self, container: str) -> None:
        self._docker(["exec", container, "/bin/sh", "-lc", "mkdir -p /tests /logs/verifier"])
        self._docker(["cp", str(self.spec.task_dir / "tests"), f"{container}:/tmp/lhtb-tests"])
        self._docker(["exec", container, "/bin/sh", "-lc", "cp -a /tmp/lhtb-tests/. /tests/"])

    def run_official_verifier(self, workspace: str | Path) -> LHTBVerifierResult:
        """Run the repository's exact test.sh and consume its result files."""
        verifier_name = f"{self.container_name}-verifier"
        network_args = [] if self.spec.allow_internet else ["--network", "none"]
        result: subprocess.CompletedProcess[str] | None = None
        try:
            self._docker(
                [
                    "create",
                    "--name",
                    verifier_name,
                    *network_args,
                    "--cpus",
                    str(self.spec.cpus),
                    "--memory",
                    f"{self.spec.memory_mb}m",
                    "--entrypoint",
                    "/bin/sh",
                    self.spec.image,
                    "-c",
                    "while :; do sleep 3600; done",
                ],
                timeout=1800.0,
            )
            self._docker(["start", verifier_name])
            self._docker(["exec", verifier_name, "/bin/sh", "-lc", self.spec.verifier_healthcheck])
            workspace_path = Path(workspace).resolve()
            self._docker(["cp", str(workspace_path), f"{verifier_name}:/tmp/lhtb-workspace"])
            self._docker(["exec", verifier_name, "/bin/sh", "-lc", "cp -a /tmp/lhtb-workspace/. /app/"])
            self._copy_tests(verifier_name)
            result = subprocess.run(
                ["docker", "exec", verifier_name, "/bin/bash", "/tests/test.sh"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.spec.verifier_timeout_sec,
                check=False,
            )
            reward_text = self._read_container_file(verifier_name, "/logs/verifier/reward.txt")
            details_text = self._read_container_file(verifier_name, "/logs/verifier/migration_details.json")
            try:
                reward = float(reward_text.strip())
            except (TypeError, ValueError):
                reward = 0.0
            try:
                details = json.loads(details_text) if details_text.strip() else {}
            except json.JSONDecodeError:
                details = {"raw_details_unparseable": True}
            gates = details.get("gates") if isinstance(details, dict) else {}
            passed = sum(1 for value in gates.values() if value is True) if isinstance(gates, dict) else 0
            total = 18
            return LHTBVerifierResult(
                verified=result.returncode == 0,
                reward=reward,
                passed_gates=passed,
                total_gates=total,
                details=details if isinstance(details, dict) else {},
                verifier_exit_code=result.returncode,
            )
        finally:
            try:
                self._docker(["rm", "-f", verifier_name], timeout=120.0)
            except Exception:
                pass

    def _read_container_file(self, container: str, path: str) -> str:
        process = self._docker(["exec", container, "/bin/sh", "-lc", f"cat {path}"], timeout=30.0)
        return process.stdout

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.container_id:
            try:
                self._docker(["rm", "-f", self.container_id], timeout=120.0)
            except Exception:
                pass


__all__ = [
    "DockerTaskEnvironment",
    "LHTBEnvironmentError",
    "LHTBTaskSpec",
    "LHTBVerifierResult",
    "SUPPORTED_TASK_ID",
]
