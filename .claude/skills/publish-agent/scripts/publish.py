"""Build one agent directory into an image and make it the agent's current version.

Idempotent: the first run registers the agent, every run after that mints a
version and promotes it.

    python3 .claude/skills/publish-agent/scripts/publish.py hello-world

Requires docker, and the vendored CLI installed so a configured Mothership
profile resolves:

    pip install -e cli/mothership-client -e cli/mothership-cli
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from mothership_cli.client import get_client
from mothership_cli.config import ConfigError, resolve_profile, set_active_profile
from mothership_client.client import MothershipClient
from mothership_client.client_models.api_output_model import ApiError
from mothership_client.client_models.common import KeywordFilter
from mothership_client.models.agent_catalog import (
    AgentCatalogEntry,
    AgentParameter,
    CreateAgentInput,
    SearchAgentCatalogInput,
    UpdateAgentInput,
)
from mothership_client.models.agent_version import CreateAgentVersionInput
from mothership_client.models.harness import HarnessType, TransportMode
from mothership_client.models.sandbox import SandboxState, SearchSandboxesInput
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, CliApp, CliPositionalArg, SettingsConfigDict

PLACEHOLDER_SLUG = "change-me"
REQUIRED_AGENT_FILES = ("SOUL.md", "CLAUDE.md", "USER.md")


class PublishError(Exception):
    """Base for every failure this script raises. Handled once, in ``main``."""


class AgentDirectoryInvalid(PublishError):
    """The agent directory is missing or incomplete."""


class ManifestInvalid(PublishError):
    """agent.json is absent, unparseable, or still holds the template slug."""


class RegistryNotConfigured(PublishError):
    """MOTHERSHIP_IMAGE_REGISTRY is unset, so built images have nowhere to go."""


class CommandFailed(PublishError):
    """A docker invocation exited non-zero."""


class PlatformRejected(PublishError):
    """The Mothership API refused a call."""


class ProfileNotResolved(PublishError):
    """No usable Mothership profile — nothing can be published."""


class PublishSettings(BaseSettings):
    """Environment inputs. The registry has no sensible default: an image tag
    that only exists on the participant's laptop is unresolvable from the
    deployment, and fails much later with a far worse error."""

    model_config = SettingsConfigDict(extra="ignore")

    mothership_image_registry: str | None = Field(
        default=None,
        description="Registry prefix the deployment pulls from, e.g. ghcr.io/<org>/agent-workshop",
    )
    agent_version: str | None = Field(
        default=None,
        description="Version label to mint; defaults to a UTC timestamp",
    )

    def registry(self) -> str:
        if not self.mothership_image_registry:
            raise RegistryNotConfigured(
                "MOTHERSHIP_IMAGE_REGISTRY is not set.\n\n"
                "Set it to the registry prefix the deployment pulls from, then re-run:\n\n"
                "  export MOTHERSHIP_IMAGE_REGISTRY=ghcr.io/<org>/agent-workshop\n\n"
                "Ask the workshop staff for the value if you don't have it."
            )
        return self.mothership_image_registry.rstrip("/")

    def version_label(self) -> str:
        return self.agent_version or datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


class AgentManifest(BaseModel):
    """agent.json — the catalog metadata for one agent directory.

    Deliberately a subset of CreateAgentInput: image and version come from the
    build, not from a file a participant edits."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", description="Catalog identifier, unique per org")
    name: str = Field(min_length=1)
    description: str = ""
    harness: HarnessType = HarnessType.OPENCLAW
    transport: TransportMode | None = Field(default=None, description="Omit to take the server default (RELAY)")
    default_model: str | None = None
    parameters: list[AgentParameter] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> AgentManifest:
        if not path.is_file():
            raise ManifestInvalid(f"missing {path}")
        try:
            manifest = cls.model_validate_json(path.read_text())
        except ValidationError as exc:
            fields = "\n  ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise ManifestInvalid(f"{path} is not a valid agent manifest:\n  {fields}") from exc
        if manifest.slug == PLACEHOLDER_SLUG:
            raise ManifestInvalid(f"set a real 'slug' in {path}")
        return manifest


class AgentSource(BaseModel):
    """A validated agent directory, ready to build."""

    model_config = ConfigDict(extra="forbid")

    directory: Path
    manifest: AgentManifest

    @classmethod
    def load(cls, repo_root: Path, agent: str) -> AgentSource:
        directory = repo_root / "agents" / agent
        if not directory.is_dir():
            raise AgentDirectoryInvalid(f"no such agent directory: agents/{agent}")
        missing = [name for name in REQUIRED_AGENT_FILES if not (directory / name).is_file()]
        if missing:
            raise AgentDirectoryInvalid(f"agents/{agent} is missing: {', '.join(missing)}")
        return cls(directory=directory, manifest=AgentManifest.load(directory / "agent.json"))


class BuiltImage(BaseModel):
    """The image reference produced by a build, once it is in the registry."""

    model_config = ConfigDict(extra="forbid")

    reference: str
    version: str


