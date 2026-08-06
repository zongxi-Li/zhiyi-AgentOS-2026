"""需求与资源能力的确定性绑定规则。"""

from contracts.resource import ResourceProfile, SchedulingRequest


def can_bind(request: SchedulingRequest, profile: ResourceProfile) -> bool:
    """仅启用且包含全部所需能力的资源才可参与候选。"""
    return profile.enabled and set(request.required_capabilities).issubset(profile.capabilities)
