"""Compose model call quotas with the existing resource lease authority."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
from time import monotonic
from uuid import uuid4

from adapters.model.protocols import StructuredGenerationError
from components.resource.scheduler.model_quota import make_model_quota_coordinator
from contracts.resource import ModelQuotaPolicy


def _total_tokens(usage):
    if not isinstance(usage, dict):
        return None
    for key in ("total_tokens", "totalTokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    for first, second in (("prompt_tokens", "completion_tokens"), ("input_tokens", "output_tokens")):
        values = [usage.get(first), usage.get(second)]
        if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in values):
            return sum(values)
    return None


class ModelCallQuota:
    """One charge per actual adapter attempt, including failover and streaming.

    Input bytes are a conservative estimate, never reported as provider usage.
    A missing usage report keeps the reservation. Monetary budgets are separate.
    """

    def __init__(self, *, coordinator, policy: ModelQuotaPolicy | None, validate=None, audit=None):
        self.coordinator = coordinator
        self.quota = make_model_quota_coordinator(coordinator) if policy is not None else None
        self.policy = policy
        self.validate = validate
        self.audit = audit
        self.resource_id = "model-quota:" + sha256(policy.scope.encode()).hexdigest() if policy else None

    @asynccontextmanager
    async def __call__(self, request, timeout):
        if self.policy is None:
            if self.validate:
                self.validate()
            yield _Charge()
            return
        if not math.isfinite(timeout) or timeout <= 0:
            raise StructuredGenerationError("MODEL_TIMEOUT_INVALID", "model timeout must be positive")
        tokens = 0
        if self.policy.tokens_per_minute is not None:
            output = next((request.options[key] for key in ("max_completion_tokens", "max_output_tokens", "max_tokens")
                           if isinstance(request.options.get(key), int) and request.options[key] > 0), None)
            if output is None:
                raise StructuredGenerationError("MODEL_QUOTA_OUTPUT_UNBOUNDED", "token quota requires a bounded model output")
            tokens = len(json.dumps([request.messages, request.response_schema, request.options], ensure_ascii=False).encode()) + output
            if tokens > self.policy.tokens_per_minute:
                raise StructuredGenerationError("MODEL_QUOTA_REQUEST_TOO_LARGE", "model request exceeds its shared token quota")
        deadline = monotonic() + timeout
        lease = reservation = None
        invoked = False
        charge = _Charge()
        try:
            while monotonic() < deadline:
                if self.validate:
                    self.validate()
                now = datetime.now(timezone.utc)
                identity = "model-call:" + uuid4().hex
                ttl = timedelta(seconds=timeout + 60)
                lease = self.coordinator.acquire(
                    lease_id=identity, resource_id=self.resource_id, capacity=self.policy.max_concurrency,
                    run_id=request.commit_id or request.request_id, step_id="model-call", attempt_id=identity,
                    slot_count=1, ttl=ttl, now=now,
                )
                if lease is not None:
                    reservation = self.quota.reserve(policy=self.policy, reservation_id=identity, tokens=tokens, ttl=ttl)
                    if reservation is not None:
                        break
                    self.coordinator.release(lease.lease_id)
                    lease = None
                await asyncio.sleep(min(.05, max(0, deadline - monotonic())))
            if reservation is None:
                raise StructuredGenerationError("MODEL_QUOTA_TIMEOUT", "shared model quota was not available before the call deadline")
            if self.validate:
                self.validate()
            invoked = True
            try:
                yield charge
            except BaseException as error:
                charge.observe(getattr(error, "usage", None) or (getattr(error, "audit", None) or {}).get("usage"))
                raise
        finally:
            try:
                if reservation is not None:
                    record = self.quota.settle(reservation, charge.tokens, invoked=invoked)
                    if self.audit:
                        self.audit(self.resource_id, dict(record, requestId=request.request_id))
            finally:
                if lease is not None:
                    self.coordinator.release(lease.lease_id)


class _Charge:
    def __init__(self):
        self.tokens = None

    def observe(self, usage):
        actual = _total_tokens(usage)
        if actual is not None:
            self.tokens = actual
