"""未配置模型和隐私发布器时，必须拒绝且不回退到普通聊天。"""

import pytest

from components.safe.application.inference import SplitInferenceService
from components.safe.application.privacy import PrivacyReleaseService
from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.inference import InferenceRequest


def test_model_stub_refuses_execution():
    with pytest.raises(SafeError) as error:
        SplitInferenceService().infer(InferenceRequest(prompt="只留本机"))
    assert error.value.code == ErrorCode.MODEL_PARTITION_UNAVAILABLE


def test_privacy_stub_never_fabricates_release():
    with pytest.raises(SafeError) as error:
        PrivacyReleaseService().release()
    assert error.value.code == ErrorCode.PRIVACY_UNAVAILABLE
