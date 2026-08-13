# Architecture

How an agent, its skills, and its evals fit together — and why the shape is
what it is. Read this once before the hands-on walkthrough; it is the model
everything else assumes.

## The thesis

A general-purpose model is a capability. A product is a capability plus
decisions: what it is for, who it serves, what it may claim, what it must
refuse, and how you know it still works. This repo is about the second part.

Every general-purpose model can talk about satellites. Very few will tell you
they cannot compute a collision probability without covariance data, and then
tell you what would be needed instead. That behavior is not a better model.
It is engineering: a persona that declares the boundary, a skill that
documents what the data does and doesn't support, and an eval that fails the
agent when it improvises past either.

## The three parts

```
       ┌──────────────────────────────────────────────┐
       │                   AGENT                      │
       │                                              │
       │  SOUL.md    mission, voice, refusals         │
       │  USER.md    who it serves                    │
       │  CLAUDE.md  how it operates, what it has     │
       │                                              │
       │      ┌──────────────────────────────┐        │
       │      │          SKILLS              │        │
       │      │  procedures, loaded on demand│        │
       │      │  agents/<name>/skills/<skill>/│        │
       │      └──────────────────────────────┘        │
       └──────────────────────────────────────────────┘
                          ▲
                          │  measured by
                          │
       ┌──────────────────────────────────────────────┐
       │                   EVALS                      │
       │  a situation + what good looks like          │
       │  agents/<name>/evals/*.json                  │
       └──────────────────────────────────────────────┘
```

### The agent is judgment

Three Markdown files, no code.

`SOUL.md` is the mission and the boundary. This is the highest-leverage file
in the repo and the one people underfill. "You are a helpful assistant for
satellite operations" produces a general-purpose model wearing a costume.
What produces an agent is stating what it does, how it works, and — the part
that matters — what it refuses and why.

`USER.md` is who is on the other side. "A satellite operations analyst who
knows orbital mechanics better than you do" and "a member of the public" are
the same capability aimed at different people, and the mismatch is what makes
an agent feel wrong.

`CLAUDE.md` is the operating manual: where things are, which skills exist,
which env vars carry configuration. It is the only one of the three that is
mostly mechanical.

### Skills are procedure

A skill is `skills/<name>/SKILL.md`: frontmatter with a `name` and a
`description`, then a body.

The split matters. **The description is always in the agent's context. The
body is not.** The agent reads descriptions to decide what to load, then pulls
in the body on demand. So a skill can be three thousand words of endpoint
detail, field gotchas, and failure modes without costing anything until it is
needed — and the description has to be written as a routing decision, not a
summary.

That is why skills, rather than a longer system prompt, are the unit of
capability. Ten skills cost ten descriptions. Ten sections of a system prompt
cost all ten, every turn, forever.

A good skill body carries four things a system prompt rarely does:

- The exact calls, with real values, not placeholders.
- The response shape, annotated where the fields mislead — units, epochs,
  things named `altitude` that aren't what you'd assume.
- What you may derive from the data, with the formulas.
- **What you may not derive from it**, and what would be required instead.

The fourth is where purpose-built beats general-purpose. `celestrak-tle`
explains how to get from mean motion to orbital period, and in the same breath
that a single element set cannot give you the satellite's current position
without a propagator. A general model will happily do both.

### Evals are the feedback loop

An eval task is a **situation** and **what good looks like**:

```json
{
  "stimulus": { "kind": "prompt", "instruction": "Where is the ISS right now?" },
  "scorers": [
    { "kind": "artifact_gate", "checks": [...] },
    { "kind": "llm_judge", "reference": "ground truth", "criteria": [...] }
  ]
}
```

Scorers stack. An `artifact_gate` runs first and cheap — a failed gate zeroes
the score and skips the judge, so no LLM call is spent grading an empty
response. An `llm_judge` grades the response against weighted rubric criteria,
using the `reference` as ground truth.

Without evals, "I improved the persona" is an opinion. With them it is a
number that moved, and you can point at which criterion moved it.

### How the three connect

The relationship is a cycle, and each direction carries information:

