"""Trusted initial-planning policy; no execution or review state authority.

V1 cannot classify free-text risk reliably. Explicit human_in_loop therefore
requires review of EVERY executable step, including artifact generation. The
accepted semantic constraints and frozen compiler inputs carry the same policy.
"""
import hashlib
from pathlib import Path
from dataclasses import replace


CONSTRAINT_TYPE = 'user_human_review'


def review_policy(mode):
    if mode == 'auto':
        return None
    if mode != 'human_in_loop':
        raise ValueError('unsupported reviewMode')
    return {'policyVersion': 'human-review-all-steps-v1', 'mode': mode,
            'scope': 'all-executable-steps', 'source': 'run.reviewMode',
            'implementationSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def bind_review_policy(plan, mode):
    policy = review_policy(mode)
    # Reserved constraints are server-owned, never interpreted from Agent text.
    nodes = tuple(node.model_copy(deep=True, update={'constraints': [
        *[c for c in node.constraints if c.get('type') != CONSTRAINT_TYPE],
        *([{'type': CONSTRAINT_TYPE, **policy}] if policy else []),
    ]}) for node in plan.nodes)
    return plan.model_copy(deep=True, update={'nodes': nodes})


def validate_review_policy(plan, mode):
    policy = review_policy(mode)
    expected = [{'type': CONSTRAINT_TYPE, **policy}] if policy else []
    if any([c for c in n.constraints if c.get('type') == CONSTRAINT_TYPE] != expected for n in plan.nodes):
        raise ValueError('candidate conflicts with trusted user review policy')


def review_lowering_input(lowering, policy):
    """Decide typed review flags BEFORE the existing lowerer builds the graph.

    L1 keeps the original business catalog. This server policy must not ask the
    model to invent verification loops or redefine risk classifications.
    """
    if policy is None:
        return lowering  # Preserve existing descriptor/template review gates.
    if policy != review_policy('human_in_loop'):
        raise ValueError('unsupported or drifted frozen human review policy')
    validate_review_policy(lowering.task_plan, 'human_in_loop')
    return replace(lowering, steps=tuple(replace(step, review_required=True,
        metadata={**step.metadata, 'reviewPolicy': policy}) for step in lowering.steps),
        metadata={**lowering.metadata, 'reviewPolicy': policy})
