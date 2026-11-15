"""固定greedy、词表和EOS边界；不依赖模型框架。"""

import math

import pytest

from safe.contracts.errors import SafeError
from safe.infrastructure.models import sampling


def test_greedy_uses_first_maximum_and_marks_only_configured_eos():
    sampler = sampling.GreedySampler(vocab_size=4, eos_token_ids=frozenset({3}))
    assert sampler.sample((0.0, 2.0, 2.0, -1.0)) == (1, False)
    assert sampler.sample((-4.0, -3.0, -2.0, -1.0)) == (3, True)


@pytest.mark.parametrize("logits", [(), (1.0,), (0.0, math.nan, 2.0, 3.0),
    (0.0, math.inf, 2.0, 3.0), (0.0, -math.inf, 2.0, 3.0),
    (0.0, True, 2.0, 3.0), (0.0, "1", 2.0, 3.0)])
def test_invalid_logits_are_refused_without_sampling(logits):
    sampler = sampling.GreedySampler(vocab_size=4)
    with pytest.raises(SafeError, match="MODEL_OUTPUT_INVALID"):
        sampler.sample(logits)


@pytest.mark.parametrize("vocab,eos", [(0, frozenset()), (True, frozenset()),
    (4, frozenset({4})), (4, frozenset({-1})), (4, frozenset({True}))])
def test_invalid_vocabulary_and_eos_configuration_is_refused(vocab, eos):
    with pytest.raises(ValueError):
        sampling.GreedySampler(vocab_size=vocab, eos_token_ids=eos)