- The **persona** declares what the agent is for. The **skills** give it the
  procedures to do that, and only that. An agent with skills its persona
  doesn't cover will drift into using them; a persona promising things no
  skill supports produces confident improvisation.
- The **evals** encode the persona as tests. A refusal stated in `SOUL.md` and
  never evaluated is a suggestion. The same refusal with a task whose
  highest-weighted criterion is "no probability figure appears" is a contract.
- The **eval results** point back at which part to change. A low score is a
  diagnosis, not a verdict — see the table in the `run-eval` skill.

## The lifecycle

```
   ┌──────────────────────────────────────────────────────┐
   │                                                      │
   ▼                                                      │
 BUILD ────────► PUBLISH ────────► INTERACT ────────► EVALUATE
 edit md         image + catalog   talk to it         score it
 agents/<name>/  version promoted  messages submit    run-eval
                                                          │
                                                          │
                                                    ITERATE
```

**Build.** Edit Markdown in `agents/<name>/`. No code, no build step yet.

**Publish.** The workspace is baked into a Docker image at `/etc/agent`, the
image is pushed to a registry, and a new **version** is registered in the
catalog and promoted to `current_version`. Promoting the version is the
deploy. `publish-agent` does all of it.

**Interact.** A **sandbox** is a container stack running one agent for one
user. `mothership messages submit` finds or creates one, sends your message,
and polls for the reply. First message: 30–90 seconds while the sandbox
starts. After that, fast.

**Evaluate.** A **run** executes a set of tasks against the agent's current
version. Each task gets its own fresh sandbox, so tasks don't contaminate each
other. Results carry per-criterion scores and the `thread_id` of the
conversation the agent actually had — which is the thing to read when a score
surprises you.

**Iterate.** Change one thing. Publish. Re-run. Compare with
`mothership evals report --run-id <new> --previous <old>`.

Change *one* thing. Two changes and a moved score is a coincidence, not a
finding.

## The platform underneath

You do not need this to complete the workshop, but it explains the vocabulary
in error messages.

```
 agent catalog row      slug, harness, model, declared parameters
        │               (what a sandbox binds to)
        ▼
 agent version          one Docker image, one label
        │               current_version is what new sandboxes boot
        ▼
 sandbox                container stack: harness + lifeline, one shared volume
        │               one per (user, agent, model)
        ▼
 thread                 a conversation; messages hang off it
```

**Harness** is the runtime inside the sandbox — `openclaw` here. The platform
doesn't care what's inside the image: it starts the container, mounts a shared
volume, and connects. At boot an init step copies `/etc/agent/` onto that
volume, which is why your Markdown reaches the running agent and why the agent
can write alongside it.

**Parameters** are the config contract. The catalog row declares keys, labels,
defaults, and a `secret` flag. At sandbox create, caller overrides merge over
the defaults; a parameter declared with `"default": null` is required and
missing it is a 400. The resolved values are injected as env vars into every
container in the stack and stamped onto the sandbox row — so a later catalog
edit does not change what a running sandbox sees. Your skills read them as
ordinary env vars. This is how the same image runs against staging and
production without a rebuild.

## Two ids

The one thing worth memorizing:

- **`slug`** — the human name you chose, `orbit-analyst`. Unique per org.
- **`agent_id`** — the generated surrogate, `agent_7f3a…`. What
  `sandboxes create`, `agents versions`, and `messages submit --agent-id` take.

```bash
mothership --json agents search --slug.eq orbit-analyst | jq -r '.records[0].agent_id'
```

## Why the CLI is vendored here

`cli/` holds a copy of `mothership-client` and `mothership-cli`. The client
package is the pydantic models the server validates with — not a
reimplementation of them. When you want to know what fields an eval task
accepts, `cli/mothership-client/src/mothership_client/models/eval_spec.py` is
the answer, and `mothership evals --help` is generated from the same models.
The docs can drift from the code; those two cannot.

It also means `.claude/skills/author-eval/scripts/validate.py` can check your eval
files locally against the real schema before anything goes over the wire.
