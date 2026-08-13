---
name: run-eval
description: "Sync an agent's eval task files to the platform, run them, and report the scores. Use when the user says run evals, score the agent, test the agent, or asks whether a change made the agent better."
---

# Run evals

Takes the JSON files in `agents/<name>/evals/` and turns them into a scored
run. Syncing is idempotent: a task whose slug already exists is updated in
place, so editing a rubric and re-running re-scores under the same task and
the history stays comparable.

The agent has to be published first — a run executes against its **current
version**. Publish, then evaluate.

Run these from the repo root.

## 1. Resolve the agent

Task files carry no `agent_id`; it comes from the manifest's slug.

```bash
AGENT=<agent-dir-name>
SLUG=$(jq -r .slug agents/$AGENT/agent.json)
AGENT_ID=$(mothership --json agents search --slug.eq $SLUG | jq -r '.records[0].agent_id // empty')
```

Empty means it isn't published yet. Stop and say so.

## 2. Sync each task file

For every file in `agents/$AGENT/evals/` (or just the ones the user named),
look it up by slug and either create or patch it:

```bash
TASK_SLUG=$(jq -r .slug agents/$AGENT/evals/<file>.json)
TASK_ID=$(mothership --json evals search --resource tasks \
            --query "$(jq -nc --arg s "$TASK_SLUG" '{slug:{eq:$s},limit:1}')" \
          | jq -r '.records[0].task_id // empty')
```

**Create** when empty — inject the agent, which is the one field the file omits:

```bash
mothership evals create --resource tasks \
  --body "$(jq -c --arg a "$AGENT_ID" '. + {agent_id: $a}' agents/$AGENT/evals/<file>.json)"
```

**Patch** otherwise. `agent_id` is immutable on a task, so send content only:

```bash
mothership evals update --resource tasks --resource-id $TASK_ID \
  --body "$(jq -c '{slug, description, tags, spec, enabled: true}' agents/$AGENT/evals/<file>.json)"
```

A 422 here means the spec doesn't validate. Read the error — it names the
field. The schema is `cli/mothership-client/src/mothership_client/models/eval_spec.py`,
and the `author-eval` skill covers the common causes.

Collect each `task_id` as you go.

## 3. Start the run

`platform` executor means the platform does the work; you only watch.

```bash
RUN_ID=$(mothership evals create --resource runs \
  --body "$(jq -nc --arg a "$AGENT_ID" --args '{agent_id:$a, executor:"platform", task_ids:$ARGS.positional}' \
            $TASK_IDS)" | jq -r '.records[0].run_id')
```

## 4. Poll until it finishes

```bash
mothership evals get --resource runs --resource-id $RUN_ID \
  | jq -r '.records[0] | "\(.status) \(.completed_count + .failed_count)/\(.task_count)"'
```

Each task provisions its own sandbox, sends the stimulus, waits for the full
response, then judges it. **Budget 2–5 minutes per task**, up to 4 at a time.
Check every 10–30 seconds; do not poll in a tight loop. Terminal statuses are
`completed`, `failed`, and `cancelled` — tell the user roughly how long it
will take and keep them posted rather than going silent.

## 5. Report

```bash
mothership evals report --run-id $RUN_ID
```

Give the user the `run_id` — they need it to compare against the next run.

## Reading the result

- **Score is a weighted mean of the non-gate scorers**, 0 to 1. A failed
  artifact gate zeroes the task and skips the judge, so a `0.0` with no
  criterion detail means a gate failed, not that the agent answered badly.
- **A criterion at 0 is the interesting row.** Read its reason — the judge
  explains itself, and it is usually right about what the agent did and
  sometimes wrong about whether that was bad.
- **Two runs of the same task will not score identically.** Both the agent and
  the judge sample. Treat movement under ~0.1 on a single task as noise; look
  for consistent direction across criteria.

## Comparing before and after

This is the loop the workshop teaches, so make it explicit. Note the `run_id`
before a change, publish, run again, then:

```bash
mothership evals report --run-id <new_run_id> --previous <old_run_id>
```

That prints Δ columns. Without the comparison a score is just a number.

## When a score is bad, diagnose before editing

| Symptom | Fix |
|---------|-----|
| Didn't use a skill it should have | The skill's `description` frontmatter — it is the routing decision |
| Used the skill but got the wrong answer from it | The skill body — usually a field it misread or a step it skipped |
| Answered something it shouldn't have | The refusals section in `SOUL.md` |
| Was right but scored low | The rubric or the `reference` — the judge didn't know what correct looked like |
| Failed a gate | Check whether the agent produced a response at all |

The fourth row is the one people get wrong: a low score is sometimes a bad
eval, not a bad agent. Read the judge's reasoning before editing the agent.

## When it fails

**A task sits in `queued` forever** — the platform executor isn't claiming it.
Check the agent's current version has a resolvable image and that any required
parameter has a value. Confirm the agent can hold a conversation at all with
`mothership messages submit` before debugging the eval.

**Every task fails with the same error** — look at one result in detail:

```bash
mothership evals search --resource results --query '{"run_id":{"eq":"<run_id>"},"limit":10}'
```

`error` carries the executor's message, and `thread_id` points at the
conversation the agent actually had. Read it with
`mothership messages search --thread-id <id>` — that answers most eval
mysteries.
