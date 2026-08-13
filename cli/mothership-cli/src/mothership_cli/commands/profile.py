"""``mothership profile`` — manage connection profiles."""

from __future__ import annotations

import os

from mothership_cli.config import Profile, load_config, save_config
from pydantic import BaseModel, Field
from pydantic_settings import CliApp, CliPositionalArg, CliSubCommand


class ProfileSet(BaseModel):
    """Store a named profile."""

    name: CliPositionalArg[str] = Field(description="Profile name")
    base_url: str = Field(description="API base URL (e.g. http://localhost:5100)")
    ws_url: str | None = Field(default=None, description="Coordinator WS URL (derived from base_url if omitted)")
    org: str | None = Field(default=None, description="Org id for tenancy-scoped resources (default: the shared 'default' org)")
    external_id: str | None = Field(default=None, description="Default external_id")
    agent_id: str | None = Field(default=None, description="Default agent_id")
    max_local_sandboxes: int | None = Field(default=None, description="Max running sandboxes; oldest stopped when exceeded (local dev)")
    api_key_env: str | None = Field(default=None, description="Env var holding this profile's API key (convention: MOTHERSHIP_API_KEY_<ENV>); the key itself is never stored")

    def cli_cmd(self) -> None:
        config = load_config()
        config.profiles[self.name] = Profile(
            base_url=self.base_url, ws_url=self.ws_url, org=self.org,
            default_external_id=self.external_id, default_agent_id=self.agent_id,
            max_local_sandboxes=self.max_local_sandboxes, api_key_env=self.api_key_env,
        )
        if not config.default_profile:
            config.default_profile = self.name
        save_config(config)
        default_note = " (set as default)" if config.default_profile == self.name else ""
        print(f"Profile '{self.name}' saved → {self.base_url}{default_note}")


class ProfileList(BaseModel):
    """List configured profiles."""

    def cli_cmd(self) -> None:
        config = load_config()
        if not config.profiles:
            print("No profiles configured. Run: mothership profile set <name> --base-url <url>")
            return
        for name, p in config.profiles.items():
            marker = " *" if name == config.default_profile else ""
            extras = []
            if p.org:
                extras.append(f"org={p.org}")
            if p.default_external_id:
                extras.append(f"external_id={p.default_external_id}")
            if p.default_agent_id:
                extras.append(f"agent_id={p.default_agent_id}")
            if p.ws_url:
                extras.append(f"ws_url={p.ws_url}")
            if p.max_local_sandboxes is not None:
                extras.append(f"max_local_sandboxes={p.max_local_sandboxes}")
            if p.api_key_env:
                extras.append(f"api_key_env=${p.api_key_env}{'' if os.environ.get(p.api_key_env) else ' (unset)'}")
            suffix = f"  ({', '.join(extras)})" if extras else ""
            print(f"  {name}{marker}: {p.base_url}{suffix}")


class ProfileSetDefault(BaseModel):
    """Switch the default profile."""

    name: CliPositionalArg[str] = Field(description="Profile to make default")

    def cli_cmd(self) -> None:
        config = load_config()
        if self.name not in config.profiles:
            raise SystemExit(f"Profile '{self.name}' not found. Run: mothership profile set {self.name} --base-url <url>")
        config.default_profile = self.name
        save_config(config)
        print(f"Default profile set to '{self.name}'")


class ProfileCmd(BaseModel):
    """Manage connection profiles."""

    set: CliSubCommand[ProfileSet]
    list: CliSubCommand[ProfileList]
    set_default: CliSubCommand[ProfileSetDefault]

    def cli_cmd(self) -> None:
        CliApp.run_subcommand(self)
