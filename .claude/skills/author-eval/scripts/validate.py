#!/usr/bin/env python3
"""Validate eval task files against the platform's own pydantic models.

The server rejects a bad spec with a 422 after a network round trip; this
catches the same errors locally, with the field path, before you run anything.

    python3 .claude/skills/author-eval/scripts/validate.py agents/hello-world/evals/*.json
    python3 .claude/skills/author-eval/scripts/validate.py agents/hello-world/evals

The models come from the vendored `mothership-client` package in `cli/` — the
exact classes the API validates with, not a copy of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from mothership_client.models.eval_spec import EvalTaskSpec
    from mothership_client.models.eval_task import CreateEvalTaskInput
except ImportError:
    sys.exit(
        "mothership-client is not installed. From the repo root:\n"
        "  pip install -e cli/mothership-client -e cli/mothership-cli"
    )
from pydantic import ValidationError

# agent_id is injected by run.sh at sync time, so files on disk don't carry one.
PLACEHOLDER_AGENT_ID = "agent_validate"


def _expand(args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.json")))
        else:
            paths.append(p)
    return paths


def _check(path: Path) -> list[str]:
    """Return a list of problems; empty means the file is good."""
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"not valid JSON: {e}"]

    if "agent_id" in doc:
        return ["remove 'agent_id' — it is injected at sync time from agent.json's slug"]

    try:
        CreateEvalTaskInput(agent_id=PLACEHOLDER_AGENT_ID, **doc)
    except ValidationError as e:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
    except TypeError as e:
        return [str(e)]

    return _lint(EvalTaskSpec.model_validate(doc["spec"]))


def _lint(spec: EvalTaskSpec) -> list[str]:
    """Warnings the schema allows but that make an eval less useful."""
    problems: list[str] = []
    for scorer in spec.scorers:
        if scorer.kind != "llm_judge":
            continue
        if not scorer.reference:
            problems.append(
                "warn: llm_judge has no 'reference' — the judge grades with no ground truth "
                "and scores will be noisy"
            )
        for criterion in scorer.criteria:
            if hasattr(criterion, "rubric") and len(criterion.rubric) < 60:
                problems.append(
                    f"warn: criterion '{criterion.name}' has a very short rubric — say what full "
                    "marks and zero look like, concretely"
                )
    return problems


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2

    failed = False
    for path in _expand(args):
        problems = _check(path)
        hard = [p for p in problems if not p.startswith("warn:")]
        if not problems:
            print(f"ok    {path}")
            continue
        print(f"{'FAIL' if hard else 'warn'}  {path}")
        for problem in problems:
            print(f"        {problem}")
        failed = failed or bool(hard)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
