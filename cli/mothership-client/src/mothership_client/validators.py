"""Reusable Pydantic validators for fields shared across models."""


def strip_or_reject_blank(v: str | None) -> str | None:
    """Strip surrounding whitespace; reject the result if empty.
    ``min_length=1`` on its own counts characters, so ``"   "``
    sneaks past — and then resolves to a blank value at runtime.
    """
    if v is None:
        return None
    stripped = v.strip()
    if not stripped:
        raise ValueError("must be non-empty (whitespace only)")
    return stripped
