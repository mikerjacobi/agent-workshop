---
name: publish-agent
description: "Build an agent directory into an image and make it the live version in Mothership. Use when the user says publish, deploy, ship, or update an agent, or asks to make their agent changes take effect."
---

# Publish an agent

Run from the repo root. `<dir>` is a directory name under `agents/`.

```bash
mothership publish <dir> --slug <slug>
```

This builds the image, pushes it, registers the agent or promotes a new
version, and stops any running sandbox so the next message picks up the
change.

`--slug` defaults to the slug in `agents/<dir>/agent.json`. Slugs must be
unique, so on a shared deployment give each person their own, like
`jsmith-quake-watch`.

The image registry defaults to the workshop's. Override it with `--registry`
only if the user names a different one; never point the catalog at a local
image tag, which the deployment cannot pull.

Report the printed `agent_id` back to the user, because talking to the agent
needs it:

```bash
mothership messages submit "<question>" --agent-id <agent_id>
```

If the agent still behaves like the old version, a sandbox survived. Find it
with `mothership sandboxes search --state.eq RUNNING` and stop it.
