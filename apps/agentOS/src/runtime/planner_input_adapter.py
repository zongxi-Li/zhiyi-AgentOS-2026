"""Translate a frozen Mission basis into the existing Planner input contract."""

from copy import deepcopy
from contracts.mission_semantic import MissionIntentBasis


_SEMANTIC_KEYS = frozenset({"objective", "userIntent", "taskGoal", "intent", "title", "goal", "constraints"})


def material_input(raw: dict) -> dict:
    """Preserve material/config data, without granting old goal aliases authority."""
    return {key: deepcopy(value) for key, value in raw.items() if key not in _SEMANTIC_KEYS}


def planner_input(basis: MissionIntentBasis, raw: dict) -> dict:
    basis = MissionIntentBasis.model_validate(basis.model_dump())
    return {
        **material_input(raw),
        "objective": basis.objective, "userIntent": basis.objective,
        "taskGoal": basis.objective, "intent": basis.objective,
        "constraints": [dict(type="mission_constraint", value=c.text,
                             constraintId=c.constraint_id, sourceRefs=list(c.source_refs)) for c in basis.constraints],
    }
