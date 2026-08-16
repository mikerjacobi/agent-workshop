"""``mothership agents`` — agent catalog CRUD."""

from __future__ import annotations

import json

from mothership_cli.client import ApiError, get_client
from mothership_cli.commands.agent_versions import AgentVersionsCmd
from mothership_cli.config import is_json_output
from mothership_cli.models.agent_catalog import (
    AgentCatalogEntry,
    AgentParameter,
    CreateAgentInput,
    SearchAgentCatalogInput,
    UpdateAgentInput,
)
from mothership_cli.models.harness import TransportMode
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand


def _print_agents(agents: list[AgentCatalogEntry], total: int) -> None:
    if not agents:
        print("No agents found.")
        return
    header = f"{'AGENT_ID':<24} {'NAME':<24} {'HARNESS':<10} {'TRANSPORT':<10} {'VERSION':<24} {'MODEL':<24} {'ACTIVE'}"
    print(header)
    print("─" * len(header))
    for a in agents:
        model = a.default_model or "—"
        active = "yes" if a.is_active else "no"
        version = a.current_version_label or a.current_version or "—"
        transport = a.transport or "—"
        print(f"{a.agent_id:<24} {a.name:<24} {a.harness:<10} {transport:<10} {version:<24} {model:<24} {active}")
    if total is not None:
        print(f"\n{total} total")


def _print_agent(agent: AgentCatalogEntry) -> None:
    if is_json_output():
        print(json.dumps(agent.model_dump(mode="json"), indent=2, default=str))
        return
    print(f"  agent_id: {agent.agent_id}")
    print(f"  name: {agent.name}")
    print(f"  description: {agent.description}")
    print(f"  harness: {agent.harness}")
    print(f"  transport: {agent.transport}")
    print(f"  current_version: {agent.current_version}")
    print(f"  current_version_label: {agent.current_version_label}")
    print(f"  default_model: {agent.default_model}")
    print(f"  thread_deeplink_template: {agent.thread_deeplink_template}")
    print(f"  is_active: {agent.is_active}")
    if agent.parameters:
        print("  parameters:")
        for p in agent.parameters:
            default_str = f" (default: {p.default})" if p.default is not None else " (required)"
            secret_str = " [secret]" if p.secret else ""
            print(f"    {p.key}: {p.label}{default_str}{secret_str}")
    else:
        print("  parameters: []")
    print(f"  created_at: {agent.created_at}")
    print(f"  updated_at: {agent.updated_at}")


class AgentsSearch(SearchAgentCatalogInput):
    """Search the agent catalog."""

    model_config = ConfigDict(extra="forbid")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            if is_json_output():
                data = client._search(client._scoped("agents", "/search"), self)
                print(json.dumps(data, indent=2, default=str))
                return
            agents, total = client.search_agents(self)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        _print_agents(agents, total)


class AgentsCreate(CreateAgentInput):
    """Register a new agent in the catalog."""

    model_config = ConfigDict(extra="forbid")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            agent = client.create_agent(self)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(f"Created agent '{agent.agent_id}'")
        _print_agent(agent)


class AgentsUpdate(BaseModel):
    """Update an existing agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: CliPositionalArg[str] = Field(description="Agent to update")
    name: str | None = Field(default=None, description="Display name")
    description: str | None = Field(default=None, description="Agent description")
    transport: TransportMode | None = Field(default=None, description="Transport mode (RELAY or BUS)")
    current_version: str | None = Field(default=None, description="version_id to set as the agent's current version")
    default_model: str | None = Field(default=None, description="Default LiteLLM model")
    is_active: bool | None = Field(default=None, description="Enable or disable the agent")
    thread_deeplink_template: str | None = Field(default=None, description="URL template with $THREAD_ID placeholder for deep links")
    parameters: str | None = Field(
        default=None,
        description='Parameters JSON array, e.g. \'[{"key":"FOO","label":"Foo","default":"","secret":true}]\'',
    )

    def cli_cmd(self) -> None:
        client = get_client()
        patch: dict = self.model_dump(exclude={"agent_id", "parameters"}, exclude_none=True)

        if self.parameters is not None:
            raw = json.loads(self.parameters)
            patch["parameters"] = [AgentParameter(**p) for p in raw]

        if not patch:
            raise SystemExit("Nothing to update. Pass at least one flag.")
        update = UpdateAgentInput(agent_id=self.agent_id, **patch)
        try:
            agent = client.update_agent(update)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(f"Updated agent '{agent.agent_id}'")
        _print_agent(agent)


class AgentsDelete(BaseModel):
    """Delete an agent from the catalog."""

    model_config = ConfigDict(extra="forbid")

    agent_id: CliPositionalArg[str] = Field(description="Agent to delete")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            agent = client.delete_agent(self.agent_id)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        print(f"Deleted agent '{agent.agent_id}'")


class AgentsCmd(BaseModel):
    """Manage the agent catalog."""

    search: CliSubCommand[AgentsSearch]
    create: CliSubCommand[AgentsCreate]
    update: CliSubCommand[AgentsUpdate]
    delete: CliSubCommand[AgentsDelete]
    versions: CliSubCommand[AgentVersionsCmd]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
