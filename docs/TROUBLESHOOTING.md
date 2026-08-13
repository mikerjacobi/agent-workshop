# Troubleshooting

The failures that actually happen, in roughly the order they happen.

First move for anything CLI-shaped: re-run with `--verbose` before the
subcommand. It prints the request, the response, and the status code, with the
bearer token redacted.

```bash
mothership --verbose agents search
```

## Setup

**`mothership: command not found`**
The install didn't land in the Python you're using. Re-run
`pip install -e cli/mothership-client -e cli/mothership-cli` and check
`which mothership`. If you made a virtualenv, activate it.

**`No profile set` / `Profile 'x' not found`**
`~/.mothership/config.json` is missing or empty. `mothership profiles list`
shows what's there. At the workshop this is pre-configured — ask rather than
guessing at a base URL.

**`cannot reach mothership API at …`**
The base URL is wrong or the deployment is unreachable. Check
`mothership profiles list`, and check `MOTHERSHIP_BASE_URL` in your
environment — it silently overrides the config file.

**HTTP 401 or 403 on every command**
Your identity isn't accepted. `--external-id` asserts who you are; a real
deployment also wants `MOTHERSHIP_API_KEY` in the environment. Ask staff.

## Publishing

**`MOTHERSHIP_IMAGE_REGISTRY is not set`**
Export it. The value comes from workshop staff. A local image tag will not
work — the deployment pulls from a registry, not from your laptop.

**`no such agent directory: agents/<x>`**
The argument is the **directory name** under `agents/`, not the slug. They can
differ, and after you edit `agent.json` they usually do.

**`set a real 'slug' in agents/<x>/agent.json`**
You're publishing the template unedited. Copy it first:
`cp -r agents/_template agents/my-agent`.

**docker build fails immediately on the base image**
Either you can't reach the registry holding the base, or you're offline. The
base image tag is at the top of `agents/Dockerfile`.

**docker build is very slow on Apple silicon**
The Dockerfile targets `linux/amd64` because that's the deploy platform, so
you're emulating. That's correct and worth the wait — a native arm64 image
runs locally but won't run on the deployment.

**`docker push` denied**
You aren't authenticated to the registry. `docker login <registry>`. Do not
work around this by pointing the catalog at a local tag: the sandbox will fail
to start later with a much less obvious error.

**`agents create` rejects the slug**
Either it collides with an existing agent (prefix it with your name) or it
isn't kebab-case. Lowercase letters, digits, and hyphens only.

## Talking to the agent

**First message times out**
Sandbox startup can exceed the 300-second default when the image is cold.
Check the state directly:

```bash
mothership --json sandboxes search --agent-id.eq $AGENT
```

`STARTING` means be patient. `STOPPED` right after creation means it failed to
boot — usually an unresolvable image or a missing required parameter.

**Sandbox never leaves `CREATED` or `STARTING`**
Two usual causes: the image tag isn't resolvable from the deployment (check
it's the pushed URI, not a local tag), or a parameter declared with
`"default": null` wasn't supplied. Supply one with
`--sandbox-param KEY=VALUE`.

**The agent answers, but behaves like the old version**
A running sandbox holds the image it booted with. `publish.py` stops running
sandboxes for you, but if you registered a version some other way:

```bash
mothership sandboxes search --state.eq RUNNING
mothership sandboxes stop <sandbox_id>
```

Or force it on the next message with `--force-sandbox-recreate`.

**The agent ignores a skill you added**
Almost always one of these, in order of likelihood:

1. The `description` in the skill's frontmatter doesn't describe the situation
   the user is actually in. The description is the routing decision — rewrite
   it as "what this retrieves, and when to reach for it."
2. The skill directory isn't at `skills/<name>/SKILL.md`.
3. You edited it but didn't republish. Skills are baked into the image.

Verify what actually shipped:

```bash
docker run --rm $MOTHERSHIP_IMAGE_REGISTRY/<slug>:<version> ls -R /etc/agent
```

**The agent says it can't read an env var**
The parameter isn't declared in `agent.json`, or it's declared but has no
value. Parameters reach the container only if the catalog row declares them.
Check with `mothership --json agents search --slug.eq <slug> | jq '.records[0].parameters'`.

## Evals

**`agent '<slug>' is not in the catalog`**
Publish before evaluating. The run executes against the agent's current
version.

**A 422 on `evals create`**
The spec doesn't validate. The error names the field. Common causes: a `slug` that isn't kebab-case, an `agent_id` left in the file
(it's injected at sync time), or a scorers list containing only gates — at
least one non-gate scorer is required, since gates can only zero a reward.

**Tasks sit in `queued` and never run**
The platform executor isn't claiming them. Usually the agent's current version
has an unresolvable image, or a required parameter has no value. Confirm the
agent can hold a conversation at all with `mothership messages submit` before
debugging the eval.

**Every task scores 0.0 with no criterion detail**
An artifact gate failed, which zeroes the reward and skips the judge. Usually
the agent produced no response — check the result's `error` and `thread_id`:

```bash
mothership evals search --resource results --query '{"run_id": {"eq": "<run_id>"}, "limit": 10}'
mothership messages search --thread-id <thread_id>
```

Reading the conversation the agent actually had answers most eval mysteries.

**Scores move without a change**
Expected. Both the agent and the judge sample. Under about 0.1 on a single
task is noise. Look for consistent movement across criteria, and use
`--previous` so you're comparing rather than eyeballing.

**A criterion scores low but the answer looks right**
The judge may be correct and you may disagree with the rubric — that's a
finding about the eval, not the agent. Read the judge's reason. If it graded
against a standard you didn't intend, the fix is in `reference` or in the
rubric text, not in the agent.

## Still stuck

- `mothership <resource> <action> --help` is generated from the pydantic
  models, so it cannot be out of date.
- The wire contract is in `cli/mothership-client/src/mothership_client/models/`.
  For evals specifically, `eval_spec.py` is the authority on every field.
- In Claude Code: "why did that command fail?" loads the `mothership-cli`
  skill.
