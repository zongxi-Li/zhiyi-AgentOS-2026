from datetime import datetime, timedelta, timezone

import pytest

from contracts.resource import ModelQuotaPolicy
from components.resource.scheduler.leases import InMemoryLeaseCoordinator, RedisLeaseCoordinator
from components.resource.scheduler.model_quota import (
    InMemoryModelQuotaCoordinator, RedisModelQuotaCoordinator, make_model_quota_coordinator,
)
from components.resource.scheduler.models import SchedulerUnavailable


NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)


def _policy(**values):
    return ModelQuotaPolicy(scope="shared-account", maxConcurrency=2, **values)


def _reserve(coordinator, identity, *, tokens=4, seconds=0, policy=None):
    return coordinator.reserve(policy=policy or _policy(tokensPerMinute=10), reservation_id=identity,
                               tokens=tokens, now=NOW + timedelta(seconds=seconds))


def test_shared_tokens_refund_actual_usage_but_retain_full_settlement_window():
    coordinator = InMemoryModelQuotaCoordinator()
    first = _reserve(coordinator, "first", tokens=8)
    assert first and _reserve(coordinator, "blocked") is None
    audit = coordinator.settle(first, 2, now=NOW + timedelta(seconds=50))
    assert audit["actualTokens"] == 2 and audit["status"] == "settled"
    assert _reserve(coordinator, "second", tokens=8, seconds=61)
    assert _reserve(coordinator, "still-blocked", tokens=1, seconds=109) is None
    assert _reserve(coordinator, "third", tokens=1, seconds=110)


def test_inflight_and_unknown_tokens_do_not_expire_after_one_minute():
    coordinator = InMemoryModelQuotaCoordinator()
    first = _reserve(coordinator, "first", tokens=10)
    assert first and _reserve(coordinator, "blocked", seconds=65) is None
    assert coordinator.settle(first, None, now=NOW + timedelta(seconds=590))["status"] == "unknown"
    assert _reserve(coordinator, "still-blocked", seconds=620) is None
    assert _reserve(coordinator, "after-expiry", seconds=650)


def test_actual_token_overrun_becomes_debt_and_rpm_is_not_refunded_on_completion():
    coordinator = InMemoryModelQuotaCoordinator()
    policy = _policy(requestsPerMinute=1, tokensPerMinute=10)
    first = _reserve(coordinator, "first", policy=policy)
    assert first
    coordinator.settle(first, 12, now=NOW + timedelta(seconds=20))
    assert _reserve(coordinator, "rpm-blocked", tokens=0, seconds=30, policy=policy) is None
    assert _reserve(coordinator, "debt-blocked", tokens=0, seconds=61, policy=policy) is None
    assert _reserve(coordinator, "after-expiry", seconds=80, policy=policy)


def test_only_proven_uninvoked_requests_release_request_and_token_quota():
    coordinator = InMemoryModelQuotaCoordinator()
    policy = _policy(requestsPerMinute=1, tokensPerMinute=10)
    first = _reserve(coordinator, "first", tokens=10, policy=policy)
    assert first
    assert coordinator.settle(first, None, invoked=False, now=NOW)["status"] == "cancelled"
    assert _reserve(coordinator, "replacement", tokens=10, policy=policy)
    with pytest.raises(ValueError, match="identity"):
        _reserve(coordinator, "first", tokens=10, policy=policy)


def test_scope_policy_and_reservation_identities_cannot_be_reinterpreted():
    coordinator = InMemoryModelQuotaCoordinator()
    first = _reserve(coordinator, "first")
    assert first == _reserve(coordinator, "first")
    with pytest.raises(ValueError, match="identity"):
        _reserve(coordinator, "first", tokens=3)
    with pytest.raises(ValueError, match="policy"):
        _reserve(coordinator, "different-policy", policy=_policy(tokensPerMinute=100))
    coordinator.settle(first, 3, now=NOW)
    with pytest.raises(ValueError, match="settlement"):
        coordinator.settle(first, 0, now=NOW)


class _Redis:
    def __init__(self, result):
        self.result, self.calls = result, []

    def eval(self, *args):
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_redis_admission_uses_one_atomic_server_clock_decision():
    client = _Redis(b"limited")
    assert RedisModelQuotaCoordinator(client).reserve(policy=_policy(), reservation_id="call", tokens=2) is None
    script, keys, *args = client.calls[0]
    assert keys == 4 and "redis.call('TIME')" in script
    assert len({key.split("{")[1].split("}")[0] for key in args[:4]}) == 1
    assert args[4] == "" and args[-2] == 2


@pytest.mark.parametrize("result,error", [(b"policy_conflict", ValueError),
                                         (ConnectionError("offline"), SchedulerUnavailable)])
def test_redis_quota_fails_closed(result, error):
    with pytest.raises(error):
        _reserve(RedisModelQuotaCoordinator(_Redis(result)), "first")


def test_quota_factory_reuses_lease_authority_across_runtime_rebuilds():
    memory = InMemoryLeaseCoordinator()
    assert make_model_quota_coordinator(memory) is make_model_quota_coordinator(memory)
    redis = RedisLeaseCoordinator(_Redis(b"limited"), key_prefix="isolated")
    quota = make_model_quota_coordinator(redis)
    assert quota.client is redis.client and quota.key_prefix == "isolated:model-quota"
