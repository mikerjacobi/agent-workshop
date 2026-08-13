# cli/

A vendored copy of the Mothership CLI and its wire-contract package, so this
repo installs and runs on its own.

```
cli/
├── mothership-client/   pydantic wire models + REST/WS client
└── mothership-cli/      the `mothership` command
```

## Install

```bash
pip install -e cli/mothership-client -e cli/mothership-cli
```

Order matters: the CLI depends on the client. One command installs both.

```bash
mothership --version
mothership --help
```

## Why it's vendored

`mothership-client` holds the pydantic models the **server validates with** —
not a client-side reimplementation of them. Two consequences worth knowing:

1. `mothership <resource> <action> --help` is generated from those models, so
   the help output cannot drift from the API.
2. You can validate a request locally before sending it. That's what
   `.claude/skills/author-eval/scripts/validate.py` does with eval specs.

When you want to know what fields something accepts, read the model, not a doc
page:

| Question | File |
|----------|------|
| What can an eval task contain? | `mothership-client/src/mothership_client/models/eval_spec.py` |
| What does an agent catalog entry hold? | `.../models/agent_catalog.py` |
| What states does a sandbox move through? | `.../models/sandbox.py` |
| What comes back from a run? | `.../models/eval_run.py` |

## Divergence from upstream

Upstream is `VulcanSkylight/mothership`, `packages/python/`. This copy is
identical except that `harbor` — the local eval runner's dependency — moved
from a required dependency to an optional extra, so the CLI installs without
access to it:

```bash
pip install -e 'cli/mothership-cli[local-runner]'   # only if you want `evals run-local`
```

Everything except `mothership evals run-local` works without it. The workshop
runs evals on the platform executor and does not need it.

> **TODO(workshop-staff):** this is a point-in-time copy of CLI `0.6.0`. If the
> upstream CLI changes before the session, re-vendor from
> `packages/python/{client,cli}` and re-apply the `harbor` extra. Confirm the
> version matches the deployment participants will be pointed at.

## Configuration

Connection settings live in `~/.mothership/config.json`, not in this repo.

```bash
mothership profiles list
mothership profiles set workshop --base-url <url> --external-id <you>
```

`MOTHERSHIP_BASE_URL` in the environment overrides the file entirely.
`MOTHERSHIP_API_KEY` carries a real credential when the deployment needs one;
it is read from the environment only and never written to disk by the CLI.

The `mothership-cli` skill (`.claude/skills/mothership-cli/SKILL.md`) is the
task-oriented reference for the command surface.
