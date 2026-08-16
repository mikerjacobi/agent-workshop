---
name: mothership-cli
description: "Reference for the mothership CLI: talking to an agent, reading threads and messages, inspecting sandboxes and the agent catalog. Use when a mothership command fails or when you need the exact flag for something."
---

# The mothership CLI

Mothership runs agents. It holds a catalog of them, starts a sandbox (a
container) per user per agent, and keeps the conversation threads.

`publish-agent` and `run-eval` cover the two long paths. This is everything
else.

## Ask it first

```bash
mothership <resource> --help
mothership <resource> <action> --help
```

The flags are generated from the models the API validates with, so help output
cannot be out of date. If a command fails, re-run it with `--help` rather than
guessing another flag.

## Global flags, before the subcommand

`--json` for machine-readable output, `--verbose` to print every HTTP request
and response with the token redacted, `--profile <name>` to target a different
deployment.

## Talking to an agent

```bash
mothership messages submit "where is the ISS?" --agent-id <agent_id>
mothership messages submit "and how fast" --thread-id <thread_id>
```

It starts a sandbox if needed, sends, and waits for the reply. The first
message also waits for the container to boot; later ones skip that. Add
`--force-sandbox-recreate` after re-pushing the same image tag.

Read a conversation back with `mothership messages search --thread-id <id>`,
or list them with `mothership threads search`.

## Sandboxes

```bash
mothership sandboxes search --state.eq RUNNING
mothership sandboxes stop <sandbox_id>
```

States are `CREATED`, `STARTING`, `RUNNING`, `STOPPING`, `STOPPED`, and filter
values are uppercase. Stop sandboxes through the CLI rather than killing the
container, which leaves the record behind.

## The catalog

```bash
mothership agents search
mothership agents search --slug.eq <slug>
```

Two ids, and mixing them up is the usual confusion. `slug` is the name a person
chose. `agent_id` is the generated one that sandboxes and messages want. To go
from one to the other:

```bash
mothership --json agents search --slug.eq <slug> | jq -r '.records[0].agent_id'
```

## Filters

Every search shares one grammar: `--<field>.<operator> <value>`. Keyword fields
take `.eq`, `.neq`, `.inc`, `.ninc`. Datetime fields take `.gte`, `.gt`,
`.lte`, `.lt`. Everything takes `--limit`, `--offset`, `--sort-by`, and
`--sort-direction`.
