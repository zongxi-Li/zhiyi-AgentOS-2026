"""Deterministic registry for declarative recovery recipes."""

from __future__ import annotations

from contracts.recovery import FailureEvent, RecoveryRecipe


class RecoveryRecipeRegistry:
    def __init__(self, recipes: list[RecoveryRecipe] | None = None) -> None:
        self._recipes: dict[tuple[str, str], RecoveryRecipe] = {}
        for recipe in recipes or []:
            self.register(recipe)

    def register(self, recipe: RecoveryRecipe) -> None:
        key = (recipe.recipe_id, recipe.version)
        if key in self._recipes:
            raise ValueError(f"recovery recipe already registered: {recipe.recipe_id}@{recipe.version}")
        self._recipes[key] = recipe.model_copy(deep=True)

    def get(self, recipe_id: str, version: str | None = None) -> RecoveryRecipe:
        matches = [
            item for (item_id, item_version), item in self._recipes.items()
            if item_id == recipe_id and (version is None or item_version == version)
        ]
        if not matches:
            raise KeyError(f"recovery recipe not found: {recipe_id}@{version or 'latest'}")
        return sorted(matches, key=lambda item: item.version)[-1].model_copy(deep=True)

    def match(
        self,
        failure: FailureEvent,
        *,
        application_counts: dict[str, int] | None = None,
    ) -> RecoveryRecipe | None:
        counts = application_counts or {}
        matches = [
            item
            for item in self._recipes.values()
            if item.matches(failure)
            and int(counts.get(f"{item.recipe_id}@{item.version}", 0)) < item.max_applications_per_run
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda item: (item.recipe_id, item.version))[0].model_copy(deep=True)


__all__ = ["RecoveryRecipeRegistry"]
