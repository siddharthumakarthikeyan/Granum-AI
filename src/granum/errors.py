"""Exception hierarchy for Granum."""

from __future__ import annotations


class GranumError(Exception):
    """Base class for every error Granum raises."""


class AliasConflictError(GranumError):
    """An alias token was re-pointed at a different path without ``force=True``."""


class SchemaError(GranumError):
    """A column schema is invalid, or data does not match its declared schema."""


class ImmutableError(GranumError):
    """An attempt was made to mutate an immutable object."""

    def __init__(self, obj_type: str = "object") -> None:
        super().__init__(
            f"{obj_type} is immutable. Operations return a new revision instead of "
            f"modifying in place -- assign the result: table = table.add_column(...)"
        )


class ObjectNotFoundError(GranumError):
    """No Granum object exists at the given URL."""


class TableError(GranumError):
    """An invalid Table operation."""


class ConfigError(GranumError):
    """Configuration could not be resolved or is invalid."""
