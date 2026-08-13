"""Validate eval task files against the platform's own pydantic models.

The server rejects a bad spec with a 422 after a network round trip; this
catches the same errors locally, with the field path, before anything runs.

    python3 .claude/skills/author-eval/scripts/validate.py agents/hello-world/evals
    python3 .claude/skills/author-eval/scripts/validate.py agents/hello-world/evals/iss-position.json

The models come from the vendored ``mothership-client`` package in ``cli/`` —
the exact classes the API validates with, not a copy of them.
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_settings import CliApp, CliPositionalArg

if TYPE_CHECKING:
    from mothership_client.models.eval_spec import EvalTaskSpec

# Task files on disk carry no agent_id — run.py injects it from agent.json at
# sync time — so validation supplies a placeholder to satisfy the model.
PLACEHOLDER_AGENT_ID = "agent_validate"
MIN_RUBRIC_CHARS = 60


class ValidateError(Exception):
    """Base for every failure this script raises. Handled once, in ``main``."""


class MissingDependency(ValidateError):
    """The vendored mothership-client package is not importable."""


class PathNotFound(ValidateError):
    """A path given on the command line does not exist."""


class NoTaskFiles(ValidateError):
    """The given paths contained no .json task files."""


class TasksInvalid(ValidateError):
    """At least one task file failed validation."""


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Problem(BaseModel):
    """One finding about one task file."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    message: str = Field(description="What is wrong, in the author's terms")
    field_path: str | None = Field(default=None, description="Dotted path into the document, when known")

    def render(self) -> str:
        prefix = "warn: " if self.severity == Severity.WARNING else ""
        location = f"{self.field_path}: " if self.field_path else ""
        return f"{prefix}{location}{self.message}"


class FileReport(BaseModel):
    """The outcome for a single task file."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    problems: list[Problem] = Field(default_factory=list)

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == Severity.ERROR]

    def render(self) -> str:
        if not self.problems:
            status = "ok"
        elif self.errors:
            status = "FAIL"
        else:
            status = "warn"
        lines = [f"{status:<5} {self.path}"]
        lines.extend(f"        {problem.render()}" for problem in self.problems)
        return "\n".join(lines)


class ValidationReport(BaseModel):
    """Every file that was checked, and whether the run should fail."""

    model_config = ConfigDict(extra="forbid")

    files: list[FileReport] = Field(default_factory=list)

    @property
    def invalid(self) -> list[FileReport]:
        return [report for report in self.files if report.errors]

    def render(self) -> str:
        return "\n".join(report.render() for report in self.files)


class EvalModels(BaseModel):
    """The platform model classes, imported lazily so a missing dependency
    surfaces as a ValidateError rather than an import-time traceback."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    create_input: type
    task_spec: type

    @classmethod
    def load(cls) -> EvalModels:
        try:
            from mothership_client.models.eval_spec import EvalTaskSpec
            from mothership_client.models.eval_task import CreateEvalTaskInput
        except ImportError as exc:
            raise MissingDependency(
                "mothership-client is not installed. From the repo root:\n"
                "  pip install -e cli/mothership-client -e cli/mothership-cli"
            ) from exc
        return cls(create_input=CreateEvalTaskInput, task_spec=EvalTaskSpec)


def collect_task_files(paths: list[str]) -> list[Path]:
    """Expand directories to the .json files inside them, keeping file paths as given."""
    collected: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise PathNotFound(f"no such path: {path}")
        collected.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    if not collected:
        raise NoTaskFiles(f"no .json task files under: {', '.join(paths)}")
    return collected


def lint_spec(spec: EvalTaskSpec) -> list[Problem]:
    """Warnings the schema permits but that make an eval score inconsistently."""
    problems: list[Problem] = []
    for index, scorer in enumerate(spec.scorers):
        if scorer.kind != "llm_judge":
            continue
        if not scorer.reference:
            problems.append(
                Problem(
                    severity=Severity.WARNING,
                    field_path=f"spec.scorers.{index}.reference",
                    message="no reference — the judge grades with no ground truth and scores will be noisy",
                )
            )
        for criterion_index, criterion in enumerate(scorer.criteria):
            rubric = getattr(criterion, "rubric", None)
            if rubric is not None and len(rubric) < MIN_RUBRIC_CHARS:
                problems.append(
                    Problem(
                        severity=Severity.WARNING,
                        field_path=f"spec.scorers.{index}.criteria.{criterion_index}.rubric",
                        message="very short rubric — say what full marks and zero look like, concretely",
                    )
                )
    return problems


def check_task_file(path: Path, models: EvalModels) -> FileReport:
    """Validate one task file and collect every problem with it."""
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return FileReport(path=path, problems=[Problem(severity=Severity.ERROR, message=f"not valid JSON: {exc}")])

    if "agent_id" in document:
        problem = Problem(
            severity=Severity.ERROR,
            field_path="agent_id",
            message="remove it — the agent is injected at sync time from agent.json's slug",
        )
        return FileReport(path=path, problems=[problem])

    try:
        models.create_input(agent_id=PLACEHOLDER_AGENT_ID, **document)
    except ValidationError as exc:
        problems = [
            Problem(
                severity=Severity.ERROR,
                field_path=".".join(str(part) for part in error["loc"]) or None,
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        return FileReport(path=path, problems=problems)
    except TypeError as exc:
        return FileReport(path=path, problems=[Problem(severity=Severity.ERROR, message=str(exc))])

    return FileReport(path=path, problems=lint_spec(models.task_spec.model_validate(document["spec"])))


def validate(paths: list[str]) -> ValidationReport:
    """Check every task file the paths resolve to."""
    models = EvalModels.load()
    return ValidationReport(files=[check_task_file(path, models) for path in collect_task_files(paths)])


class Validate(BaseModel):
    """Validate eval task files against the platform's pydantic models."""

    model_config = ConfigDict(extra="forbid")

    paths: CliPositionalArg[list[str]] = Field(description="Task files or directories containing them")

    def cli_cmd(self) -> None:
        report = validate(self.paths)
        print(report.render())
        if report.invalid:
            raise TasksInvalid(f"{len(report.invalid)} of {len(report.files)} task file(s) failed validation")


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
        CliApp.run(Validate)
    except ValidateError as exc:
        sys.stderr.write(f"\n{exc}\n")
        raise SystemExit(1) from exc
    except ValidationError as exc:
        sys.stderr.write(f"\nError: {describe_validation_error(exc)}\n")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
