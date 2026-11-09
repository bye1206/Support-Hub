"""Domain exceptions (no HTTP knowledge at this layer)."""


class DomainError(Exception):
    """Base class for domain rule violations."""


class TransitionNotAllowed(DomainError):
    """A status/mode transition was requested that the FSM forbids."""

    def __init__(self, entity: str, current: str, target: str) -> None:
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(
            f"Forbidden transition of {entity}: {current} -> {target}"
        )


class StateConflict(DomainError):
    """Optimistic lock conflict: the entity changed concurrently."""


class SessionExpiredError(DomainError):
    """Operation requires an active session but it has expired."""
