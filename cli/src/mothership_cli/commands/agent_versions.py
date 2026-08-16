"""``mothership agent-versions`` — agent version CRUD."""

from __future__ import annotations

import json

from mothership_cli.client import ApiError, MothershipClient, get_client
from mothership_cli.config import is_json_output
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.models.agent_catalog import SearchAgentCatalogInput, UpdateAgentInput
from mothership_cli.models.agent_version import (
    AgentVersion,
    CreateAgentVersionInput,
    SearchAgentVersionsInput,
    UpdateAgentVersionInput,
)
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand


def _require_agent(client: MothershipClient, agent_id: str) -> None:
    agents, _ = client.search_agents(SearchAgentCatalogInput(agent_id=KeywordFilter(eq=agent_id)))
    if not agents:
        raise SystemExit(f"Agent '{agent_id}' not found.")


def _print_versions(versions: list[AgentVersion], total: int) -> None:
    if not versions:
        print("No versions found.")
        return
    header = f"{'VERSION_ID':<40} {'AGENT_ID':<24} {'VERSION':<24} {'IMAGE':<40} {'ENABLED':<8} {'CREATED_AT'}"
    print(header)
    print("─" * len(header))
    for v in versions:
        created = str(v.created_at or "")[:19]
        enabled = "yes" if v.enabled else "no"
        print(
            f"{v.version_id:<40} "
            f"{v.agent_id:<24} "
            f"{v.version:<24} "
            f"{v.image:<40} "
            f"{enabled:<8} "
            f"{created}"
        )
    if total is not None:
        print(f"\n{total} total")


def _print_version(v: AgentVersion) -> None:
    if is_json_output():
        print(json.dumps(v.model_dump(mode="json"), indent=2, default=str))
        return
    print(f"  version_id: {v.version_id}")
    print(f"  agent_id: {v.agent_id}")
    print(f"  version: {v.version}")
    print(f"  image: {v.image}")
    print(f"  date_built: {v.date_built}")
    print(f"  enabled: {v.enabled}")
    print(f"  created_at: {v.created_at}")
    print(f"  updated_at: {v.updated_at}")


class AgentVersionsSearch(BaseModel):
    """List versions for an agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: CliPositionalArg[str] = Field(description="Agent whose versions to list")
    version: str | None = Field(default=None, description="Filter by version label")
    enabled: bool | None = Field(default=None, description="Filter by enabled status")

    def cli_cmd(self) -> None:
        client = get_client()
        _require_agent(client, self.agent_id)
        filters: dict = {"agent_id": KeywordFilter(eq=self.agent_id)}
        if self.version:
            filters["version"] = KeywordFilter(eq=self.version)
        if self.enabled is not None:
            filters["enabled"] = self.enabled
        query = SearchAgentVersionsInput(**filters)
        try:
            if is_json_output():
                data = client._search("/api/agent-versions/search", query)
                print(json.dumps(data, indent=2, default=str))
                return
            versions, total = client.search_agent_versions(query)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        _print_versions(versions, total)


class AgentVersionsCreate(BaseModel):
    """Create a new version for an agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: CliPositionalArg[str] = Field(description="Agent to add the version to")
    version: str = Field(description="Version label (tag, sha, free-form)")
    image: str = Field(description="Docker image (resolvable from orchestrator)")
    enabled: bool = Field(default=True, description="Whether this version can be promoted")
    set_current: bool = Field(default=False, description="Also set this version as the agent's current_version")

    def cli_cmd(self) -> None:
        client = get_client()
        _require_agent(client, self.agent_id)
        try:
            created = client.create_agent_version(CreateAgentVersionInput(
                agent_id=self.agent_id,
                version=self.version,
                image=self.image,
                enabled=self.enabled,
            ))
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(f"Created version '{created.version}' ({created.version_id})")
        _print_version(created)

        if self.set_current:
            try:
                client.update_agent(UpdateAgentInput(
                    agent_id=self.agent_id,
                    current_version=created.version_id,
                ))
            except ApiError as e:
                raise SystemExit(f"Version created but failed to set as current: {e}") from e
            print(f"\nSet as current_version for '{self.agent_id}'")


class AgentVersionsUpdate(BaseModel):
    """Update an existing agent version."""

    model_config = ConfigDict(extra="forbid")

    version_id: CliPositionalArg[str] = Field(description="Version to update")
    version: str | None = Field(default=None, description="New version label")
    image: str | None = Field(default=None, description="New Docker image")
    enabled: bool | None = Field(default=None, description="Enable or disable")

    def cli_cmd(self) -> None:
        client = get_client()
        patch = self.model_dump(exclude={"version_id"}, exclude_none=True)
        if not patch:
            raise SystemExit("Nothing to update. Pass at least one flag.")
        try:
            updated = client.update_agent_version(UpdateAgentVersionInput(
                version_id=self.version_id, **patch,
            ))
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(f"Updated version '{updated.version}' ({updated.version_id})")
        _print_version(updated)


class AgentVersionsDelete(BaseModel):
    """Delete an agent version."""

    model_config = ConfigDict(extra="forbid")

    version_id: CliPositionalArg[str] = Field(description="Version to delete")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            deleted = client.delete_agent_version(self.version_id)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(f"Deleted version '{deleted.version}' ({deleted.version_id})")


class AgentVersionsCmd(BaseModel):
    """Manage agent versions."""

    search: CliSubCommand[AgentVersionsSearch]
    create: CliSubCommand[AgentVersionsCreate]
    update: CliSubCommand[AgentVersionsUpdate]
    delete: CliSubCommand[AgentVersionsDelete]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
