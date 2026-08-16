"""Aggregation query envelope — groups records by one or more fields and
computes a metric. Search endpoints that expose aggregations subclass
``AggregationInput`` so field validation uses the service's own filter
schema."""

from __future__ import annotations

import types
from enum import StrEnum
from typing import ClassVar, Self, Union, get_args, get_origin

from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter, NumericFilter
from pydantic import BaseModel, Field, PositiveFloat, PositiveInt, model_validator


class MetricType(StrEnum):
    COUNT = "count"
    AVG = "avg"
    SUM = "sum"
    MIN = "min"
    MAX = "max"


class MetricInput(BaseModel, extra="forbid"):
    type: MetricType
    field: str | None = None

    @model_validator(mode='after')
    def validate_field(self) -> Self:
        if self.type != MetricType.COUNT and not self.field:
            raise ValueError(f"'field' is required for metric type '{self.type}'")
        if self.type == MetricType.COUNT and self.field:
            raise ValueError("'field' should not be provided for metric type 'count'")
        return self


class CalendarInterval(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class GroupByInput(BaseModel, extra="forbid"):
    field: str
    interval: CalendarInterval | PositiveInt | PositiveFloat | None = None
    num_buckets: PositiveInt | None = Field(default=None, le=1000)


def _unwrap_optional(annotation: type) -> type:
    """Strip Optional / `X | None` to get the inner type."""
    origin = get_origin(annotation)
    if origin is types.UnionType or origin is Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return args[0] if args else annotation
    return annotation


def get_aggregatable_fields(model: type[BaseModel], prefix: str = "") -> dict[str, type]:
    """Walk a Pydantic model and return {dotted_field_path: filter_class} for
    every field whose type is KeywordFilter, DatetimeFilter, or NumericFilter.
    Nested BaseModels are recursed into. Subclasses can augment the result via
    ``_extra_aggregatable_fields`` or prune it via ``_excluded_aggregatable_fields``.
    """
    result: dict[str, type] = {}
    for name, field_info in model.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        raw_annotation = field_info.annotation
        if raw_annotation is None:
            continue
        annotation = _unwrap_optional(raw_annotation)
        base = get_origin(annotation) or annotation

        if isinstance(base, type) and issubclass(base, KeywordFilter | NumericFilter | DatetimeFilter):
            result[path] = base
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            result.update(get_aggregatable_fields(annotation, prefix=path))

    extras = getattr(model, '_extra_aggregatable_fields', None)
    if extras and not prefix:
        result.update(extras)

    excluded = getattr(model, '_excluded_aggregatable_fields', None)
    if excluded and not prefix:
        for field_name in excluded:
            result.pop(field_name, None)

    return result


class AggregationInput(BaseModel, extra="forbid"):
    metric: MetricInput
    group_by: list[GroupByInput] = Field(default_factory=list, max_length=2)

    # Subclasses can declare additional aggregatable fields beyond what
    # get_aggregatable_fields discovers from the model. Avoids dummy model
    # fields that would falsely imply filtering support.
    _extra_aggregatable_fields: ClassVar[dict[str, type]] = {}
    # Subclasses can exclude discovered fields that shouldn't be
    # aggregatable (e.g. high-cardinality IDs).
    _excluded_aggregatable_fields: ClassVar[set[str]] = set()

    @model_validator(mode="after")
    def validate_group_by(self) -> Self:
        agg_fields = get_aggregatable_fields(type(self))
        for gb in self.group_by:
            if gb.field not in agg_fields:
                raise ValueError(f"Cannot group by '{gb.field}'")
            ft = agg_fields[gb.field]
            if issubclass(ft, KeywordFilter):
                if gb.interval is not None:
                    raise ValueError(f"Keyword field '{gb.field}' does not support interval")
                if gb.num_buckets is None:
                    gb.num_buckets = 100
            else:
                if gb.num_buckets is not None:
                    raise ValueError(
                        f"'num_buckets' is only supported on keyword fields, "
                        f"not '{gb.field}'"
                    )
            if issubclass(ft, DatetimeFilter) and not isinstance(gb.interval, CalendarInterval):
                raise ValueError(
                    f"Datetime field '{gb.field}' requires a CalendarInterval "
                    f"(day, week, month, quarter, year)"
                )
            if issubclass(ft, NumericFilter) and not isinstance(gb.interval, int | float):
                raise ValueError(f"Numeric field '{gb.field}' requires a numeric interval")
        if self.metric.field:
            if self.metric.field not in agg_fields:
                raise ValueError(f"Cannot compute metric on '{self.metric.field}'")
            ft = agg_fields[self.metric.field]
            if self.metric.type in (MetricType.AVG, MetricType.SUM) and not issubclass(ft, NumericFilter):
                raise ValueError(
                    f"Metric type '{self.metric.type}' requires a numeric field, "
                    f"but '{self.metric.field}' is not numeric"
                )
            if (self.metric.type in (MetricType.MIN, MetricType.MAX) and
                    not issubclass(ft, (NumericFilter, DatetimeFilter))):
                raise ValueError(
                    f"Metric type '{self.metric.type}' requires a numeric or datetime field, "
                    f"but '{self.metric.field}' is not numeric or datetime"
                )

        return self


class AggregationBucket(BaseModel):
    # ``None`` keys arise when grouping by a nullable column (e.g. a
    # thread's sandbox_id before it binds) — that's a real bucket, not an
    # error. Callers building a value list filter nulls out themselves.
    key: dict[str, str | int | float | None]
    value: int | float | None


AggregationResponse = ApiOutputModel[AggregationBucket]
