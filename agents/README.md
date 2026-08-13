# agents/

One directory per agent. Each directory is a complete, self-contained agent:
persona, instructions, skills, and the evals that hold it to account.

```
agents/
├── Dockerfile            builds any agent dir into a runnable image (don't edit)
├── agent-pre-start.sh    seeds the workspace into the sandbox at boot (don't edit)
├── hello-world/          minimal agent — one skill, two evals
├── quake-watch/          richer example — two skills, two parameters, three evals
└── _template/            copy this to start your own
```

## What's in an agent directory

| File | What it is |
|------|------------|
| `SOUL.md` | The persona. Mission, capabilities, working habits, and refusals. |
| `CLAUDE.md` | Operating instructions: where things are, which skills exist, what env vars to read. |
| `USER.md` | Who the agent is helping, and what that implies about tone and depth. |
| `agent.json` | Catalog metadata: slug, display name, harness, model, declared parameters. |
| `skills/<name>/` | One skill: `SKILL.md`, plus optional `scripts/` and `references/`. Loaded on demand, not held in context. |
| `evals/*.json` | Eval tasks. One file per task. |

A fuller agent directory looks like this:

```
agents/my-agent/
├── SOUL.md
├── CLAUDE.md
├── USER.md
├── agent.json
├── skills/
│   └── my-skill/
│       ├── SKILL.md          the procedure
│       ├── scripts/          executables the skill invokes
│       └── references/       detail loaded only when needed
└── evals/
    └── my-task.json
```

Put anything long and situational in `references/` and link to it from
`SKILL.md`. The agent pulls it in only when the situation calls for it, which
is the whole reason skills beat a longer system prompt.

At build time `skills/` is renamed to `.claude/skills/`, which is where the
harness discovers it. You author at the path a person would look in; the
Dockerfile handles the runtime convention.

`SOUL.md`, `CLAUDE.md`, `USER.md`, and `skills/` are copied into the image and
seeded into the running sandbox. `agent.json` and `evals/` never reach the
agent — they are consumed by the CLI at publish and eval time.

## Start your own

```bash
cp -r agents/_template agents/my-agent
```

Then edit `agent.json` (set `slug`), `SOUL.md`, `CLAUDE.md`, `USER.md`, rename
the example skill, and write at least one eval. The `publish-agent` skill
takes it from there:

```
> use publish-agent on my-agent
```

## Adding a skill

Skills are files. Start from the template, or copy one from another agent:

```bash
cp -r agents/_template/skills/example-skill agents/my-agent/skills/my-skill
cp -r agents/quake-watch/skills/geocode agents/my-agent/skills/geocode
```

Then add it to the table in your agent's `CLAUDE.md` — a skill the agent
doesn't know exists will never be invoked.

The build dereferences symlinks (`cp -rL`), so if two agents should share one
skill, a relative symlink works and keeps a single copy under source control.

These are the agent's own skills, not the ones in the repo's top-level
`skills/` — those are read by Claude Code to drive the dev loop and never
reach the image. See [`skills/README.md`](../skills/README.md).

## agent.json

```json
{
  "slug": "my-agent",
  "name": "My Agent",
  "description": "One sentence.",
  "harness": "openclaw",
  "default_model": "litellm/opus-4.6",
  "parameters": [
    {
      "key": "MY_API_KEY",
      "label": "My API key",
      "description": "What it authenticates.",
      "default": null,
      "secret": true
    }
  ]
}
```

`slug` must be kebab-case and unique in the deployment — prefix it with your
name at the workshop (`jsmith-quake-watch`) so you don't collide.

Parameters are env vars injected into every container in the sandbox. A
parameter with `"default": null` is **required**: the caller must supply a
value at sandbox-create time. `"secret": true` masks it in the admin UI. Your
skills read them as ordinary env vars.

> **TODO(workshop-staff):** confirm `default_model` matches a model alias the
> target deployment's LiteLLM proxy actually serves, and update every
> `agent.json` here (`hello-world`, `quake-watch`, `_template`) plus the
> `publish-agent` skill's fallback if it differs. A wrong alias fails at
> sandbox create, which is a confusing first error for a participant.

> **TODO(workshop-staff):** if the target deployment fronts agents with the
> **bus** transport rather than the default **relay**, add `"transport": "BUS"`
> to each `agent.json`. `(openclaw, bus)` is the only implemented bus pair.
