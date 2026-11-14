"""严格合同、JSON往返及首版能力边界。"""

import pytest
from pydantic import ValidationError

from safe.contracts.inference import GenerationOptions, InferenceRequest
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.privacy import PrivacyProfile
from safe.infrastructure.codecs.fp32 import FP32Codec


def test_contract_json_roundtrip_preserves_shape():
    envelope = FP32Codec().encode([1.0, 2.0], (1, 1, 2))
    assert type(envelope).model_validate_json(envelope.model_dump_json()) == envelope


@pytest.mark.parametrize("updates", [{"max_new_tokens": 33}, {"max_new_tokens": True}, {"sampling": "random"}])
def test_generation_rejects_unapproved_options(updates):
    with pytest.raises(ValidationError):
        GenerationOptions(**updates)


def test_local_prompt_hidden_from_repr_and_no_dp_profile_is_exposed():
    assert "敏感内容" not in repr(InferenceRequest(prompt="敏感内容"))
    with pytest.raises(ValidationError):
        PrivacyProfile(profile_id="split-dp-experimental-v1")


def test_manifest_requires_immutable_revision_and_internal_cut():
    data = dict(model_id="test/model", revision="a" * 40, config_digest="b" * 64,
                tokenizer_digest="c" * 64, template_digest="d" * 64,
                prefix_digest="e" * 64, suffix_digest="f" * 64,
                total_layers=4, cut_layer=2, hidden_size=8, license_id="test-license")
    assert SplitModelManifest(**data).cut_layer == 2
    for update in ({"revision": "main"}, {"cut_layer": 0}, {"cut_layer": 4}, {"hidden_size": 0}):
        with pytest.raises(ValidationError):
            SplitModelManifest(**(data | update))
