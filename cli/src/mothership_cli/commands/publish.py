"""``mothership publish`` — build an agent directory and make it the live version.

One command for what is otherwise a docker build, a push, a catalog write, a
version promotion, and a sandbox recycle.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from mothership_cli.client import get_client
from mothership_cli.client_models.common import KeywordFilter
from mothership_cli.errors import MothershipCliError
from mothership_cli.http import ApiError, MothershipClient
from mothership_cli.models.agent_catalog import (
    AgentCatalogEntry,
    CreateAgentInput,
    SearchAgentCatalogInput,
    UpdateAgentInput,
)
from mothership_cli.models.agent_version import CreateAgentVersionInput, SearchAgentVersionsInput
from mothership_cli.models.harness import TransportMode
from mothership_cli.models.sandbox import SandboxState, SearchSandboxesInput
from mothership_cli.workspace import Agent, AgentManifest
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import CliPositionalArg


class PublishError(MothershipCliError):
    """Publishing failed. Handled by the CLI's top-level handler."""


def _run(command: list[str], step: str) -> None:
    if subprocess.run(command, check=False).returncode != 0:
        raise PublishError(f"{step} failed: {' '.join(command)}")


def _find(client: MothershipClient, slug: str) -> AgentCatalogEntry | None:
    agents, _ = client.search_agents(SearchAgentCatalogInput(slug=KeywordFilter(eq=slug)))
    return agents[0] if agents else None


def _register(client: MothershipClient, slug: str, m: AgentManifest, image: str, version: str) -> AgentCatalogEntry:
    return client.create_agent(CreateAgentInput(
        slug=slug, name=m.name, description=m.description, harness=m.harness,
        transport=m.transport or TransportMode.RELAY, default_model=m.default_model,
        parameters=m.parameters, image=image, version=version,
    ))


def _promote(client: MothershipClient, agent: AgentCatalogEntry, m: AgentManifest, image: str, version: str) -> None:
    try:
        new = client.create_agent_version(CreateAgentVersionInput(
            agent_id=agent.agent_id, version=version, image=image, enabled=True))
    except ApiError as exc:
        if exc.status != 409:
            raise
        # The label already exists (e.g. --skip-build re-run); promote that one.
        versions, _ = client.search_agent_versions(SearchAgentVersionsInput(
            agent_id=KeywordFilter(eq=agent.agent_id), version=KeywordFilter(eq=version)))
        new = versions[0]
    # Model and parameters live on the catalog row rather than the version, so
    # a manifest edit needs its own call.
    client.update_agent(UpdateAgentInput(
        agent_id=agent.agent_id, name=m.name, description=m.description,
        default_model=m.default_model, parameters=m.parameters, current_version=new.version_id))


def _recycle(client: MothershipClient, agent_id: str) -> int:
    """A running sandbox keeps the image it booted with, so it would serve the
    previous version until it is stopped."""
    sandboxes, _ = client.search_sandboxes(SearchSandboxesInput(
        agent_id=KeywordFilter(eq=agent_id), state=KeywordFilter(eq=SandboxState.RUNNING)))
    for sandbox in sandboxes:
        client.stop_sandbox(sandbox.sandbox_id)
    return len(sandboxes)


class PublishCmd(BaseModel):
    """Build an agent directory into an image and make it the live version."""

    model_config = ConfigDict(extra="forbid")

    agent: CliPositionalArg[str] = Field(description="Directory name under agents/")
    slug: str | None = Field(default=None, description="Catalog id (default: the manifest's slug)")
    registry: str | None = Field(default=None, description="Image registry (default: $MOTHERSHIP_IMAGE_REGISTRY)")
    version: str | None = Field(default=None, description="Version label (default: a UTC timestamp)")
    agents_dir: str = Field(default="agents", description="Where agent directories live")
    skip_build: bool = Field(default=False, description="Reuse the image already in the registry")

    def cli_cmd(self) -> None:
        import os

        source = Agent.load(self.agent, self.agents_dir)
        slug = self.slug or source.manifest.slug
        registry = (self.registry or os.environ.get("MOTHERSHIP_IMAGE_REGISTRY", "")).rstrip("/")
        if not registry:
            raise PublishError(
                "No image registry. Pass --registry or set MOTHERSHIP_IMAGE_REGISTRY.\n"
                "A local image tag will not work: the deployment pulls from a registry."
            )
        version = self.version or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        image = f"{registry}/{slug}:{version}"
        client = get_client()

        if not self.skip_build:
            print(f"building {image}")
            _run(["docker", "build", "--build-arg", f"AGENT={self.agent}", "-t", image,
                  "-f", f"{self.agents_dir}/Dockerfile", self.agents_dir], "docker build")
            print(f"pushing {image}")
            _run(["docker", "push", image], "docker push")

        try:
            existing = _find(client, slug)
            if existing is None:
                agent = _register(client, slug, source.manifest, image, version)
                print(f"registered {slug}")
            else:
                agent = existing
                _promote(client, agent, source.manifest, image, version)
                print(f"promoted {slug} to {version}")
            stopped = _recycle(client, agent.agent_id)
        except ApiError as exc:
            raise PublishError(str(exc)) from exc

        if stopped:
            print(f"stopped {stopped} running sandbox(es)")
        print(f"\nagent_id  {agent.agent_id}")
        print(f"image     {image}")
