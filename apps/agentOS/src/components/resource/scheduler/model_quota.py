"""Shared rolling model-call quotas; concurrency stays in LeaseCoordinator.

RPM expires 60 seconds after admission. Token reservations remain charged for
the caller's bounded transport lifetime; known usage expires 60 seconds after
settlement. Missing usage never refunds a possibly executed provider request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Protocol
from weakref import WeakKeyDictionary

from contracts.resource import ModelQuotaPolicy

from .leases import InMemoryLeaseCoordinator, LeaseCoordinator, RedisLeaseCoordinator
from .models import SchedulerUnavailable


@dataclass(frozen=True)
class ModelQuotaReservation:
    scope: str
    reservation_id: str
    reserved_tokens: int
    expires_at: datetime


class ModelQuotaCoordinator(Protocol):
    def reserve(self, *, policy: ModelQuotaPolicy, reservation_id: str, tokens: int,
                ttl: timedelta = timedelta(minutes=10), now: datetime | None = None) -> ModelQuotaReservation | None: ...

    def settle(self, reservation: ModelQuotaReservation, actual_tokens: int | None,
               invoked: bool = True, now: datetime | None = None) -> dict[str, Any]: ...


def _clock(now: datetime | None) -> int:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("model quota clock must be timezone-aware")
    return int(current.timestamp() * 1000)


def _policy_key(policy: ModelQuotaPolicy) -> str:
    return json.dumps([policy.max_concurrency, policy.requests_per_minute, policy.tokens_per_minute], separators=(",", ":"))


def _validate(reservation_id: str, tokens: int, ttl: timedelta) -> None:
    if not reservation_id.strip() or isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        raise ValueError("model quota requires a reservation id and nonnegative token count")
    if ttl < timedelta(seconds=60):
        raise ValueError("model quota reservation ttl must cover at least 60 seconds")


def _reservation(scope: str, reservation_id: str, record: dict[str, Any]) -> ModelQuotaReservation:
    return ModelQuotaReservation(scope, reservation_id, record["reservedTokens"],
                                 datetime.fromtimestamp(record["expiresAt"] / 1000, timezone.utc))


def _audit(reservation: ModelQuotaReservation, record: dict[str, Any]) -> dict[str, Any]:
    return {"scope": reservation.scope, "reservationId": reservation.reservation_id,
            "reservedTokens": reservation.reserved_tokens, "actualTokens": record["actualTokens"],
            "status": record["status"]}


class InMemoryModelQuotaCoordinator:
    def __init__(self) -> None:
        self._policies: dict[str, str] = {}
        self._records: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = RLock()
        self._sweep_at = 0

    def reserve(self, *, policy: ModelQuotaPolicy, reservation_id: str, tokens: int,
                ttl: timedelta = timedelta(minutes=10), now: datetime | None = None) -> ModelQuotaReservation | None:
        _validate(reservation_id, tokens, ttl)
        current, policy_key = _clock(now), _policy_key(policy)
        with self._lock:
            if self._policies.setdefault(policy.scope, policy_key) != policy_key:
                raise ValueError("model quota policy conflicts for shared scope")
            records = self._live(policy.scope, current)
            if record := records.get(reservation_id):
                if record["reservedTokens"] != tokens or record["status"] != "pending":
                    raise ValueError("model quota reservation identity conflicts")
                return _reservation(policy.scope, reservation_id, record)
            requests = sum(r["requestExpiresAt"] > current and r["status"] != "cancelled" for r in records.values())
            charged = sum(r["tokens"] for r in records.values())
            if ((policy.requests_per_minute is not None and requests >= policy.requests_per_minute)
                    or (policy.tokens_per_minute is not None and charged + tokens > policy.tokens_per_minute)):
                return None
            record = {"reservedTokens": tokens, "tokens": tokens, "actualTokens": None,
                      "requestExpiresAt": current + 60_000, "expiresAt": current + int(ttl.total_seconds() * 1000),
                      "status": "pending"}
            records[reservation_id] = record
            return _reservation(policy.scope, reservation_id, record)

    def settle(self, reservation: ModelQuotaReservation, actual_tokens: int | None,
               invoked: bool = True, now: datetime | None = None) -> dict[str, Any]:
        _validate_settlement(actual_tokens, invoked)
        current = _clock(now)
        with self._lock:
            record = self._live(reservation.scope, current).get(reservation.reservation_id)
            if record is None:
                return _audit(reservation, {"actualTokens": actual_tokens, "status": "expired"})
            if record["reservedTokens"] != reservation.reserved_tokens:
                raise ValueError("model quota reservation identity conflicts")
            status = "cancelled" if not invoked else "settled" if actual_tokens is not None else "unknown"
            if record["status"] in {"settled", "cancelled"}:
                if record["status"] != status or record["actualTokens"] != actual_tokens:
                    raise ValueError("model quota settlement conflicts")
            elif record["status"] != "unknown" or status != "unknown":
                record.update(status=status, actualTokens=actual_tokens,
                              tokens=0 if not invoked else actual_tokens if actual_tokens is not None else record["tokens"],
                              expiresAt=max(record["expiresAt"], current + 60_000) if status == "unknown" else current + 60_000)
            return _audit(reservation, record)

    def _live(self, scope: str, now: int) -> dict[str, dict[str, Any]]:
        if now >= self._sweep_at:
            for other in list(self._records):
                self._records[other] = {key: value for key, value in self._records[other].items() if value["expiresAt"] > now}
                if not self._records[other]:
                    del self._records[other]
            self._sweep_at = now + 60_000
        records = self._records.setdefault(scope, {})
        for key in [key for key, value in records.items() if value["expiresAt"] <= now]:
            del records[key]
        return records


def _validate_settlement(actual_tokens: int | None, invoked: bool) -> None:
    if actual_tokens is not None and (isinstance(actual_tokens, bool) or not isinstance(actual_tokens, int) or actual_tokens < 0):
        raise ValueError("actual model tokens must be a nonnegative integer")
    if not invoked and actual_tokens not in (None, 0):
        raise ValueError("an uninvoked request cannot consume tokens")


_QUOTA_LUA = r"""
local now = tonumber(ARGV[1])
if not now then
  local clock = redis.call('TIME')
  now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
