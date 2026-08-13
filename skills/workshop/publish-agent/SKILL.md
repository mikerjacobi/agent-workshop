---
name: publish-agent
description: "Build a workshop agent directory into an image and make it the live version in the Mothership catalog. Use when the user says publish, deploy, ship, or update an agent, or asks to make their agent changes take effect."
---

# Publish an agent

Turns `agents/<name>/` into a running agent. One command, idempotent — the
first run registers the agent, every run after that ships a new version and
promotes it.

## Do this

```bash
./skills/workshop/publish-agent/publish.sh <agent-dir-name>
```

Run it from the repo root. Report the printed `agent_id` back to the user —
they need it for every subsequent command.

## Before you run it

Check these; each one is a failure that costs the user a five-minute image
build to discover:

1. `agents/<name>/agent.json` exists and `slug` is not `CHANGE-ME`.
2. `slug` is prefixed to be unique in a shared deployment. If it isn't and the
   user is at a workshop, suggest prefixing it with their name.
3. `SOUL.md`, `CLAUDE.md`, and `USER.md` all exist.
4. Every skill named in `CLAUDE.md`'s table exists under
   `.claude/skills/<name>/SKILL.md`, and every skill directory is named in
   the table. A skill the agent doesn't know about will never be invoked.
5. Every env var the skills read is declared in `agent.json`'s `parameters`.
   Grep the skills for `$[A-Z_]` and compare.
6. `MOTHERSHIP_IMAGE_REGISTRY` is set in the environment.

## What it does

| Step | Why |
|------|-----|
| `docker build` with `--build-arg AGENT=<name>` | Bakes the workspace to `/etc/agent` in the image |
| `docker push` | The deployment's orchestrator pulls from the registry, not your laptop |
| `agents create` **or** `agents versions create --set-current` | Registers or promotes; the catalog row is what a sandbox binds to |
| `agents update --parameters …` | Parameters and model live on the catalog row, not the version, so they need a separate push |
| `sandboxes stop` on running sandboxes | A running sandbox holds the image it booted with and would otherwise serve the old agent |

The version label is a UTC timestamp unless `AGENT_VERSION` is set.

## After it succeeds

Offer to talk to it:

```bash
mothership messages submit "<a question the agent should handle>" --agent-id <agent_id>
```

The first message provisions a sandbox and takes 30–90 seconds. Later messages
in the same thread are fast. Pass `--thread-id` to continue a conversation.

## When it fails

**`no such agent directory`** — the argument is the directory name under
`agents/`, not the slug. They can differ.

**Build fails on `AGENT build arg is required`** — the script was run from
somewhere other than the repo root, or with no argument.

**`docker push` denied** — the user is not authenticated to the registry.
Do not work around this by pointing the catalog at a local image tag; a
local tag is unresolvable from the deployment and produces a sandbox that
fails to start with a much less obvious error. Tell them to authenticate.

**`agents create` rejects the slug** — either it collides with an existing
agent in the org (prefix it) or it isn't kebab-case.

**Sandbox starts but the agent behaves like the old version** — a stale
sandbox survived. Re-run with `mothership sandboxes search --state.eq running`
and stop it, or add `--force-sandbox-recreate` to the next `messages submit`.

**Sandbox never reaches `running`** — usually the image tag is unresolvable
from the deployment, or a required parameter (one with `"default": null`)
wasn't supplied at sandbox create. Check
`mothership --json sandboxes search --agent-id.eq <agent_id>` for the state
and error.
