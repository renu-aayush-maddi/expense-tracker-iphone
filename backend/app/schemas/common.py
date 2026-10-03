from typing import Annotated

from pydantic import BeforeValidator


def _blank_to_none(value):
    """Turn "" / "   " into None and trim whitespace from strings."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# Optional text field where an empty string from a form means "not set".
OptionalStr = Annotated[str | None, BeforeValidator(_blank_to_none)]
