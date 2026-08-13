"""Local Harbor runner: materialize → harbor → ingest.

The workspace-shaped escape hatch: author and review in
the platform, execute wherever Harbor runs. Platform-authored tasks
materialize via the export API; repo-authored tasks via a shallow git fetch
at the pinned ref (the resolved commit SHA is stamped on every ingested
result). Harbor itself is invoked as a subprocess on PATH — its agent flags
pass through verbatim, because the task's environment owns those choices.

Secrets never leave the platform: exported task.tomls carry ``${VAR}``
placeholders resolved from the local environment by Harbor itself.
"""

import io
import json
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from mothership_client.models.eval_task import EvalTask


class LocalRunError(Exception):
    pass


@dataclass
class MaterializedTasks:
    tasks_dir: Path
    # task slug → resolved commit SHA for repo-authored tasks.
    source_shas: dict[str, str]


@dataclass
class TrialOutcome:
    task_slug: str
    reward: float | None
    criteria: list[dict]
    error: str | None
    duration_seconds: float | None


def clone_at_ref(repo: str, ref: str, workdir: Path) -> tuple[Path, str]:
    """Shallow-fetch ``repo`` at ``ref``; returns (checkout dir, resolved SHA)."""
    url = repo if repo.startswith(("https://", "git@")) else f"https://{repo}"
    dest = workdir / repo.replace("/", "__")
    if not dest.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)], check=True, capture_output=True, text=True)
    sha = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    return dest, sha


def materialize(tasks: list[EvalTask], export_zip: bytes | None, workdir: Path) -> MaterializedTasks:
    """Lay out one Harbor task dir per task under ``workdir/tasks``."""
    tasks_dir = workdir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    source_shas: dict[str, str] = {}
    if export_zip:
        with zipfile.ZipFile(io.BytesIO(export_zip)) as archive:
            archive.extractall(tasks_dir)
    clones = workdir / "clones"
    clones.mkdir(exist_ok=True)
    for task in tasks:
        if task.source is None:
            continue
        checkout, sha = clone_at_ref(task.source.repo, task.source.ref, clones)
        source_dir = checkout / task.source.path
        if not (source_dir / "task.toml").exists():
            raise LocalRunError(f"{task.slug}: no task.toml at {task.source.path} in {task.source.repo}@{task.source.ref}")
        target = tasks_dir / task.slug
        if not target.exists():
            target.symlink_to(source_dir, target_is_directory=True)
        source_shas[task.slug] = sha
    return MaterializedTasks(tasks_dir=tasks_dir, source_shas=source_shas)


def run_harbor(tasks_dir: Path, jobs_dir: Path, harbor_args: list[str]) -> Path:
    """Invoke harbor on PATH; returns the job directory it produced."""
    before = {p.name for p in jobs_dir.iterdir()} if jobs_dir.exists() else set()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["harbor", "run", "-p", str(tasks_dir), "--jobs-dir", str(jobs_dir), *harbor_args]
    completed = subprocess.run(cmd)
    new_dirs = sorted(p for p in jobs_dir.iterdir() if p.is_dir() and p.name not in before)
    if not new_dirs:
        raise LocalRunError(f"harbor produced no job dir under {jobs_dir} (exit {completed.returncode})")
    return new_dirs[-1]


def parse_job_dir(job_dir: Path) -> list[TrialOutcome]:
    """Read per-trial results (task_name, verifier reward, timing) plus
    rewardkit's reward-details.json for criterion scores. Trial results parse
    through Harbor's own pinned models, so a layout change upstream fails
    loudly at the version bump instead of silently reading None."""
    # Deferred: harbor is an evaluator/CLI dependency, not an API one.
    from harbor.models.trial.paths import TrialPaths
    from harbor.models.trial.result import TrialResult

    outcomes = []
    result_name = TrialPaths(trial_dir=job_dir).result_path.name
    for trial_result in sorted(job_dir.glob(f"*/{result_name}")):
        paths = TrialPaths(trial_dir=trial_result.parent)
        trial = TrialResult.model_validate_json(trial_result.read_text())
        task_name = trial.task_name or trial_result.parent.name
        slug = task_name.rsplit("/", 1)[-1]
        rewards = (trial.verifier_result.rewards if trial.verifier_result else None) or {}
        reward = next(iter(rewards.values()), None)
        exception = trial.exception_info
        duration = None
        if trial.started_at and trial.finished_at:
            duration = (trial.finished_at - trial.started_at).total_seconds()
        criteria: list[dict] = []
        details_path = paths.verifier_dir / "reward-details.json"
        if details_path.exists():
            details = json.loads(details_path.read_text())
            for entry in details.values():
                for reward_detail in entry if isinstance(entry, list) else [entry]:
                    for c in reward_detail.get("criteria", []):
                        criteria.append({
                            "name": str(c.get("name", "criterion")),
                            "score": max(0.0, min(1.0, float(c.get("value", 0.0)))),
                            "weight": float(c.get("weight", 1.0)),
                            "reason": c.get("reasoning") or c.get("error"),
                        })
        outcomes.append(TrialOutcome(
            task_slug=slug,
            reward=float(reward) if reward is not None else None,
            criteria=criteria,
            error=f"{exception.exception_type}: {exception.exception_message}"[:2000] if exception else None,
            duration_seconds=duration,
        ))
    return outcomes


def default_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="mothership-evals-"))
