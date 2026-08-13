# agents/

One directory per agent. Each directory is a complete, self-contained agent:
persona, instructions, skills, and the evals that hold it to account.

```
agents/
├── Dockerfile            builds any agent dir into a runnable image (don't edit)
├── agent-pre-start.sh    seeds the workspace into the sandbox at boot (don't edit)
├── hello-world/          minimal agent — one skill, two evals
├── orbit-analyst/        richer example — two skills, a parameter, two evals
└── _template/            copy this to start your own
```

## What's in an agent directory

| File | What it is |
|------|------------|
| `SOUL.md` | The persona. Mission, capabilities, working habits, and refusals. |
| `CLAUDE.md` | Operating instructions: where things are, which skills exist, what env vars to read. |
| `USER.md` | Who the agent is helping, and what that implies about tone and depth. |
| `agent.json` | Catalog metadata: slug, display name, harness, model, declared parameters. |
| `.claude/skills/<name>/SKILL.md` | One skill. Loaded on demand, not held in context. |
| `evals/*.json` | Eval tasks. One file per task. |

`SOUL.md`, `CLAUDE.md`, `USER.md`, and `.claude/` are copied into the image and
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

## Reusing a skill

Skills are files. Copy one in:

```bash
cp -r skills/library/http-json agents/my-agent/.claude/skills/
```

The build dereferences symlinks (`cp -rL`), so a relative symlink works too if
you'd rather track the original.

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
name at the workshop (`jsmith-orbit-analyst`) so you don't collide.

Parameters are env vars injected into every container in the sandbox. A
parameter with `"default": null` is **required**: the caller must supply a
value at sandbox-create time. `"secret": true` masks it in the admin UI. Your
skills read them as ordinary env vars.

> **TODO(workshop-staff):** confirm `default_model` matches a model alias the
> target deployment's LiteLLM proxy actually serves, and update every
> `agent.json` here (`hello-world`, `orbit-analyst`, `_template`) plus the
> `publish-agent` skill's fallback if it differs. A wrong alias fails at
> sandbox create, which is a confusing first error for a participant.

> **TODO(workshop-staff):** if the target deployment fronts agents with the
> **bus** transport rather than the default **relay**, add `"transport": "BUS"`
> to each `agent.json`. `(openclaw, bus)` is the only implemented bus pair.
