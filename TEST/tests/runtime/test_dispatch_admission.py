"""Keep the real Permit-only bypass counterexample in the native freeze gate."""
from pathlib import Path


def test_permit_only_cannot_claim_dispatch_enabled_native_runtime(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(root / "apps/agent"))
    monkeypatch.syspath_prepend(str(root / "apps/agent/tests"))
    from test_agentos_c2_dispatch_admission import test_native_execution_requires_dispatch_even_with_issued_permit
    test_native_execution_requires_dispatch_even_with_issued_permit(tmp_path)
