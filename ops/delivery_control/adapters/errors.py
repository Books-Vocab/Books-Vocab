from __future__ import annotations

from ..domain.errors import DeliverySourceError
from ..ports.process import CommandResult


class AdapterError(DeliverySourceError):
    """Base class for infrastructure failures kept outside the domain model."""


class AdapterCommandError(AdapterError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        super().__init__(
            f"command failed with exit {result.exit_code}: {' '.join(result.argv)}: {detail}"
        )


class AdapterPayloadError(AdapterError):
    """Raised when an external command returns malformed structured data."""
