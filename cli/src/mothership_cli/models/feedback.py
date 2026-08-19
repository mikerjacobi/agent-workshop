"""Feedback models."""

from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self

from mothership_cli.client_models.aggregation import AggregationInput
from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.client_models.pagination import PaginationInput
from pydantic import BaseModel, ConfigDict, model_validator


class FeedbackType(StrEnum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"


class AgentFeedback(BaseModel):
    """Per-message user feedback (thumbs up/down with optional comment)."""

    model_config = ConfigDict(extra="ignore")

    message_id: str
    external_id: str
    feedback_type: FeedbackType | None = None
    comment: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FeedbackInput(BaseModel):
    """Input for creating or updating feedback on a message."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    feedback_type: FeedbackType | None = None
    comment: str | None = None

    @model_validator(mode="after")
    def _require_feedback_type_or_comment(self) -> Self:
        if self.feedback_type is None and self.comment is None:
            raise ValueError("at least one of feedback_type or comment is required")
        return self


class FeedbackSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class AgentFeedbackFilterFields(BaseModel, extra="forbid"):
    """All feedback filter fields. No pagination, no aggregation."""

    message_id: KeywordFilter[str] | None = None
    external_id: KeywordFilter[str] | None = None
    feedback_type: KeywordFilter[FeedbackType] | None = None


class SearchAgentFeedbackInput(AgentFeedbackFilterFields):
    """Unpaginated feedback search — returns all matching rows."""


class SearchAgentFeedbackPaginatedInput(AgentFeedbackFilterFields, PaginationInput[FeedbackSortBy]):
    sort_by: FeedbackSortBy = FeedbackSortBy.CREATED_AT


class AggregateAgentFeedbackInput(AgentFeedbackFilterFields, AggregationInput):
    _excluded_aggregatable_fields: ClassVar[set[str]] = set()


SearchAgentFeedbackOutput = ApiOutputModel[AgentFeedback]
