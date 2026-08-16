"""``mothership sandboxes`` — sandbox lifecycle."""

import json

from mothership_cli.client import ApiError, get_client
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.config import is_json_output, resolve_external_id
from mothership_cli.models.sandbox import CreateSandboxInput, Sandbox, SandboxState, SearchSandboxesInput
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand


def _print_sandboxes(sandboxes: list[Sandbox], total: int) -> None:
    if not sandboxes:
        print("No sandboxes found.")
        return
    header = f"{'SANDBOX_ID':<12} {'EXTERNAL_ID':<16} {'AGENT_ID':<24} {'VERSION':<20} {'MODEL':<28} {'STATE':<10} {'CREATED_AT'}"
    print(header)
    print("─" * len(header))
    for s in sandboxes:
        created = str(s.created_at or "")[:19]
        version = s.current_agent_version or s.current_agent_version_id or "—"
        print(
            f"{s.sandbox_id:<12} "
            f"{s.external_id:<16} "
            f"{(s.agent_id or '—'):<24} "
            f"{version:<20} "
            f"{s.model:<28} "
            f"{s.state:<10} "
            f"{created}"
        )
    if total is not None:
        print(f"\n{total} total")


class SandboxesSearch(SearchSandboxesInput):
    """Search sandboxes."""

    model_config = ConfigDict(extra="forbid")

    def cli_cmd(self) -> None:
        client = get_client()
        try:
            if is_json_output():
                data = client._search(client._scoped("sandboxes", "/search"), self)
                print(json.dumps(data, indent=2, default=str))
                return
            sandboxes, total = client.search_sandboxes(self)
        except ApiError as e:
            raise SystemExit(str(e)) from e
        _print_sandboxes(sandboxes, total)


class SandboxesCreate(BaseModel):
    """Create (or reuse) a sandbox for an agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: CliPositionalArg[str] = Field(description="Agent catalog entry")
    external_id: str | None = Field(default=None, description="Override external_id")
    display_name: str | None = Field(default=None, description="Admin-UI label (defaults to external_id)")
    agent_version_id: str | None = Field(default=None, description="Pin to a specific agent version (omit to use current_version)")
    model: str | None = Field(default=None, description="LiteLLM model override")
    param: list[str] = Field(default_factory=list, description="Agent parameter override KEY=VALUE (repeatable)")
    issue_ticket: bool = Field(default=False, description="Mint a WS-connect ticket")

    def cli_cmd(self) -> None:
        client = get_client()
        eid = resolve_external_id(self.external_id)
        params: dict[str, str] = {}
        for item in self.param:
            k, _, v = item.partition("=")
            params[k] = v
        try:
            sandbox, ticket = client.create_sandbox(CreateSandboxInput(
                external_id=eid, agent_id=self.agent_id,
                agent_version_id=self.agent_version_id, model=self.model,
                display_name=self.display_name, parameters=params,
                issue_ticket=self.issue_ticket,
            ))
        except ApiError as e:
            raise SystemExit(str(e)) from e
        if is_json_output():
            out: dict = {"sandbox": sandbox.model_dump(mode="json")}
            if ticket:
                out["ticket"] = ticket.model_dump(mode="json")
            print(json.dumps(out, indent=2))
        else:
            print(f"Sandbox {sandbox.sandbox_id} ({sandbox.state})")
            if ticket:
                print(f"Ticket: {ticket.ticket_val} (expires {ticket.expires_at})")


class SandboxesStop(BaseModel):
    """Stop a sandbox, or every running sandbox for an agent."""

    model_config = ConfigDict(extra="forbid")

    sandbox_id: CliPositionalArg[str] = Field(default="", description="Sandbox to stop")
    agent_id: str | None = Field(default=None, description="Stop every running sandbox for this agent instead")

    def cli_cmd(self) -> None:
        client = get_client()
        if self.sandbox_id:
            targets = [self.sandbox_id]
        elif self.agent_id:
            found, _ = client.search_sandboxes(SearchSandboxesInput(
                agent_id=KeywordFilter(eq=self.agent_id), state=KeywordFilter(eq=SandboxState.RUNNING)))
            targets = [s.sandbox_id for s in found]
        else:
            raise SystemExit("Pass a sandbox id, or --agent-id to stop all of an agent's sandboxes.")

        if not targets:
            print("No running sandboxes.")
            return
        for target in targets:
            try:
                client.stop_sandbox(target)
            except ApiError as e:
                raise SystemExit(str(e)) from e
            print(f"Stopped {target}")


class SandboxesCmd(BaseModel):
    """Manage sandboxes."""

    search: CliSubCommand[SandboxesSearch]
    create: CliSubCommand[SandboxesCreate]
    stop: CliSubCommand[SandboxesStop]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
