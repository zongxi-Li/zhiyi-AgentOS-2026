"""新领域仓储公开的稳定错误类型。"""


class EntityNotFoundError(LookupError):
    pass


class IdentityConflictError(ValueError):
    pass


__all__ = ["EntityNotFoundError", "IdentityConflictError"]
