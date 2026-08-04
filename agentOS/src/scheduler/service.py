"""调度部件的公共 Facade。"""

from contracts.resource import ResourceProfile, ResourceSnapshot, SchedulingRequest

from .binder import can_bind
from .scorer import score_candidate


class SchedulerService:
    """选择一个满足能力要求的最佳资源，且不产生外部副作用。"""

    def choose(self, request: SchedulingRequest, profiles: list[ResourceProfile], snapshots: list[ResourceSnapshot]) -> str | None:
        """从画像和同标识快照中选出最高分资源标识。

        输入列表只读，返回资源标识或无候选时的 ``None``；复杂度为画像和快照数量
        O(p+s)，本 Facade 不创建租约、不更新快照，也不承担跨线程资源预留。
        """
        by_id = {snapshot.resource_id: snapshot for snapshot in snapshots}
        candidates = [profile for profile in profiles if profile.resource_id in by_id and can_bind(request, profile)]
        chosen = max(candidates, key=lambda item: score_candidate(request, by_id[item.resource_id]), default=None)
        return chosen.resource_id if chosen else None
