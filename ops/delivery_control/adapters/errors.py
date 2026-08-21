from __future__ import annotations

from delivery_control.ports.process import CommandResult


class AdapterError(RuntimeError):
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