class PublishResult(BaseModel):
    """What the participant needs from a successful publish."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    agent_id: str
    image: BuiltImage
    created: bool = Field(description="True when this run registered the agent for the first time")
    stopped_sandboxes: list[str] = Field(default_factory=list)

    def render(self) -> str:
        lines = [
            "",
            f"published: {self.slug} ({'new agent' if self.created else 'new version'})",
            f"  agent_id: {self.agent_id}",
            f"  version:  {self.image.version}",
            f"  image:    {self.image.reference}",
            "",
            f"talk to it:  mothership messages submit 'hello' --agent-id {self.agent_id}",
        ]
        return "\n".join(lines)


def run_command(command: list[str], step: str) -> None:
    """Run a subprocess, streaming its output, and raise if it fails."""
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise CommandFailed(f"{step} failed (exit {completed.returncode}): {' '.join(command)}")


def build_and_push(repo_root: Path, source: AgentSource, settings: PublishSettings) -> BuiltImage:
    """Bake the agent workspace into an image and put it where the deployment can pull it."""
    version = settings.version_label()
    image = BuiltImage(reference=f"{settings.registry()}/{source.manifest.slug}:{version}", version=version)
    agent_dir_name = source.directory.name

    print(f"▸ building {image.reference} from agents/{agent_dir_name}")
    run_command(
        [
            "docker", "build",
            "--build-arg", f"AGENT={agent_dir_name}",
            "-t", image.reference,
            "-f", str(repo_root / "agents" / "Dockerfile"),
            str(repo_root / "agents"),
        ],
        step="docker build",
    )

    print(f"▸ pushing {image.reference}")
    run_command(["docker", "push", image.reference], step="docker push")
    return image


def find_agent(client: MothershipClient, slug: str) -> AgentCatalogEntry | None:
    agents, _ = client.search_agents(SearchAgentCatalogInput(slug=KeywordFilter(eq=slug)))
    return agents[0] if agents else None


def register_agent(client: MothershipClient, manifest: AgentManifest, image: BuiltImage) -> AgentCatalogEntry:
    """First publish: create the catalog row, which mints its first version."""
    print(f"▸ registering new agent '{manifest.slug}'")
    return client.create_agent(
        CreateAgentInput(
            slug=manifest.slug,
            name=manifest.name,
            description=manifest.description,
            harness=manifest.harness,
            transport=manifest.transport or TransportMode.RELAY,
            default_model=manifest.default_model,
            parameters=manifest.parameters,
            image=image.reference,
            version=image.version,
        )
    )


def promote_version(client: MothershipClient, agent: AgentCatalogEntry, manifest: AgentManifest,
                    image: BuiltImage) -> None:
    """Later publishes: mint a version, promote it, and re-push catalog-level fields.

    Parameters, name, description, and model live on the catalog row rather than
    on the version, so a manifest edit needs its own call."""
    print(f"▸ agent exists ({agent.agent_id}) — adding version {image.version} and promoting it")
    version = client.create_agent_version(
        CreateAgentVersionInput(agent_id=agent.agent_id, version=image.version, image=image.reference, enabled=True)
    )
    client.update_agent(
        UpdateAgentInput(
            agent_id=agent.agent_id,
            name=manifest.name,
            description=manifest.description,
            default_model=manifest.default_model,
            parameters=manifest.parameters,
            current_version=version.version_id,
        )
    )


def stop_stale_sandboxes(client: MothershipClient, agent_id: str) -> list[str]:
    """A running sandbox holds the image it booted with, so it would keep
    serving the previous version. Stop it and let the next message reprovision."""
    sandboxes, _ = client.search_sandboxes(
        SearchSandboxesInput(agent_id=KeywordFilter(eq=agent_id), state=KeywordFilter(eq=SandboxState.RUNNING))
    )
    stopped: list[str] = []
    for sandbox in sandboxes:
        print(f"▸ stopping stale sandbox {sandbox.sandbox_id}")
        client.stop_sandbox(sandbox.sandbox_id)
        stopped.append(sandbox.sandbox_id)
    return stopped


def connect() -> MothershipClient:
    """Resolve the active profile the same way the CLI does, then build a client."""
    try:
        name, profile = resolve_profile(None)
        set_active_profile(name, profile)
        # get_client resolves the org, identity, and API key, and any of the
        # three can be misconfigured — so it is inside the guard too.
        return get_client()
    except ConfigError as exc:
        raise ProfileNotResolved(f"{exc}\n\nCheck `mothership profiles list`.") from exc


def publish(repo_root: Path, agent: str, settings: PublishSettings) -> PublishResult:
    source = AgentSource.load(repo_root, agent)
    settings.registry()  # fail before a five-minute build, not after it
    client = connect()

    image = build_and_push(repo_root, source, settings)

    print(f"▸ resolving '{source.manifest.slug}' in the catalog")
    try:
        existing = find_agent(client, source.manifest.slug)
        if existing is None:
            entry = register_agent(client, source.manifest, image)
            created = True
        else:
            promote_version(client, existing, source.manifest, image)
            entry = existing
            created = False
        stopped = stop_stale_sandboxes(client, entry.agent_id)
    except ApiError as exc:
        raise PlatformRejected(str(exc)) from exc

    return PublishResult(
        slug=source.manifest.slug,
        agent_id=entry.agent_id,
        image=image,
        created=created,
        stopped_sandboxes=stopped,
    )


class Publish(BaseModel):
    """Build an agent directory and make it the agent's current version."""

    model_config = ConfigDict(extra="forbid")

    agent: CliPositionalArg[str] = Field(description="Directory name under agents/, e.g. hello-world")

    def cli_cmd(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        print(publish(repo_root, self.agent, PublishSettings()).render())


def describe_validation_error(error: ValidationError) -> str:
    """Render a pydantic failure as the flag the user actually typed."""
    lines = []
    for item in error.errors():
        field = ".".join(str(part) for part in item["loc"])
        flag = f"--{field.replace('_', '-')}" if field else ""
        lines.append(f"{flag}: {item['msg']}".lstrip(": "))
    return "\n".join(lines)


def main() -> None:
    try:
        CliApp.run(Publish)
    except PublishError as exc:
        sys.stderr.write(f"\n{exc}\n")
        raise SystemExit(1) from exc
    except ValidationError as exc:
        sys.stderr.write(f"\nError: {describe_validation_error(exc)}\n")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
