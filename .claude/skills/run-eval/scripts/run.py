"""Sync an agent's eval task files to the platform, run them, and print the report.

Idempotent: a task file whose slug already exists is updated in place, so
editing a rubric and re-running re-scores against the new one under the same
task and the history stays comparable.

    python3 .claude/skills/run-eval/scripts/run.py quake-watch
    python3 .claude/skills/run-eval/scripts/run.py quake-watch --tasks recent-activity

Requires the vendored CLI installed so a configured Mothership profile resolves:

    pip install -e cli/mothership-client -e cli/mothership-cli
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from mothership_cli.client import get_client
from mothership_cli.config import ConfigError, resolve_profile, set_active_profile
from mothership_cli.evals.report import render_report
from mothership_client.client import MothershipClient
from mothership_client.client_models.api_output_model import ApiError, ApiOutputModel
from mothership_client.client_models.common import KeywordFilter
from mothership_client.models.agent_catalog import SearchAgentCatalogInput
from mothership_client.models.eval_run import (
    CreateEvalRunInput,
    EvalResult,
    EvalRun,
    EvalRunStatus,
    RunExecutor,
    SearchEvalResultInput,
)
from mothership_client.models.eval_task import CreateEvalTaskInput, EvalTask, SearchEvalTaskInput, UpdateEvalTaskInput
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import BaseSettings, CliApp, CliPositionalArg, SettingsConfigDict

TERMINAL_STATUSES = (EvalRunStatus.COMPLETED, EvalRunStatus.FAILED, EvalRunStatus.CANCELLED)


class RunEvalError(Exception):
    """Base for every failure this script raises. Handled once, in ``main``."""


class AgentDirectoryInvalid(RunEvalError):
    """The agent directory or its manifest is missing."""


class AgentNotPublished(RunEvalError):
    """The agent is not in the catalog, so there is nothing to evaluate."""


class TaskFileInvalid(RunEvalError):
    """A task file is absent or does not validate against the platform models."""


class NoTasks(RunEvalError):
    """No task files matched."""


class PlatformRejected(RunEvalError):
    """The Mothership API refused a call."""


class ProfileNotResolved(RunEvalError):
    """No usable Mothership profile."""


class RunTimedOut(RunEvalError):
    """The run did not reach a terminal status inside the wait budget."""


class RunSettings(BaseSettings):
    """Environment overrides for the poll loop. Each task provisions its own
    sandbox, runs the agent, then judges the response — minutes, not seconds."""

    model_config = SettingsConfigDict(extra="ignore")

    eval_timeout_sec: int = Field(default=1800, gt=0, description="Give up waiting after this long")
    eval_poll_interval_sec: float = Field(default=10.0, gt=0, description="Seconds between status checks")


class AgentRef(BaseModel):
    """The two identifiers for one agent, resolved together so the rest of the
    script never has to guess which one an API wants."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    agent_id: str


class TaskFile(BaseModel):
    """One eval task file on disk, parsed but not yet bound to an agent."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    document: CreateEvalTaskInput

    @classmethod
    def load(cls, path: Path, agent_id: str) -> TaskFile:
        """Files on disk carry no agent_id — it is injected here from the
        manifest's slug, so the same task file works for any participant."""
        if not path.is_file():
            raise TaskFileInvalid(f"no such eval file: {path}")
        try:
            document = CreateEvalTaskInput.model_validate(json.loads(path.read_text()) | {"agent_id": agent_id})
        except json.JSONDecodeError as exc:
            raise TaskFileInvalid(f"{path} is not valid JSON: {exc}") from exc
        except ValidationError as exc:
            fields = "\n  ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise TaskFileInvalid(
                f"{path} does not validate:\n  {fields}\n\n"
                "Run the validator for the same check without a round trip:\n"
                "  python3 .claude/skills/author-eval/scripts/validate.py <path>"
            ) from exc
        return cls(path=path, document=document)


