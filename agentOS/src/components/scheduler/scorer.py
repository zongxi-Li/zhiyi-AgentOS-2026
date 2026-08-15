"""调度候选评分 Facade。"""

from contracts.resource import ResourceSnapshot, SchedulingRequest

from .algorithms import lease_score


def score_candidate(request: SchedulingRequest, snapshot: ResourceSnapshot) -> float:
    """将合同快照投影为可比较分数。"""
    return lease_score(snapshot.available_slots, snapshot.utilization, request.priority)
