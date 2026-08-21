"""Domain-level validation errors."""


class DeliveryContractError(ValueError):
    """Base class for malformed deterministic delivery facts."""


class InvalidScope(DeliveryContractError):
    """Raised when a structured Scope is unsafe or ambiguous."""


class InvalidReceipt(DeliveryContractError):
    """Raised when a typed handback receipt cannot be trusted."""


class DeliverySourceError(RuntimeError):
    """Raised when an external source cannot provide trustworthy facts."""


class CompareAndSwapConflict(DeliverySourceError):
    """Raised when a mutation target changed after its exact preflight."""


class PolicyViolation(DeliverySourceError):
    """Raised when exact delivery facts do not authorize a requested action."""