class SyncedTask(BaseModel):
    """A task file after it has been created or updated on the platform."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    slug: str
    created: bool

    def render(self) -> str:
        return f"▸ {'created' if self.created else 'updated'} task {self.slug} ({self.task_id})"


class RunProgress(BaseModel):
    """One poll of the run's state."""

    model_config = ConfigDict(extra="forbid")

    status: EvalRunStatus
    finished: int
    total: int

    @classmethod
    def of(cls, run: EvalRun) -> RunProgress:
        return cls(status=run.status, finished=run.completed_count + run.failed_count, total=run.task_count)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def render(self) -> str:
        return f"  {self.status:<12} {self.finished}/{self.total} "


class RunOutcome(BaseModel):
    """The finished run and everything needed to report or compare it."""

    model_config = ConfigDict(extra="forbid")

    run: EvalRun
    results: list[EvalResult] = Field(default_factory=list)

    def render(self) -> str:
        report = render_report(self.run, self.results, None)
        return (
            f"\n{report}\n\nrun_id: {self.run.run_id}\n"
            f"compare against a previous run:\n"
            f"  mothership evals report --run-id {self.run.run_id} --previous <older_run_id>"
        )


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


def read_manifest_slug(repo_root: Path, agent: str) -> str:
    """The catalog slug lives in agent.json; the directory name may differ."""
    manifest_path = repo_root / "agents" / agent / "agent.json"
    if not manifest_path.is_file():
        raise AgentDirectoryInvalid(f"missing agents/{agent}/agent.json")

    class _Slug(BaseModel):
        model_config = ConfigDict(extra="ignore")

        slug: str

    try:
        return _Slug.model_validate_json(manifest_path.read_text()).slug
    except ValidationError as exc:
        raise AgentDirectoryInvalid(f"{manifest_path} has no usable 'slug'") from exc


def resolve_agent(client: MothershipClient, slug: str) -> AgentRef:
    agents, _ = client.search_agents(SearchAgentCatalogInput(slug=KeywordFilter(eq=slug)))
    if not agents:
        raise AgentNotPublished(
            f"agent '{slug}' is not in the catalog — publish it first:\n"
            f"  python3 .claude/skills/publish-agent/scripts/publish.py <agent-dir>"
        )
    return AgentRef(slug=slug, agent_id=agents[0].agent_id)


def collect_task_files(repo_root: Path, agent: str, agent_id: str, names: list[str]) -> list[TaskFile]:
    """Named files if given, otherwise every task file in the agent's evals/."""
    eval_dir = repo_root / "agents" / agent / "evals"
    if not eval_dir.is_dir():
        raise NoTasks(f"no evals/ directory under agents/{agent}")
    paths = [eval_dir / f"{name.removesuffix('.json')}.json" for name in names] if names \
        else sorted(eval_dir.glob("*.json"))
    if not paths:
        raise NoTasks(f"no eval task files under agents/{agent}/evals/")
    return [TaskFile.load(path, agent_id) for path in paths]


def find_task(client: MothershipClient, slug: str) -> EvalTask | None:
    query = SearchEvalTaskInput(slug=KeywordFilter(eq=slug), limit=1)
    data = client._request("POST", client._scoped("evals", "/tasks/search"),
                           json=query.model_dump(mode="json", exclude_none=True))
    records = ApiOutputModel[EvalTask].model_validate(data).records or []
    return records[0] if records else None


def sync_task(client: MothershipClient, task_file: TaskFile) -> SyncedTask:
    """Create the task, or replace the stored document when the slug already exists."""
    existing = find_task(client, task_file.document.slug)
    if existing is None:
        data = client._request("POST", client._scoped("evals", "/tasks"),
                               json=task_file.document.model_dump(mode="json", exclude_none=True))
        records = ApiOutputModel[EvalTask].model_validate(data).records or []
        return SyncedTask(task_id=records[0].task_id, slug=records[0].slug, created=True)

    # agent_id is immutable on a task; the patch carries content only.
    patch = UpdateEvalTaskInput(
        slug=task_file.document.slug,
        description=task_file.document.description,
        tags=task_file.document.tags,
        spec=task_file.document.spec,
        enabled=True,
    )
    client._request("PATCH", client._scoped("evals", f"/tasks/{existing.task_id}"),
                    json=patch.model_dump(mode="json", exclude_none=True))
    return SyncedTask(task_id=existing.task_id, slug=existing.slug, created=False)