end
for _, id in ipairs(redis.call('ZRANGEBYSCORE', KEYS[4], '-inf', now)) do
  redis.call('HDEL', KEYS[2], id)
end
redis.call('ZREMRANGEBYSCORE', KEYS[4], '-inf', now)
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
local id = ARGV[3]
local raw = redis.call('HGET', KEYS[2], id)
local record = raw and cjson.decode(raw) or nil
if ARGV[2] == 'reserve' then
  local policy = redis.call('GET', KEYS[1])
  if policy and policy ~= ARGV[4] then return 'policy_conflict' end
  redis.call('SET', KEYS[1], ARGV[4])
  if record then
    if record['reservedTokens'] ~= tonumber(ARGV[5]) or record['status'] ~= 'pending' then return 'identity_conflict' end
    return cjson.encode(record)
  end
  local limits = cjson.decode(ARGV[4])
  local tokens = 0
  for _, value in ipairs(redis.call('HVALS', KEYS[2])) do tokens = tokens + cjson.decode(value)['tokens'] end
  if (limits[2] ~= cjson.null and redis.call('ZCARD', KEYS[3]) >= limits[2])
    or (limits[3] ~= cjson.null and tokens + tonumber(ARGV[5]) > limits[3]) then return 'limited' end
  record = {reservedTokens=tonumber(ARGV[5]), tokens=tonumber(ARGV[5]), actualTokens=cjson.null,
            requestExpiresAt=now+60000, expiresAt=now+tonumber(ARGV[6]), status='pending'}
  redis.call('ZADD', KEYS[3], record['requestExpiresAt'], id)
