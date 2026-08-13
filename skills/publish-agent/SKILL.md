---
name: publish-agent
description: "Build a workshop agent directory into an image and make it the live version in the Mothership catalog. Use when the user says publish, deploy, ship, or update an agent, or asks to make their agent changes take effect."
---

# Publish an agent

Turns `agents/<name>/` into a running agent: build the image, push it, and
make it the agent's current version. Idempotent — the first run registers the
agent, every run after that mints a version and promotes it.

Run these from the repo root. `MOTHERSHIP_IMAGE_REGISTRY` must be set; if it
isn't, stop and tell the user to get the value from workshop staff. A local
image tag is unresolvable from the deployment and fails much later with a far
worse error, so never work around a missing registry.

## 1. Check before you build

Each of these costs a five-minute image build to discover otherwise:

- `agents/<name>/agent.json` exists and `slug` is not `change-me`.
- `slug` is unique in a shared deployment. If the user is at a workshop and it
  isn't prefixed, suggest their name (`jsmith-hello-world`).
- `SOUL.md` exists and is more than a sentence.
- Every skill directory has a `SKILL.md` with a `description` in its
  frontmatter — that description is what makes the skill discoverable.
- Every env var the skills read is declared in `agent.json`'s `parameters`.
  Grep the skills for `$[A-Z_]` and compare.
- `mothership profiles list` shows the deployment you expect.

Read the manifest:

```bash
AGENT=<agent-dir-name>
SLUG=$(jq -r .slug agents/$AGENT/agent.json)
VERSION=$(date -u +%Y%m%d-%H%M%S)
IMAGE="$MOTHERSHIP_IMAGE_REGISTRY/$SLUG:$VERSION"
```

## 2. Build and push

The build context is `agents/`, and `AGENT` is the **directory name**, which
can differ from the slug.

```bash
docker build --build-arg AGENT=$AGENT -t $IMAGE -f agents/Dockerfile agents/
docker push $IMAGE
```

Three to five minutes, most of it the build. The Dockerfile bakes the
workspace to `/etc/agent` and renames `skills/` to `.claude/skills/`, which is
where the harness discovers it.

## 3. Register or promote

Resolve the slug to the surrogate `agent_id` — versions and sandboxes take the
surrogate, never the slug:

```bash
AGENT_ID=$(mothership --json agents search --slug.eq $SLUG | jq -r '.records[0].agent_id // empty')
```

**Empty — first publish.** Creating the catalog row mints its first version:

```bash
mothership agents create \
  --slug $SLUG \
  --name "$(jq -r .name agents/$AGENT/agent.json)" \
  --description "$(jq -r '.description // ""' agents/$AGENT/agent.json)" \
  --harness "$(jq -r '.harness // "openclaw"' agents/$AGENT/agent.json)" \
  --default-model "$(jq -r .default_model agents/$AGENT/agent.json)" \
  --image $IMAGE \
  --version $VERSION \
  --parameters "$(jq -c .parameters agents/$AGENT/agent.json)"
```

> **Omit `--parameters` entirely when the array is empty.** It is a list flag,
> so `--parameters '[]'` parses as one bogus element and the command fails
> with "Input should be a valid dictionary". Drop `--default-model` too if the
> manifest has none.

Then re-read `AGENT_ID` with the same search — you need it for step 4.

**Non-empty — later publishes.** Mint the version and promote it:

```bash
mothership agents versions create $AGENT_ID --version $VERSION --image $IMAGE --set-current
```

Name, description, model, and parameters live on the **catalog row**, not the
version, so a manifest edit needs its own call. Here `--parameters` is a plain
JSON string flag, so `'[]'` is fine and means "clear them":

```bash
mothership agents update $AGENT_ID \
  --name "$(jq -r .name agents/$AGENT/agent.json)" \
  --description "$(jq -r '.description // ""' agents/$AGENT/agent.json)" \
  --parameters "$(jq -c .parameters agents/$AGENT/agent.json)"
```

## 4. Recycle running sandboxes

A running sandbox holds the image it booted with, so it keeps serving the old
agent. Stop it and the next message reprovisions on the new version:

```bash
mothership --json sandboxes search --state.eq RUNNING --agent-id.eq $AGENT_ID \
  | jq -r '.records[].sandbox_id' \
  | xargs -r -n1 mothership sandboxes stop
```

Enum filters are uppercase: `--state.eq RUNNING`, not `running`.

## 5. Report back

Give the user the `agent_id`, the version, and the image — they need the
`agent_id` for every subsequent command. Then offer to talk to it:

```bash
mothership messages submit "<a question the agent should handle>" --agent-id $AGENT_ID
```

The first message takes 30–90 seconds while the sandbox starts.

## When it fails

**`docker push` denied** — not authenticated to the registry. Tell them to
`docker login`. Do not point the catalog at a local tag instead.

**`agents create` rejects the slug** — it collides with an existing agent
(prefix it) or isn't kebab-case.

**`--parameters` errors with "Input should be a valid dictionary"** — the
empty-array trap above.

**Agent behaves like the old version** — a stale sandbox survived. Re-run
step 4, or add `--force-sandbox-recreate` to the next `messages submit`.

**Sandbox never reaches `RUNNING`** — usually an image the deployment can't
pull, or a parameter declared with `"default": null` and never supplied.
Check `mothership --json sandboxes search --agent-id.eq $AGENT_ID` for the
state, and see [TROUBLESHOOTING.md](../../docs/TROUBLESHOOTING.md).

If a `mothership` command fails, re-run it with `--help` rather than guessing
another flag — the help is generated from the models the API validates with.
