"""Agent version models. A version is an immutable (image, label) build
of an agent. ``agent_catalog.current_version`` points at the version
sandboxes should boot with; sandboxes track their own
``current_agent_version_id`` / ``desired_agent_version_id`` so a running
sandbox keeps its image even as the catalog moves on.

``version`` is any free-form string today (a sha256, a release tag, or
"mike special build"). ``enabled`` retires a version without deleting
it — disabled versions can't be promoted to ``current_version`` but are
kept for audit and for sandboxes still running them.
"""

from datetime import datetime
from enum import StrEnum

from mothership_cli.client_models.api_output_model import ApiOutputModel
from mothership_cli.client_models.common import DatetimeFilter, KeywordFilter
from mothership_cli.client_models.pagination import PaginationInput
from pydantic import BaseModel, ConfigDict, Field


class AgentVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    agent_id: str
    version: str
    image: str
    date_built: datetime | None = None
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CreateAgentVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    # Free-form label: sha256, release tag, or a human note. No format is
    # enforced yet — semver may come later.
    version: str = Field(min_length=1)
    image: str = Field(min_length=1)
    date_built: datetime | None = None
    enabled: bool = True


class UpdateAgentVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Path parameter; excluded from the patch payload serialized to the DB.
    version_id: str

    version: str | None = Field(default=None, min_length=1)
    image: str | None = Field(default=None, min_length=1)
    date_built: datetime | None = None
    enabled: bool | None = None


class AgentVersionSortBy(StrEnum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    DATE_BUILT = "date_built"
    VERSION = "version"


class AgentVersionFilterFields(BaseModel, extra="forbid"):
    version_id: KeywordFilter[str] | None = None
    agent_id: KeywordFilter[str] | None = None
    version: KeywordFilter[str] | None = None
    image: KeywordFilter[str] | None = None
    enabled: bool | None = None
    created_at: DatetimeFilter | None = None
    updated_at: DatetimeFilter | None = None


class SearchAgentVersionsInput(AgentVersionFilterFields, PaginationInput[AgentVersionSortBy]):
    sort_by: AgentVersionSortBy = AgentVersionSortBy.CREATED_AT


SearchAgentVersionsOutput = ApiOutputModel[AgentVersion]
AgentVersionOutput = ApiOutputModel[AgentVersion]