def create_run(client: MothershipClient, agent: AgentRef, task_ids: list[str]) -> EvalRun:
    request = CreateEvalRunInput(agent_id=agent.agent_id, task_ids=task_ids, executor=RunExecutor.PLATFORM)
    data = client._request("POST", client._scoped("evals", "/runs"),
                           json=request.model_dump(mode="json", exclude_none=True))
    return (ApiOutputModel[EvalRun].model_validate(data).records or [])[0]


def get_run(client: MothershipClient, run_id: str) -> EvalRun:
    data = client._request("GET", client._scoped("evals", f"/runs/{run_id}"))
    return (ApiOutputModel[EvalRun].model_validate(data).records or [])[0]


def get_results(client: MothershipClient, run_id: str) -> list[EvalResult]:
    query = SearchEvalResultInput(run_id=KeywordFilter(eq=run_id), limit=1000)
    data = client._request("POST", client._scoped("evals", "/results/search"),
                           json=query.model_dump(mode="json", exclude_none=True))
    return ApiOutputModel[EvalResult].model_validate(data).records or []


def wait_for_run(client: MothershipClient, run_id: str, settings: RunSettings) -> EvalRun:
    """Watch until the run reaches a terminal status. The platform executor does
    the work; this only reports on it."""
    deadline = time.monotonic() + settings.eval_timeout_sec
    while True:
        run = get_run(client, run_id)
        progress = RunProgress.of(run)
        sys.stdout.write(f"\r{progress.render()}")
        sys.stdout.flush()
        if progress.terminal:
            sys.stdout.write("\n")
            return run
        if time.monotonic() > deadline:
            sys.stdout.write("\n")
            raise RunTimedOut(
                f"gave up waiting for run {run_id} after {settings.eval_timeout_sec}s (still {progress.status}).\n"
                f"It is still running server-side. Check it with:\n"
                f"  mothership evals report --run-id {run_id}"
            )
        time.sleep(settings.eval_poll_interval_sec)


def run_evals(repo_root: Path, agent: str, task_names: list[str], settings: RunSettings) -> RunOutcome:
    # Local checks first: a typo'd agent name should not need a working profile
    # to produce its error.
    slug = read_manifest_slug(repo_root, agent)
    client = connect()
    agent_ref = resolve_agent(client, slug)
    print(f"▸ agent {agent_ref.slug} ({agent_ref.agent_id})")

    task_files = collect_task_files(repo_root, agent, agent_ref.agent_id, task_names)
    try:
        synced = [sync_task(client, task_file) for task_file in task_files]
        for task in synced:
            print(task.render())

        run = create_run(client, agent_ref, [task.task_id for task in synced])
        print(f"▸ run {run.run_id} over {len(synced)} task(s)")

        finished = wait_for_run(client, run.run_id, settings)
        return RunOutcome(run=finished, results=get_results(client, finished.run_id))
    except ApiError as exc:
        raise PlatformRejected(str(exc)) from exc


class RunEval(BaseModel):
    """Sync an agent's eval tasks, run them, and print the scored report."""

    model_config = ConfigDict(extra="forbid")

    agent: CliPositionalArg[str] = Field(description="Directory name under agents/, e.g. quake-watch")
    tasks: list[str] = Field(default_factory=list, description="Task file names to run; omit for all of them")

    def cli_cmd(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        print(run_evals(repo_root, self.agent, self.tasks, RunSettings()).render())


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
        CliApp.run(RunEval)
    except RunEvalError as exc:
        sys.stderr.write(f"\n{exc}\n")
        raise SystemExit(1) from exc
    except ValidationError as exc:
        sys.stderr.write(f"\nError: {describe_validation_error(exc)}\n")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
