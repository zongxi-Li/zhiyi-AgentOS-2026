from pathlib import Path

from packs.industrial.capabilities import INDUSTRIAL_CAPABILITY_IDS, industrial_capabilities
from support.packs.registry import load_pack_manifest


def test_industrial_manifest_matches_model_backed_capability_contracts() -> None:
    manifest = load_pack_manifest(
        Path(__file__).resolve().parents[1] / "packs" / "industrial" / "manifest.yaml"
    )
    descriptors = industrial_capabilities()

    assert manifest.pack_id == "industrial"
    assert set(manifest.capabilities) == set(INDUSTRIAL_CAPABILITY_IDS)
    assert len(manifest.agents) == 7
    assert all(item.source == "native" for item in descriptors)
    assert all(item.output_contract.get("required") for item in descriptors)
    assert {item.capability_id for item in descriptors} == set(INDUSTRIAL_CAPABILITY_IDS)
