"""Filter primitives used by search endpoints — one class per filter shape
(keyword, datetime, numeric) that pydantic composes into concrete
``Search*Input`` models."""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, model_validator


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class KeywordFilter[T](BaseModel, extra='forbid'):
    """API query model for filtering keyword fields."""
    eq: T | None = None
    neq: T | None = None
    inc: list[T] | None = None
    ninc: list[T] | None = None

    @model_validator(mode='after')
    def validate_fields(self) -> Self:
        if self.eq and self.neq:
            raise ValueError("Cannot specify both 'eq' and 'neq'")
        return self

    def matches(self, value: T) -> bool:
        """In-memory counterpart to apply_keyword_filter (which builds SQL
        conditions). Needed when intersecting a caller-provided filter with
        a Python list of values that can't be expressed as a single SQL clause,
        e.g. narrowing page-scoped thread_ids by a caller's thread_id filter."""
        if self.eq is not None and value != self.eq:
            return False
        if self.neq is not None and value == self.neq:
            return False
        if self.inc is not None and value not in self.inc:
            return False
        if self.ninc is not None and value in self.ninc:
            return False
        return True


class StringFilter(KeywordFilter[str]):
    """API query model for filtering text fields — a KeywordFilter over ``str``
    that adds ``like``/``nlike`` substring matching.

    Subclassing (rather than restating eq/neq/inc/ninc) is load-bearing:
    ``get_aggregatable_fields`` discovers group-by-able fields by testing
    ``issubclass(..., KeywordFilter | NumericFilter | DatetimeFilter)``, so a
    standalone StringFilter would silently make its field non-aggregatable and
    break the filter typeaheads that read from /aggregate."""
    like: str | None = None
    nlike: str | None = None


class DatetimeFilter(BaseModel, extra='forbid'):
    """API query model for filtering datetime fields."""
    gte: datetime | None = None
    gt: datetime | None = None
    lte: datetime | None = None
    lt: datetime | None = None
    exists: bool | None = None

    @model_validator(mode='after')
    def validate_fields(self) -> Self:
        if self.gte and self.gt:
            raise ValueError("Cannot specify both 'gte' and 'gt'")
        if self.lte and self.lt:
            raise ValueError("Cannot specify both 'lte' and 'lt'")
        if self.exists is True and (self.gte or self.gt or self.lte or self.lt):
            # Asking for a field to exist AND filtering on a range is
            # redundant — the range already implies existence.
            raise ValueError("Cannot specify both 'exists = True' and a range filter")
        return self


class NumericFilter[N: (int, float)](BaseModel, extra='forbid'):
    """API query model for filtering numeric fields."""
    gte: N | None = None
    gt: N | None = None
    lte: N | None = None
    lt: N | None = None
    eq: N | None = None
    neq: N | None = None

    @model_validator(mode='after')
    def validate_fields(self) -> Self:
        has_equality = any([self.eq, self.neq])
        has_range = any([self.gte, self.gt, self.lte, self.lt])
        if has_equality and has_range:
            raise ValueError("Cannot specify both equality and range filters")
        if self.gte is not None and self.gt is not None:
            raise ValueError("Cannot specify both 'gte' and 'gt'")
        if self.lte is not None and self.lt is not None:
            raise ValueError("Cannot specify both 'lte' and 'lt'")
        if self.eq is not None and self.neq is not None:
            raise ValueError("Cannot specify both 'eq' and 'neq'")
        return self


IntFilter = NumericFilter[int]
FloatFilter = NumericFilter[float]
