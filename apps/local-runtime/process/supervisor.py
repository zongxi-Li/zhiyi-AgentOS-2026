"""Thread-backed native process supervisor with bounded event history."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
from threading import Condition, RLock, Thread
from time import monotonic
from uuid import uuid4

from contracts.local_runtime import LocalRuntimeExecutionEvent, LocalRuntimeExecutionLimits
from security.windows_acl import SecurityBoundaryError, WindowsWorkspaceSecurityLease

from .models import ProcessExecutionMode, ProcessExecutionRequest
from .windows_job import ProcessContainmentError, WindowsJobObject
from .windows_process import create_restricted_process


_MAX_EVENT_BYTES = 8 * 1024
_MAX_EVENT_HISTORY = 4096
_READ_CHUNK_BYTES = 4096


@dataclass
class _ExecutionRecord:
    execution_id: str
    request_id: str
    invocation_id: str
    resource_id: str
    request: ProcessExecutionRequest
    cwd: Path
    environment: dict[str, str]
    limits: LocalRuntimeExecutionLimits
    events: deque[LocalRuntimeExecutionEvent] = field(
        default_factory=lambda: deque(maxlen=_MAX_EVENT_HISTORY)
    )
    condition: Condition = field(default_factory=lambda: Condition(RLock()))
    process: object | None = None
    job: WindowsJobObject | None = None
    security: WindowsWorkspaceSecurityLease | None = None
    worker: Thread | None = None
    next_sequence: int = 0
    state: str = "starting"
    cancel_requested: bool = False
    timeout_requested: bool = False
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    total_bytes: int = 0
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    history_truncated: bool = False


class ProcessSupervisor:
    """Start and stop process trees without leaking child processes."""

    def __init__(self, *, max_event_history: int = _MAX_EVENT_HISTORY) -> None:
        if max_event_history < 8:
            raise ValueError("max_event_history must be at least 8")
        self.max_event_history = max_event_history
        self._records: dict[str, _ExecutionRecord] = {}
        self._lock = RLock()
        self._stopping = False

    def start(
        self,
        request: ProcessExecutionRequest,
        *,
        request_id: str,
        invocation_id: str,
        resource_id: str,
        cwd: Path,
        environment: dict[str, str],
        limits: LocalRuntimeExecutionLimits,
        security: WindowsWorkspaceSecurityLease | None = None,
    ) -> str:
        execution_id = f"execution-{uuid4()}"
        temporary_root: Path | None = None
        if security is not None:
            try:
                temporary_root = security.create_execution_temp(execution_id)
            except Exception:
                security.close()
                raise
            scoped_environment = dict(environment)
            for key in tuple(scoped_environment):
                if key.upper() in {"TEMP", "TMP"}:
                    del scoped_environment[key]
            scoped_environment["TEMP"] = os.fspath(temporary_root)
            scoped_environment["TMP"] = os.fspath(temporary_root)
            environment = scoped_environment
        record = _ExecutionRecord(
            execution_id=execution_id,
            request_id=request_id,
            invocation_id=invocation_id,
            resource_id=resource_id,
            request=request,
            cwd=cwd,
            environment=environment,
            limits=limits,
            security=security,
        )
        with self._lock:
            if self._stopping:
                raise RuntimeError("process supervisor is stopping")
            record.events = deque(maxlen=self.max_event_history)
            self._records[execution_id] = record
        self._emit(record, "started", {})
        worker = Thread(
            target=self._run,
            args=(record,),
            name=f"zhiyi-process-{execution_id[-12:]}",
            daemon=True,
        )
        record.worker = worker
        worker.start()
        return execution_id

    def get_identity(self, execution_id: str) -> tuple[str, str, str, str]:
        record = self._get(execution_id)
        return record.request_id, record.invocation_id, record.resource_id, record.state

    def events(
        self,
        execution_id: str,
        *,
        after_sequence: int = -1,
        wait_seconds: float = 0.0,
    ) -> tuple[list[LocalRuntimeExecutionEvent], bool, str]:
        if after_sequence < -1:
            raise ValueError("after_sequence must not be below -1")
        record = self._get(execution_id)
        with record.condition:
            if wait_seconds > 0 and not any(
                event.sequence > after_sequence for event in record.events
            ) and record.state not in {"completed", "failed", "cancelled"}:
                record.condition.wait(timeout=min(wait_seconds, 5.0))
            selected = [event for event in record.events if event.sequence > after_sequence]
            terminal = record.state in {"completed", "failed", "cancelled"}
            return selected, terminal, record.state

    def cancel(self, execution_id: str) -> str:
        record = self._get(execution_id)
        with record.condition:
            if record.state in {"completed", "failed", "cancelled"}:
                return record.state
            record.cancel_requested = True
            process = record.process
            job = record.job
        if job is not None:
            try:
                job.terminate(process)
            except ProcessContainmentError:
                if process is not None:
                    process.kill()
        elif process is not None:
            process.kill()
        return "cancelling"

    def shutdown(self, *, join_timeout: float = 5.0) -> None:
        with self._lock:
            self._stopping = True
            records = list(self._records.values())
        for record in records:
            try:
                self.cancel(record.execution_id)
            except KeyError:
                pass
        deadline = monotonic() + max(join_timeout, 0.1)
        for record in records:
            worker = record.worker
            if worker is not None:
                worker.join(timeout=max(0.0, deadline - monotonic()))
        for record in records:
            with record.condition:
                if record.process is not None and record.process.poll() is None:
                    try:
                        if record.job is not None:
                            record.job.terminate(record.process)
                        else:
                            record.process.kill()
                    except (OSError, ProcessContainmentError):
                        pass

    def _get(self, execution_id: str) -> _ExecutionRecord:
        with self._lock:
            record = self._records.get(execution_id)
        if record is None:
            raise KeyError(execution_id)
        return record

    def _run(self, record: _ExecutionRecord) -> None:
        process: object | None = None
        job: WindowsJobObject | None = None
        readers: list[Thread] = []
        timed_out = False
        try:
            job = WindowsJobObject()
            if record.security is not None:
                process = create_restricted_process(
                    request=record.request,
                    cwd=record.cwd,
                    environment=record.environment,
                    security=record.security,
                    creation_flags=job.creation_flags(),
                )
            else:
                kwargs: dict[str, object] = {
                    "cwd": os.fspath(record.cwd),
                    "env": record.environment,
                    "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "creationflags": job.creation_flags(),
                }
                if job.start_new_session():
                    kwargs["start_new_session"] = True
                if record.request.mode is ProcessExecutionMode.DIRECT:
                    command: object = [record.request.program, *record.request.args]
                    process = subprocess.Popen(command, **kwargs)
                else:
                    process = subprocess.Popen(record.request.command or "", shell=True, **kwargs)
            job.attach(process)
            with record.condition:
                record.process = process
                record.job = job
                should_cancel = record.cancel_requested
                record.state = "running"
            if should_cancel:
                try:
                    job.terminate(process)
                except ProcessContainmentError:
                    # A concurrent cancel may have already terminated the job.
                    if not record.cancel_requested:
                        raise
            else:
                try:
                    job.resume(process)
                except ProcessContainmentError:
                    # Cancellation can race the attach/resume window. Treat a
                    # failed resume as cancellation only when the request was
                    # actually marked cancelled; otherwise fail closed.
                    if not record.cancel_requested:
                        raise
                    try:
                        process.kill()
                    except OSError:
                        pass
            readers = [
                Thread(
                    target=self._read_stream,
                    args=(record, process.stdout, "stdout"),
                    name=f"{record.execution_id}-stdout",
                    daemon=True,
                ),
                Thread(
                    target=self._read_stream,
                    args=(record, process.stderr, "stderr"),
                    name=f"{record.execution_id}-stderr",
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()
            timeout = record.request.timeout_seconds or record.limits.timeout_seconds
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                with record.condition:
                    record.timeout_requested = True
                    record.cancel_requested = True
                job.terminate(process)
                process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=2)
            with record.condition:
                cancelled = record.cancel_requested and not timed_out
            if timed_out:
                self._finish(
                    record,
                    "failed",
                    {"code": "EXECUTION_TIMEOUT", "exitCode": process.returncode},
                )
            elif cancelled:
                self._finish(record, "cancelled", {"exitCode": process.returncode})
            elif process.returncode == 0:
                self._finish(record, "completed", {"exitCode": 0})
            else:
                self._finish(record, "failed", {"code": "PROCESS_EXIT_NONZERO", "exitCode": process.returncode})
        except ProcessContainmentError:
            self._finish(record, "failed", {"code": "PROCESS_CONTAINMENT_FAILED"})
            if process is not None and process.poll() is None:
                process.kill()
        except SecurityBoundaryError:
            self._finish(record, "failed", {"code": "ISOLATION_START_FAILED"})
            if process is not None and process.poll() is None:
                process.kill()
        except (OSError, ValueError):
            self._finish(record, "failed", {"code": "PROCESS_START_FAILED"})
        finally:
            for reader in readers:
                if reader.is_alive():
                    reader.join(timeout=0.5)
            if job is not None:
                job.close()
            close_process = getattr(process, "close", None)
            if close_process is not None:
                close_process()
            if record.security is not None:
                record.security.close()
            with record.condition:
                if record.state == "starting":
                    record.state = "failed"
                record.condition.notify_all()

    def _read_stream(self, record: _ExecutionRecord, stream, name: str) -> None:
        if stream is None:
            return
        try:
            while True:
                # ``BufferedReader.read`` may wait for the full requested
                # size, which turns small command output into completion-only
                # behavior. ``read1`` returns bytes currently available.
                reader = getattr(stream, "read1", None)
                if reader is not None:
                    data = reader(_READ_CHUNK_BYTES)
                else:
                    data = os.read(stream.fileno(), _READ_CHUNK_BYTES)
                if not data:
                    return
                self._emit_output(record, name, data)
        except (OSError, ValueError):
            return

    def _emit_output(self, record: _ExecutionRecord, stream: str, data: bytes) -> None:
        with record.condition:
            stream_seen = record.stdout_bytes if stream == "stdout" else record.stderr_bytes
            stream_limit = record.limits.max_stdout_bytes if stream == "stdout" else record.limits.max_stderr_bytes
            total_limit = record.limits.max_stdout_bytes + record.limits.max_stderr_bytes
            remaining = max(0, min(stream_limit - stream_seen, total_limit - record.total_bytes))
            accepted = data[:remaining]
            if stream == "stdout":
                record.stdout_bytes += len(accepted)
            else:
                record.stderr_bytes += len(accepted)
            record.total_bytes += len(accepted)
            truncated = len(accepted) < len(data)
            already_truncated = record.stdout_truncated if stream == "stdout" else record.stderr_truncated
            if truncated:
                if stream == "stdout":
                    record.stdout_truncated = True
                else:
                    record.stderr_truncated = True
        for offset in range(0, len(accepted), _MAX_EVENT_BYTES):
            chunk = accepted[offset : offset + _MAX_EVENT_BYTES]
            self._emit(
                record,
                "stdout_delta" if stream == "stdout" else "stderr_delta",
                {"delta": chunk.decode("utf-8", errors="replace"), "bytes": len(chunk)},
            )
        if truncated and not already_truncated:
            self._emit(
                record,
                "stdout_delta" if stream == "stdout" else "stderr_delta",
                {"delta": "", "bytes": 0, "truncated": True},
            )

    def _finish(self, record: _ExecutionRecord, state: str, data: dict[str, object]) -> None:
        with record.condition:
            if record.state in {"completed", "failed", "cancelled"}:
                return
            record.state = state
        self._emit(record, state, data)

    def _emit(self, record: _ExecutionRecord, event_type: str, data: dict[str, object]) -> None:
        with record.condition:
            if len(record.events) >= self.max_event_history:
                record.history_truncated = True
            event = LocalRuntimeExecutionEvent(
                protocolVersion="1",
                requestId=record.request_id,
                invocationId=record.invocation_id,
                executionId=record.execution_id,
                eventType=event_type,
                sequence=record.next_sequence,
                data={**data, "historyTruncated": record.history_truncated}
                if record.history_truncated
                else data,
            )
            record.next_sequence += 1
            record.events.append(event)
            record.condition.notify_all()


__all__ = ["ProcessSupervisor"]