else
  if not record then return 'expired' end
  if record['reservedTokens'] ~= tonumber(ARGV[4]) then return 'identity_conflict' end
  local actual = ARGV[5] == '' and cjson.null or tonumber(ARGV[5])
  local status = ARGV[6] == '0' and 'cancelled' or (actual == cjson.null and 'unknown' or 'settled')
  if record['status'] == 'settled' or record['status'] == 'cancelled' then
    if record['status'] ~= status or record['actualTokens'] ~= actual then return 'settlement_conflict' end
  elseif record['status'] ~= 'unknown' or status ~= 'unknown' then
    record['actualTokens'], record['status'] = actual, status
    if status == 'cancelled' then
      record['tokens'] = 0
      redis.call('ZREM', KEYS[3], id)
    elseif actual ~= cjson.null then record['tokens'] = actual end
    record['expiresAt'] = status == 'unknown' and math.max(record['expiresAt'], now+60000) or now+60000
  end
end
redis.call('HSET', KEYS[2], id, cjson.encode(record))
redis.call('ZADD', KEYS[4], record['expiresAt'], id)
local last = redis.call('ZREVRANGE', KEYS[4], 0, 0, 'WITHSCORES')
local ttl = math.max(1, tonumber(last[2])-now+1000)
for i=2,4 do redis.call('PEXPIRE', KEYS[i], ttl) end
return cjson.encode(record)
"""


class RedisModelQuotaCoordinator:
    """One atomic decision per operation, with no local fallback or body data."""

    def __init__(self, client: Any, *, key_prefix: str = "agentos:scheduler:model-quota") -> None:
        if not key_prefix.strip():
            raise ValueError("model quota Redis prefix cannot be blank")
        self.client, self.key_prefix = client, key_prefix.rstrip(":")

    def _eval(self, scope: str, now: datetime | None, *args: Any) -> dict[str, Any] | str:
        key = f"{self.key_prefix}:{{{sha256(scope.encode()).hexdigest()}}}"
        current = "" if now is None else _clock(now)
        try:
            result = self.client.eval(_QUOTA_LUA, 4, f"{key}:policy", f"{key}:records",
                                      f"{key}:requests", f"{key}:expiry", current, *args)
        except Exception as exc:
            raise SchedulerUnavailable("SCHEDULER_UNAVAILABLE: Redis model quota operation failed") from exc
        result = result.decode() if isinstance(result, bytes) else result
        if result in {"policy_conflict", "identity_conflict", "settlement_conflict"}:
            raise ValueError(f"model quota {result.replace('_', ' ')}")
        return json.loads(result) if result.startswith("{") else result

    def reserve(self, *, policy: ModelQuotaPolicy, reservation_id: str, tokens: int,
                ttl: timedelta = timedelta(minutes=10), now: datetime | None = None) -> ModelQuotaReservation | None:
        _validate(reservation_id, tokens, ttl)
        record = self._eval(policy.scope, now, "reserve", reservation_id, _policy_key(policy), tokens, int(ttl.total_seconds() * 1000))
        return None if record == "limited" else _reservation(policy.scope, reservation_id, record)

    def settle(self, reservation: ModelQuotaReservation, actual_tokens: int | None,
               invoked: bool = True, now: datetime | None = None) -> dict[str, Any]:
        _validate_settlement(actual_tokens, invoked)
        record = self._eval(reservation.scope, now, "settle", reservation.reservation_id,
                            reservation.reserved_tokens, "" if actual_tokens is None else actual_tokens, int(invoked))
        return _audit(reservation, {"actualTokens": actual_tokens, "status": "expired"} if record == "expired" else record)


_ledgers: WeakKeyDictionary = WeakKeyDictionary()
_ledgers_lock = RLock()


def make_model_quota_coordinator(coordinator: LeaseCoordinator) -> ModelQuotaCoordinator:
    """Retain the selected lease authority across Runtime/wrapper reconstruction."""
    with _ledgers_lock:
        if coordinator not in _ledgers:
            if isinstance(coordinator, RedisLeaseCoordinator):
                _ledgers[coordinator] = RedisModelQuotaCoordinator(coordinator.client, key_prefix=f"{coordinator.key_prefix}:model-quota")
            elif isinstance(coordinator, InMemoryLeaseCoordinator):
                _ledgers[coordinator] = InMemoryModelQuotaCoordinator()
            else:
                raise TypeError("model quota requires a supported lease coordination authority")
        return _ledgers[coordinator]
