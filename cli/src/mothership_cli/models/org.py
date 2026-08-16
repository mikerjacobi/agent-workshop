"""Org models. An org is the tenancy boundary every sandbox/thread/agent belongs
to. Every user is a member of the shared ``default`` org; named orgs are created
explicitly."""

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from mothership_cli.client_models.aggregation import AggregationInput
from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter, StringFilter
from mothership_cli.client_models.pagination import PaginationInput
from pydantic import BaseModel, ConfigDict, Field

# The well-known shared org every user is enrolled into (created by migration
# 0029). Referenced by this stable slug.
DEFAULT_ORG_SLUG = "default"

# Its id is derived from the slug rather than generated, so the migration seed,
# ``find_or_create_default``, and any client that needs to address the default
# org all arrive at the same value without a lookup. Lives here, beside the
# slug, so callers that must not import the DB layer (the CLI) can still use it.
DEFAULT_ORG_ID = f"org_{hashlib.md5(DEFAULT_ORG_SLUG.encode(), usedforsecurity=False).hexdigest()[:12]}"


class Org(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: str
    name: str
    slug: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrgSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class OrgFilterFields(BaseModel, extra="forbid"):
    org_id: KeywordFilter[str] | None = None
    name: StringFilter | None = None
    slug: KeywordFilter[str] | None = None
    created_at: DatetimeFilter | None = None
    updated_at: DatetimeFilter | None = None


class SearchOrgsInput(OrgFilterFields, PaginationInput[OrgSortBy]):
    sort_by: OrgSortBy = OrgSortBy.CREATED_AT


class AggregateOrgsInput(OrgFilterFields, AggregationInput):
    _excluded_aggregatable_fields: ClassVar[set[str]] = set()


class CreateOrgInput(BaseModel):
    """POST body for creating a named org. ``slug`` defaults to a slugified
    ``name`` when omitted."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Human-readable org name.")
    slug: str | None = Field(default=None, description="URL-safe identifier. Defaults to a slugified name.")


class UpdateOrgInput(BaseModel):
    """PATCH body for an org; ``org_id`` is taken from the URL. ``slug`` is the
    stable URL key and is intentionally immutable."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Human-readable org name.")


SearchOrgsOutput = ApiOutputModel[Org]
OrgOutput = ApiOutputModel[Org]
