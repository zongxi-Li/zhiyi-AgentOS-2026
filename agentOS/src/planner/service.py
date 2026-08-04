"""规划部件的公共 Facade。"""

from .acg_builder import build_acg
from .cognitive_router import route_cognition
from .intent_analyzer import analyze_intent
from .task_structurer import structure_tasks


class PlannerService:
    """将文本请求转为可检查的最小规划结果。"""

    def plan(self, request: str) -> dict[str, object]:
        intent = analyze_intent(request)
        tasks = structure_tasks(intent)
        return {"route": route_cognition(intent), "tasks": tasks, "acg": build_acg(tasks)}
