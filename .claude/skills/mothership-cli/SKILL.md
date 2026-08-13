---
name: mothership-cli
description: "Reference for the `mothership` CLI: profiles, talking to an agent, threads, sandboxes, the agent catalog, and evals. Use when a mothership command fails, when you need the exact flag for something, or when the user asks to inspect platform state directly rather than through the workshop scripts."
---

# The mothership CLI

Mothership is the agent control plane: a catalog of agents, a sandbox (a
containerized runtime) per user per agent, conversation threads, and the eval
system. `mothership` is the interface to all of it.

The `publish-agent` and `run-eval` skills wrap the common paths. Reach for
this one when something fails, or when you need to look at platform state
those scripts don't print.

## The CLI is authoritative

Before running anything unfamiliar, ask it:

```bash
mothership --help
mothership <resource> --help
mothership <resource> <action> --help
```

**If a command fails, re-run with `--help` rather than guessing another flag
or reaching for raw HTTP.** The flags are generated from pydantic models in
`cli/mothership-client/`, so `--help` and the wire contract cannot drift.

## Global flags go before the subcommand

| Flag | Effect |
|------|--------|
| `--json` | Raw JSON instead of tables. Use whenever you need to extract an id. |
| `--profile <name>` | Target a named profile for this invocation |
| `--external-id <id>` | Act as a different user |
| `--verbose` | Trace every HTTP call to stderr, bodies included |

```bash
mothership --json sandboxes search --state.eq RUNNING
mothership --verbose agents search
```

`--verbose` is the debugging tool. It prints method, URL, headers, and
pretty-printed request and response bodies, with the bearer token redacted.

## Profiles

Connection settings live at `~/.mothership/config.json`. At the workshop this
is pre-configured — check before assuming it isn't:

```bash
mothership profiles list
```

If you need to create one:

```bash
mothership profiles set workshop \
  --base-url <api-url> \
  --external-id <your-username> \
  --max-local-sandboxes 1
```

`MOTHERSHIP_BASE_URL` in the environment overrides the config file entirely,
which is the fastest way to point at a different deployment for one command.

## Talking to an agent

`messages submit` is the entry point. It ensures a sandbox is running, creates
a thread if needed, sends, and polls for the reply.

```bash
mothership messages submit "where is the ISS?" --agent-id <agent_id>
mothership messages submit "and how fast" --thread-id <thread_id>
```

| Flag | Use |
|------|-----|
| `--thread-id` | Continue a conversation instead of starting one |
| `--model` | Override the model for this run |
| `--sandbox-param KEY=VALUE` | Supply or override an agent parameter (repeatable) |
| `--force-sandbox-recreate` | Rebuild the sandbox first — use after re-pushing the same image tag |
| `--fire-and-forget` | Return the ids immediately, don't wait for the reply |
| `--timeout` | Poll timeout in seconds, default 300 |

The first message to an agent takes 30–90 seconds because the sandbox has to
start. Later messages are fast.

Read a conversation back:

```bash
mothership messages search --thread-id <thread_id>
mothership threads search --external-id <you> --limit 20
```

## Sandboxes

```bash
mothership sandboxes search --state.eq RUNNING
mothership sandboxes create <agent_id>
mothership sandboxes stop <sandbox_id>
```

States are `CREATED → STARTING → RUNNING → STOPPING → STOPPED`. Enum values in
filters are uppercase (`--state.eq RUNNING`).

> **Stop sandboxes with `mothership sandboxes stop`, never `docker rm -f`.**
> Killing the container orphans the sandbox row; the CLI tears down both.

## The agent catalog

```bash
mothership agents search
mothership agents search --slug.eq <slug>
mothership agents versions search <agent_id>
```

Two ids exist and mixing them up is the most common confusion here:

- **`slug`** — the human name you chose, e.g. `quake-watch`. Unique per org.
- **`agent_id`** — the generated surrogate, e.g. `agent_7f3a…`. This is what
  `sandboxes create`, `agents versions`, and `messages submit --agent-id`
  expect.

Resolve one to the other:

```bash
mothership --json agents search --slug.eq quake-watch | jq -r '.records[0].agent_id'
```

A **version** pins an image; the catalog row's `current_version` is what new
sandboxes boot. Promoting a version is the deploy:

```bash
mothership agents versions create <agent_id> --version <label> --image <uri> --set-current
```

Model, description, and parameters live on the catalog row, not the version:

```bash
mothership agents update <agent_id> --default-model <litellm/...>
mothership agents update <agent_id> --parameters '[{"key":"FOO","label":"Foo","secret":true}]'
```

## Search filter grammar

Every `search` shares one grammar: `--<field>.<operator> <value>`.

- Keyword fields: `.eq`, `.neq`, `.inc` (in list), `.ninc` (not in list)
- Free-text fields also take `.like`, `.nlike`
- Datetime fields: `.gte`, `.gt`, `.lte`, `.lt`, `.exists`
- Everywhere: `--limit`, `--offset`, `--sort-by`, `--sort-direction`

```bash
mothership sandboxes search --state.eq RUNNING --external-id.eq you --limit 10
mothership threads search --created-at.gte 2026-08-01T00:00:00Z --sort-direction DESC
```

## Evals

The eval commands take a JSON body validated server-side, rather than one flag
per field. The schema is `cli/mothership-client/src/mothership_client/models/eval_spec.py`.

```bash
mothership evals search --resource tasks --query '{"agent_id": {"eq": "<agent_id>"}}'
mothership evals create --resource tasks --body '<CreateEvalTaskInput json>'
mothership evals update --resource tasks --resource-id <task_id> --body '<patch json>'
mothership evals create --resource runs --body '{"agent_id": "<id>", "task_ids": [...], "executor": "platform"}'
mothership evals get --resource runs --resource-id <run_id>
mothership evals report --run-id <run_id> [--previous <run_id>]
```

`--resource` and `--resource-id` are flags, not positionals. Resources for
`search` are `tasks`, `templates`, `runs`, `results`.

`evals run-local` executes tasks under Harbor on your machine instead of the
platform. It needs the `local-runner` extra (`pip install -e
'cli/mothership-cli[local-runner]'`) and Harbor on your PATH. The workshop
uses the platform executor; you don't need this.

## Habits

1. **Know which deployment you're pointed at** before mutating anything —
   `mothership profiles list`.
2. **Use `--json` plus `jq` to extract ids** rather than reading them out of
   tables.
3. **Confirm before `sandboxes stop`, `agents delete`, `agents versions
   delete`** — they affect shared infrastructure.
4. **Reach for `--verbose` on the second failure**, not the fifth.
