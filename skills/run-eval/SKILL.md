---
name: run-eval
description: "Score an agent against the eval tasks in its directory and print the report. Use when the user says run evals, score the agent, test the agent, or asks whether a change made the agent better."
---

# Run evals

Run from the repo root. Publish first, because a run scores whichever version
is current.

```bash
mothership evals run <dir> --slug <slug>
```

This uploads each file in `agents/<dir>/evals/`, starts a run, waits for it,
and prints the report. Add `--task <name>` to run one file instead of all of
them. Each task gets its own sandbox, so runs are not instant.

To compare against an earlier run, pass its id:

```bash
mothership evals run <dir> --slug <slug> --previous <run_id>
```

## Reading the report

A score of `0.0` with no criterion detail means a gate failed, so the agent
probably returned nothing at all. Otherwise read the lowest criterion, because
the judge explains its reasoning.

Where the fix goes depends on what went wrong. If the agent did not use a skill
it should have, edit that skill's `description`. If it used the skill but
misread the data, edit the skill body. If it answered something it should have
refused, edit `SOUL.md`. If it was right but scored low, the rubric or the
reference is wrong rather than the agent.

Movement under about 0.1 on a single task is sampling noise, so look for
consistent direction across criteria instead.
