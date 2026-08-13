# agents/

One directory per agent. Each is a complete agent: persona, skills, and the
evals that hold it to account.

```
agents/
├── Dockerfile            builds any agent dir into a runnable image (don't edit)
├── agent-pre-start.sh    seeds the workspace into the sandbox at boot (don't edit)
├── hello-world/          minimal agent — one skill, two evals
├── quake-watch/          richer example — two skills, two parameters, three evals
└── _template/            copy this to start your own
```

## What's in an agent directory

```
agents/my-agent/
├── SOUL.md               the persona: mission, audience, habits, refusals
├── agent.json            catalog metadata: slug, name, model, parameters
├── skills/
│   └── my-skill/
│       ├── SKILL.md      the procedure
│       ├── scripts/      optional — executables the skill invokes
│       └── references/   optional — detail loaded only when needed
└── evals/
    └── my-task.json      one file per eval task
```

`SOUL.md` and `skills/` are baked into the image and seeded into the running
sandbox. `agent.json` and `evals/` never reach the agent — the CLI consumes
them at publish and eval time.

There is no second prose file. Skills are discovered from the workspace, so
nothing has to list them; a skill's `description` frontmatter is what makes it
findable.

At build time `skills/` is renamed to `.claude/skills/`, which is where the
harness looks. You author at the path a person would look in.

## Start your own

```bash
cp -r agents/_template agents/my-agent
```

Edit `agent.json` (set `slug` first), write `SOUL.md`, rename the example
skill, and write at least one eval. Then follow
[`skills/publish-agent`](../skills/publish-agent/SKILL.md).

## Adding a skill

Skills are files. Start from the template, or copy one from another agent:

```bash
cp -r agents/_template/skills/example-skill agents/my-agent/skills/my-skill
cp -r agents/quake-watch/skills/geocode agents/my-agent/skills/geocode
```

The build dereferences symlinks (`cp -rL`), so if two agents should share a
skill, a relative symlink works and keeps one copy under source control.

These are the agent's own skills. The repo's top-level `skills/` is a
different thing — instructions for driving the dev loop, never shipped in an
image. See [`skills/README.md`](../skills/README.md).

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
name at the workshop (`jsmith-my-agent`) so you don't collide.

Parameters are env vars injected into every container in the sandbox. A
parameter with `"default": null` is **required**: the caller must supply a
value at sandbox-create time. `"secret": true` masks it in the admin UI. Your
skills read them as ordinary env vars.

> **TODO(workshop-staff):** confirm `default_model` matches a model alias the
> target deployment's LiteLLM proxy actually serves, and update every
> `agent.json` here plus the `publish-agent` skill if it differs. A wrong alias
> fails at sandbox create, which is a confusing first error for a participant.

> **TODO(workshop-staff):** if the target deployment fronts agents with the
> **bus** transport rather than the default **relay**, add `"transport": "BUS"`
> to each `agent.json`. `(openclaw, bus)` is the only implemented bus pair.
