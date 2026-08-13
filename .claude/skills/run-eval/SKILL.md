---
name: run-eval
description: "Sync an agent's eval task files to the platform, run them, and print the scored report. Use when the user says run evals, score the agent, test the agent, or asks whether a change made the agent better."
---

# Run evals

Takes the JSON files in `agents/<name>/evals/` and turns them into a scored
run. Sync is idempotent: editing a rubric and re-running re-scores against the
new one under the same task, so the history stays comparable.

## Do this

```bash
python3 .claude/skills/run-eval/scripts/run.py <agent-dir-name>
python3 .claude/skills/run-eval/scripts/run.py <agent-dir-name> --tasks recent-activity refuses-prediction
```

Omit `--tasks` to run every file in the agent's `evals/`. The names are task
file names, with or without `.json`. `EVAL_TIMEOUT_SEC` and
`EVAL_POLL_INTERVAL_SEC` tune the wait; the defaults are 1800 and 10.

Run it from the repo root. The agent has to be published first — the run
executes against the agent's **current version**, so publish, then evaluate.

Validate the task files locally first; it costs nothing and saves a round trip:

```bash
python3 .claude/skills/author-eval/scripts/validate.py agents/<name>/evals
```

## What to expect

Each task provisions its own sandbox, sends the stimulus, waits for the
agent's full response, then runs the judge over it. Budget **2–5 minutes per
task**, running up to 4 at a time. The script prints progress and blocks until
the run reaches a terminal state.

The report is a markdown table: one row per task, the weighted score, and the
per-criterion breakdown.

## Reading the result

- **Score is a weighted mean of the non-gate scorers**, 0 to 1. A failed
  artifact gate zeroes the whole task and skips the judge, so a 0.0 with no
  criterion detail means a gate failed, not that the agent answered badly.
- **A criterion at 0 is the interesting row.** Read its `reason` — the judge
  explains itself, and it is usually right about what the agent did and
  sometimes wrong about whether that was bad.
- **Two runs of the same task will not score identically.** Both the agent and
  the judge are sampling. Treat a movement under ~0.1 on a single task as
  noise; look for consistent movement across tasks.

## Comparing before and after

This is the loop the workshop is teaching, so make it explicit for the user.
Note the `run_id` before a change, publish the change, run again, then:

```bash
mothership evals report --run-id <new_run_id> --previous <old_run_id>
```

That prints Δ columns. Without the comparison, a score is just a number.

## When a score is bad, diagnose before editing

Ask which of these it is, because the fix is different for each:

| Symptom | Fix |
|---------|-----|
| The agent didn't use a skill it should have | The skill's `description` frontmatter, or the skill table in `CLAUDE.md` |
| It used the skill but got the wrong answer from it | The skill body — usually a field it misread or a step it skipped |
| It answered something it shouldn't have | The refusals section in `SOUL.md` |
| It was right but scored low | The rubric or the `reference` — the judge didn't know what correct looked like |
| It failed a gate | Look at whether the agent produced a response at all; check the sandbox |

The last row is the one people get wrong. A low score is sometimes a bad eval,
not a bad agent. Read the judge's reasoning before editing the agent.

## When it fails

**`agent '<slug>' is not in the catalog`** — publish first.

**A task sits in `queued` forever** — the platform executor isn't claiming it.
Check that the agent's current version has a resolvable image, and that any
required parameter has a value.

**Every task fails with the same error** — look at one result in detail:

```bash
mothership evals search --resource results --query '{"run_id": {"eq": "<run_id>"}, "limit": 10}'
```

The `error` field on a result carries the executor's message, and `thread_id`
points at the conversation the agent actually had, which you can read with
`mothership messages search --thread-id <id>`.
