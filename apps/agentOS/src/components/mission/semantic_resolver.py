"""Pure semantic projection and Run-basis capture; no persistence or authority."""

from contracts.mission_semantic import (
    EffectiveMissionSnapshot, MissionSemanticView, MissionIntentBasis,
    FrozenSemanticConstraint, intent_basis_fingerprint,
)


class MissionSemanticResolver:
    @staticmethod
    def resolve(snapshot: EffectiveMissionSnapshot) -> MissionSemanticView:
        snapshot = EffectiveMissionSnapshot.model_validate(snapshot.model_dump())
        if snapshot.status == "MISSION_NOT_FOUND":
            raise KeyError(snapshot.mission_id)
        if snapshot.status == "UNINITIALIZED":
            if snapshot.state is not None or snapshot.mission_revision != 0:
                raise ValueError("inconsistent uninitialized snapshot")
            return MissionSemanticView(missionId=snapshot.mission_id,
                semanticStatus="UNINITIALIZED", missionRevision=0, sourceStatus="NOT_APPLICABLE")
        state = snapshot.state
        if state is None or state.mission_id != snapshot.mission_id or state.mission_revision != snapshot.mission_revision:
            raise ValueError("inconsistent committed semantic snapshot")
        return MissionSemanticView(missionId=state.mission_id, semanticStatus="INITIALIZED",
            missionRevision=state.mission_revision, commitId=state.last_commit_id, objective=state.objective,
            constraints=tuple(FrozenSemanticConstraint.model_validate(c.model_dump()) for c in state.constraints),
            sourceReferences=tuple(state.source_refs), sourceStatus=snapshot.source_status)

    @staticmethod
    def freeze(view: MissionSemanticView, *, legacy_input: dict | None = None,
               legacy_title: str = "", allow_legacy: bool = False) -> MissionIntentBasis:
        view = MissionSemanticView.model_validate(view.model_dump())
        if view.semantic_status == "INITIALIZED":
            payload = dict(missionId=view.mission_id, sourceType="SEMANTIC",
                sourceRevision=view.mission_revision, commitId=view.commit_id, objective=view.objective,
                constraints=[c.model_dump(by_alias=True, mode="json") for c in view.constraints],
                sourceReferences=list(view.source_references), sourceStatus=view.source_status)
        else:
            if not allow_legacy:
                raise ValueError("Mission semantics are uninitialized; explicit compatibility is required")
            raw = legacy_input or {}
            objective = next((str(raw[k]).strip() for k in ("objective", "userIntent", "taskGoal", "intent")
                              if isinstance(raw.get(k), str) and raw[k].strip()), "")
            source_type = "LEGACY_INPUT" if objective else "LEGACY_TITLE"
            objective = objective or legacy_title.strip()
            # Compatibility constraints remain explicitly unconfirmed, never promoted.
            constraints = []
            for index, item in enumerate(raw.get("constraints") or []):
                text = item if isinstance(item, str) else item.get("value", item.get("text")) if isinstance(item, dict) else None
                if isinstance(text, str) and text.strip():
                    constraints.append(dict(constraintId=f"legacy:{index}", text=text, sourceRefs=[]))
            payload = dict(missionId=view.mission_id, sourceType=source_type, sourceRevision=0,
                commitId=None, objective=objective, constraints=constraints,
                sourceReferences=[], sourceStatus="NOT_APPLICABLE")
        payload.update(basisSchemaVersion=1, fingerprintVersion=1)
        payload["fingerprint"] = intent_basis_fingerprint(payload)
        return MissionIntentBasis.model_validate(payload)
