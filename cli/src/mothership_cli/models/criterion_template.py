"""Criterion template models. The one piece of a task spec normalized into a
real table: rubric text edited independently in the UI and referenced by many
tasks with per-task weights, so scores stay comparable across tasks."""

from datetime import datetime
from enum import StrEnum

from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.client_models.pagination import PaginationInput
from mothership_cli.models.eval_spec import CriterionType
from pydantic import BaseModel, ConfigDict, Field


class CriterionTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    template_id: str
    org_id: str | None = None
    name: str
    rubric: str
    criterion_type: CriterionType = CriterionType.LIKERT
    points: int = 5
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateCriterionTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Platform-provided starter template: org_id NULL, readable by every org,
    # writable by platform admins only.
    is_global: bool = False
    name: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    criterion_type: CriterionType = CriterionType.LIKERT
    points: int = Field(default=5, ge=2, le=10)


class UpdateCriterionTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    rubric: str | None = Field(default=None, min_length=1)
    criterion_type: CriterionType | None = None
    points: int | None = Field(default=None, ge=2, le=10)


class CriterionTemplateSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class CriterionTemplateFilterFields(BaseModel, extra="forbid"):
    template_id: KeywordFilter[str] | None = None
    name: KeywordFilter[str] | None = None


class SearchCriterionTemplateInput(CriterionTemplateFilterFields, PaginationInput[CriterionTemplateSortBy]):
    sort_by: CriterionTemplateSortBy = CriterionTemplateSortBy.CREATED_AT


CriterionTemplateOutput = ApiOutputModel[CriterionTemplate]
SearchCriterionTemplateOutput = ApiOutputModel[CriterionTemplate]
