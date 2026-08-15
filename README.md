# Agent Workshop

Building purpose-built AI agents as products.

A general-purpose model is a capability. A product is a capability plus
decisions: what it is for, who it serves, what it may claim, what it must
refuse, and how you know it still works. This repo is a working example of
making those decisions and shipping them.

The claim it demonstrates: **general-purpose models become products through
engineering** — a mission and persona, domain-specific skills, and a
development loop that closes.

```
BUILD ──────► PUBLISH ──────► INTERACT ──────► EVALUATE ──────► ITERATE
edit markdown  image +         talk to it       score it         change one
in agents/     catalog                                           thing, repeat
```

This is not a CLI tutorial. The CLI is here so the loop can actually close.

## Start here

```bash
git clone https://github.com/mikerjacobi/agent-workshop.git
cd agent-workshop
pip install -e cli/mothership-client -e cli/mothership-cli
```

Then open **[`workshop.ipynb`](workshop.ipynb)** and run it top to bottom. It
walks the whole loop as `mothership` commands you can read — publish an agent,
talk to it, score it, change one thing, and prove the score moved.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first if you want the model
before the mechanics, and [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
when something breaks.

## Layout

```
agent-workshop/
├── docs/       architecture, the walkthrough, troubleshooting
├── cli/        the mothership CLI, vendored so this repo stands alone
├── agents/     one directory per agent — persona, its own skills, its evals
└── skills/     the Mothership interactions: publish, evaluate, author, debug
```

Skills appear in two places and the split is by **reader**: `skills/` is read
by you (or Claude Code) to drive the dev loop, `agents/<name>/skills/` is read
by the agent you built, running in a sandbox.

## What's in an agent

Markdown. No code.

```
agents/quake-watch/
├── SOUL.md                     mission, audience, habits, refusals
├── agent.json                  catalog metadata
├── skills/
│   ├── geocode/SKILL.md        place name to coordinates
│   └── usgs-quakes/            SKILL.md + scripts/ + references/
└── evals/                      three tasks that hold it to the above
```

[`quake-watch`](agents/quake-watch/) is the worked example the notebook uses.
Copy [`_template/`](agents/_template/) to start something of your own.

## The dev loop

Open the repo in Claude Code and ask in plain language, pointing it at the
matching skill in [`skills/`](skills/):

> publish my agent
> run its evals
> write an eval that checks it refuses to guess pass times

Each skill is a procedure over the `mothership` CLI — the exact commands, in
order, with what the failures mean. Read one and you can run the loop by hand;
there is no wrapper in between.

## Requirements

`git`, `docker`, `python3` ≥ 3.12, and access to a Mothership deployment.
Workshop participants arrive with credentials already configured.

The helper scripts are Python and take their dependencies from the vendored
CLI, so the `pip install` above is the whole setup. `jq` is optional — handy
for picking ids out of `mothership --json` by hand, not needed by anything
here.

## What's not here

No server code and no secrets — this repo is public. It talks to a Mothership
deployment over its REST API; the deployment itself lives elsewhere.

Places that need a local path or private infrastructure are marked
`TODO(workshop-staff)`:

```bash
grep -rn "TODO(workshop-staff)" .
```
