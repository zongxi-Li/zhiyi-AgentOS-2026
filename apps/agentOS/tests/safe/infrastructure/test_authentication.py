"""签名固定向量、身份绑定与有界原子防重放验收。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace

import pytest

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.identity import AuthenticatedIdentity
from safe.infrastructure.security import authentication, signing
from safe.ports import credentials


NOW = 1700000000
NONCE = "0123456789abcdef0123456789abcdef"
BODY = b'{"owner_id":"untrusted"}'
PATH = "/safe/v1/sessions"


class Source:
    def __init__(self, credential):
        self.credential = credential
        self.lookups = []

    def get(self, credential_id):
        self.lookups.append(credential_id)
        return self.credential if self.credential and self.credential.credential_id == credential_id else None


def credential(**changes):
    values = dict(credential_id="cred:one", owner_id="owner.one", secret=bytes(range(32)), scopes=frozenset({"safe:infer"}))
    values.update(changes)
    return credentials.Credential(**values)


def signed(**changes):
    values = dict(credential=credential(), method="POST", path=PATH, timestamp=NOW, nonce=NONCE, body=BODY)
    values.update(changes)
    return signing.sign_request(**values)


def authenticator(*, source=None, clock=lambda: NOW, nonces=None):
    return authentication.HmacAuthenticator(
        credentials=source or Source(credential()),
        nonces=nonces or authentication.InMemoryNonceStore(clock=clock), clock=clock,
    )


def rejected(auth, *, headers=None, **changes):
    values = dict(method="POST", path=PATH, headers=signed() if headers is None else headers, body=BODY)
    values.update(changes)
    with pytest.raises(SafeError) as caught:
        auth.authenticate(**values)
    assert caught.value.code is ErrorCode.AUTHENTICATION_FAILED
    assert str(caught.value) == "AUTHENTICATION_FAILED"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_fixed_canonical_vector_and_hmac_known_answer():
    expected = (
        "SAFE-HMAC-SHA256-V1\ncred:one\nPOST\n/safe/v1/sessions\n1700000000\n"
        "0123456789abcdef0123456789abcdef\n"
        "62938d089aadca07dd7f19c3bf83025eb378c7da80f2fef23f563e6e62ef02ff"
    ).encode()
    assert signing.canonical_request(credential_id="cred:one", method="post", path=PATH, timestamp=NOW, nonce=NONCE, body=BODY) == expected
    assert signed() == {
        "X-Safe-Protocol": "safe-v1", "X-Safe-Credential": "cred:one",
        "X-Safe-Timestamp": "1700000000", "X-Safe-Nonce": NONCE,
        "X-Safe-Signature": "224f458f9eba8b6d8a5c4ee6e0c2c1db5210fdb98f2b458d724c8c7f838b40cd",
    }


def test_authenticated_identity_comes_from_credential_and_headers_are_case_insensitive():
    result = authenticator().authenticate(method="POST", path=PATH, headers={k.lower(): v for k, v in signed().items()}, body=BODY)
    assert result == AuthenticatedIdentity(owner_id="owner.one", credential_id="cred:one", scopes=("safe:infer",))


@pytest.mark.parametrize("method,path", [
    ("GET", "/safe/v1/capabilities"), ("POST", PATH),
    ("POST", "/safe/v1/sessions/session_1/steps"),
    ("GET", "/safe/v1/sessions/session-1/requests/req_1"),
    ("DELETE", "/safe/v1/sessions/session-1"),
])
def test_supported_routes(method, path):
    authenticator().authenticate(method=method, path=path, headers=signed(method=method, path=path), body=BODY)


@pytest.mark.parametrize("method,path", [
    ("GET", PATH), ("POST", PATH + "/"), ("POST", PATH + "?x=1"),
    ("POST", PATH + "#fragment"), ("POST", "/safe/v1//sessions"),
    ("POST", "/safe/v1/./sessions"), ("POST", "/safe/v1/x/../sessions"),
    ("POST", "/safe/v1/%73essions"), ("POST", "/safe/v1/sessions/a%2Fb/steps"),
    ("POST", "/safe/v1/sessions/a\\b/steps"), ("POST", "/safe/v1/sessions/../steps"),
    ("POST", "/safe/v1/sessions/a.b/steps"), ("POST", "/safe/v1/sessions/中文/steps"),
    ("POST", "/safe/v1/sessions/" + "a" * 129 + "/steps"), ("POST\n", PATH),
    ("poſt", PATH),
])
def test_ambiguous_or_unsupported_routes_fail_closed(method, path):
    rejected(authenticator(), method=method, path=path)
    with pytest.raises(ValueError):
        signed(method=method, path=path)


@pytest.mark.parametrize("field,value", [
    ("X-Safe-Protocol", "safe-v2"), ("X-Safe-Credential", "cred:two"),
    ("X-Safe-Timestamp", str(NOW + 1)), ("X-Safe-Nonce", "f" * 32),
    ("X-Safe-Signature", "0" * 64),
])
def test_every_signed_header_tamper_is_rejected(field, value):
    headers = signed()
    headers[field] = value
    source = Source(credential(credential_id=value)) if field == "X-Safe-Credential" else None
    rejected(authenticator(source=source), headers=headers)


@pytest.mark.parametrize("changes", [dict(body=BODY + b" "), dict(method="GET"), dict(path="/safe/v1/capabilities"), dict(path="/safe/v1/sessions/other/steps")])
def test_request_field_tamper_is_rejected(changes):
    rejected(authenticator(), **changes)


@pytest.mark.parametrize("field", ["X-Safe-Protocol", "X-Safe-Credential", "X-Safe-Timestamp", "X-Safe-Nonce", "X-Safe-Signature"])
def test_missing_headers_are_rejected(field):
    headers = signed()
    del headers[field]
    rejected(authenticator(), headers=headers)


@pytest.mark.parametrize("field,value", [
    ("X-Safe-Timestamp", "NaN"), ("X-Safe-Timestamp", "inf"), ("X-Safe-Timestamp", "1e9"),
    ("X-Safe-Timestamp", str(NOW) + ".0"), ("X-Safe-Timestamp", "0" + str(NOW)),
    ("X-Safe-Timestamp", "+" + str(NOW)), ("X-Safe-Timestamp", str(NOW) + "\n"),
    ("X-Safe-Timestamp", "9" * 5000), ("X-Safe-Timestamp", NOW),
    ("X-Safe-Nonce", NONCE.upper()), ("X-Safe-Nonce", "a" * 31), ("X-Safe-Nonce", "a" * 33),
    ("X-Safe-Nonce", "g" * 32), ("X-Safe-Signature", "A" * 64), ("X-Safe-Signature", "0" * 63),
    ("X-Safe-Credential", "cred\nsecret"), ("X-Safe-Credential", "a" * 129),
])
def test_malformed_headers_are_rejected(field, value):
    headers = signed()
    headers[field] = value
    rejected(authenticator(), headers=headers)


def test_duplicate_case_header_names_are_rejected():
    headers = signed()
    headers["x-safe-nonce"] = NONCE
    rejected(authenticator(), headers=headers)


@pytest.mark.parametrize("offset", [-60, 60])
def test_timestamp_window_includes_boundaries(offset):
    authenticator().authenticate(method="POST", path=PATH, headers=signed(timestamp=NOW + offset), body=BODY)


@pytest.mark.parametrize("offset", [-61, 61])
def test_timestamp_outside_window_does_not_consume_nonce(offset):
    auth = authenticator()
    rejected(auth, headers=signed(timestamp=NOW + offset))
    auth.authenticate(method="POST", path=PATH, headers=signed(), body=BODY)


def test_invalid_hmac_does_not_consume_nonce():
    auth = authenticator()
    rejected(auth, body=b"tampered")
    auth.authenticate(method="POST", path=PATH, headers=signed(), body=BODY)
    rejected(auth)


def test_future_timestamp_nonce_survives_its_full_validity_and_inclusive_boundary():
    now = [NOW]
    auth = authenticator(clock=lambda: now[0])
    headers = signed(timestamp=NOW + 60)
    auth.authenticate(method="POST", path=PATH, headers=headers, body=BODY)
    now[0] = NOW + 120
    rejected(auth, headers=headers)


def test_utc_rollback_cannot_replay_a_nonce_that_was_already_cleaned_up():
    now = [1000]
    auth = authenticator(clock=lambda: now[0])
    original = signed(timestamp=1000)
    auth.authenticate(method="POST", path=PATH, headers=original, body=BODY)
    now[0] = 1061
    auth.authenticate(method="POST", path=PATH, headers=signed(timestamp=1061, nonce="b" * 32), body=BODY)
    now[0] = 1030
    rejected(auth, headers=original)
    rejected(auth, headers=signed(timestamp=1030, nonce="c" * 32))
    now[0] = 1061
    auth.authenticate(method="POST", path=PATH, headers=signed(timestamp=1061, nonce="c" * 32), body=BODY)


def test_nonce_clock_rollback_preserves_live_capacity_until_recovery():
    now = [1000]
    store = authentication.InMemoryNonceStore(clock=lambda: now[0], max_entries=1)
    assert store.consume("cred:one", "a" * 32, 1060)
    now[0] = 1061
    assert store.consume("cred:one", "b" * 32, 1121)
    now[0] = 1030
    assert not store.consume("cred:one", "a" * 32, 1060)
    now[0] = 1061
    assert not store.consume("cred:one", "c" * 32, 1121)
    now[0] = 1121
    assert not store.consume("cred:one", "c" * 32, 1121)
    now[0] = 1121.01
    assert store.consume("cred:one", "c" * 32, 1122)


@pytest.mark.parametrize("invalid_expiry", [float("nan"), 999, 1300])
def test_invalid_expiry_does_not_advance_nonce_clock_high_watermark(invalid_expiry):
    now = [1000]
    store = authentication.InMemoryNonceStore(clock=lambda: now[0])
    assert store.consume("cred:one", "a" * 32, 1060)
    now[0] = 1100
    assert not store.consume("cred:one", "b" * 32, invalid_expiry)
    now[0] = 1030
    assert store.consume("cred:one", "c" * 32, 1090)


def test_concurrent_replay_has_exactly_one_success():
    auth = authenticator()
    def attempt(_):
        try:
            auth.authenticate(method="POST", path=PATH, headers=signed(), body=BODY)
            return True
        except SafeError:
            return False
    with ThreadPoolExecutor(max_workers=16) as workers:
        assert sum(workers.map(attempt, range(64))) == 1


def test_nonce_capacity_and_expiry_never_evict_live_entries():
    now = [NOW]
    store = authentication.InMemoryNonceStore(clock=lambda: now[0], max_entries=2, max_per_credential=1)
    assert store.consume("cred:one", "a" * 32, NOW + 1)
    assert not store.consume("cred:one", "b" * 32, NOW + 1)
    assert store.consume("cred:two", "b" * 32, NOW + 1)
    assert not store.consume("cred:three", "c" * 32, NOW + 1)
    now[0] = NOW + 1
    assert not store.consume("cred:one", "a" * 32, NOW + 1)
    now[0] = NOW + 1.01
    assert store.consume("cred:three", "c" * 32, NOW + 2)


@pytest.mark.parametrize("expires_at", [NOW - 1, NOW + 121, float("inf"), float("nan"), True, 10 ** 400])
def test_nonce_store_rejects_unsafe_expiry(expires_at):
    assert not authentication.InMemoryNonceStore(clock=lambda: NOW).consume("cred:one", NONCE, expires_at)


@pytest.mark.parametrize("changes", [dict(max_entries=0), dict(max_entries=True), dict(max_per_credential=-1), dict(max_per_credential=1.5)])
def test_nonce_store_rejects_invalid_capacity_configuration(changes):
    with pytest.raises(ValueError):
        authentication.InMemoryNonceStore(**changes)


@pytest.mark.parametrize("clock_value", [float("inf"), float("nan"), True, "1700000000", 10 ** 400])
def test_unusable_clock_fails_closed(clock_value):
    rejected(authenticator(clock=lambda: clock_value))
    assert not authentication.InMemoryNonceStore(clock=lambda: clock_value).consume("cred:one", NONCE, NOW + 60)


@pytest.mark.parametrize("changes", [dict(timestamp=NOW + .5), dict(timestamp=True), dict(timestamp=-1), dict(nonce="A" * 32), dict(body=bytearray(BODY))])
def test_signer_rejects_noncanonical_inputs(changes):
    with pytest.raises(ValueError):
        signed(**changes)


@pytest.mark.parametrize("replacement", [None, dict(revoked=True), dict(scopes=frozenset())])
def test_unknown_revoked_and_missing_scope_are_rejected(replacement):
    source = Source(None if replacement is None else credential(**replacement))
    rejected(authenticator(source=source))


def test_credential_revocation_is_looked_up_on_every_request():
    source = Source(credential())
    auth = authenticator(source=source)
    auth.authenticate(method="POST", path=PATH, headers=signed(), body=BODY)
    source.credential = replace(source.credential, revoked=True)
    rejected(auth, headers=signed(nonce="f" * 32))
    assert source.lookups == ["cred:one", "cred:one"]


def test_credential_source_failure_is_redacted():
    class BrokenSource:
        def get(self, credential_id):
            raise RuntimeError("secret payload")
    rejected(authenticator(source=BrokenSource()))


def test_credential_is_immutable_and_repr_does_not_reveal_secret():
    secret = b"VERY_SECRET_VALUE_01234567890123456789"
    scopes = {"safe:infer"}
    record = credential(secret=secret, scopes=scopes)
    scopes.clear()
    assert secret.decode() not in repr(record)
    assert record.scopes == frozenset({"safe:infer"})
    with pytest.raises(FrozenInstanceError):
        record.owner_id = "someone"


@pytest.mark.parametrize("changes", [dict(secret=b"short"), dict(secret=bytearray(32)), dict(credential_id="bad/name"), dict(owner_id="bad\nowner"), dict(owner_id="a" * 129), dict(scopes="safe:infer"), dict(scopes=None), dict(scopes={1}), dict(revoked=1)])
def test_invalid_credential_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        credential(**changes)
