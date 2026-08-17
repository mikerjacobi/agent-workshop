"""Reading an agent directory off disk.

An agent is a folder under ``agents/``: a persona, a manifest, its skills, and
its evals. ``publish`` and ``evals run`` both start here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mothership_cli.errors import MothershipCliError
from mothership_cli.models.agent_catalog import AgentParameter
from mothership_cli.models.harness import HarnessType, TransportMode
from pydantic import BaseModel, ConfigDict, Field, ValidationError

REQUIRED_FILES = ("SOUL.md",)


class WorkspaceError(MothershipCliError):
    """The agent directory is missing, incomplete, or has a bad manifest."""


class AgentManifest(BaseModel):
    """``agent.json``. A subset of CreateAgentInput: the image and version come
    from the build, not from a file anyone edits."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    description: str = ""
    harness: HarnessType = HarnessType.OPENCLAW
    transport: TransportMode | None = None
    default_model: str | None = None
    parameters: list[AgentParameter] = Field(default_factory=list)


class Agent(BaseModel):
    """A validated agent directory."""

    model_config = ConfigDict(extra="forbid")

    directory: Path
    manifest: AgentManifest

    @property
    def eval_dir(self) -> Path:
        return self.directory / "evals"

    def eval_files(self, only: str | None = None) -> list[Path]:
        if not self.eval_dir.is_dir():
            raise WorkspaceError(f"no evals/ directory under {self.directory}")
        if only:
            path = self.eval_dir / f"{only.removesuffix('.json')}.json"
            if not path.is_file():
                raise WorkspaceError(f"no such eval file: {path}")
            return [path]
        files = sorted(self.eval_dir.glob("*.json"))
        if not files:
            raise WorkspaceError(f"no eval files under {self.eval_dir}")
        return files

    @classmethod
    def load(cls, name: str, agents_dir: str = "agents") -> Agent:
        directory = Path(agents_dir) / name
        if not directory.is_dir():
            raise WorkspaceError(f"no such agent directory: {directory}")
        missing = [f for f in REQUIRED_FILES if not (directory / f).is_file()]
        if missing:
            raise WorkspaceError(f"{directory} is missing: {', '.join(missing)}")

        manifest_path = directory / "agent.json"
        if not manifest_path.is_file():
            raise WorkspaceError(f"missing {manifest_path}")
        try:
            manifest = AgentManifest.model_validate_json(manifest_path.read_text())
        except ValidationError as exc:
            fields = "\n  ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise WorkspaceError(f"{manifest_path} is not a valid manifest:\n  {fields}") from exc
        return cls(directory=directory, manifest=manifest)


def read_eval_task(path: Path, agent_id: str, slug: str) -> dict:
    """One eval file, ready to POST. The file carries neither the agent nor the
    caller's slug prefix, so both are stamped on here."""
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"{path} is not valid JSON: {exc}") from exc
    document["agent_id"] = agent_id
    document["slug"] = slug
    return document


# Build noise that must not ship inside a skill directory.
_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def stage_build_context(agent: Agent, context: Path, agents_dir: str = "agents") -> None:
    """Lay out the docker build context: the seed script plus the reshaped
    workspace. The reshape is the runtime convention: ``agent.json`` and
    ``evals/`` are CLI inputs and never ship, and ``skills/`` is authored where
    a person looks while the harness discovers ``.claude/skills/``."""
    workspace = context / "workspace"
    shutil.copytree(agent.directory, workspace, symlinks=False, ignore=_IGNORE)
    (workspace / "agent.json").unlink(missing_ok=True)
    shutil.rmtree(workspace / "evals", ignore_errors=True)
    skills = workspace / "skills"
    if skills.is_dir():
        (workspace / ".claude").mkdir()
        skills.rename(workspace / ".claude" / "skills")
    shutil.copy2(Path(agents_dir) / "agent-pre-start.sh", context / "agent-pre-start.sh")
