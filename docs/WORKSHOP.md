# Workshop guide

Clone to a published, evaluated agent in under 20 minutes. Then make it
better and prove it.

Read [ARCHITECTURE.md](./ARCHITECTURE.md) first if you haven't — it is the
model this walkthrough assumes. Ten minutes, and it makes the rest obvious.

| Step | What you do | Minutes |
|------|-------------|---------|
| 0 | Set up | 3 |
| 1 | Publish the hello-world agent | 5 |
| 2 | Talk to it | 2 |
| 3 | Evaluate it | 5 |
| 4 | Change one thing and prove it moved | 5 |

Steps 1 and 3 are mostly waiting. Read ahead while they run.

---

## Step 0 — Set up

You need `git`, `docker` (running), `python3` 3.12 or newer, and `jq`.

```bash
git clone https://github.com/VulcanSkylight/agent-workshop.git
cd agent-workshop
pip install -e cli/mothership-client -e cli/mothership-cli
```

Use a virtualenv if you'd rather not install into your system Python:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e cli/mothership-client -e cli/mothership-cli
```

Confirm the CLI is there and pointed somewhere:

```bash
mothership --version
mothership profiles list
mothership agents search
```

`agents search` returning a table — even an empty one — means your
credentials and connection work. If it doesn't, stop here and ask; nothing
downstream will work.

Set the registry your images go to:

```bash
export MOTHERSHIP_IMAGE_REGISTRY=<value from the workshop staff>
```

> **TODO(workshop-staff):** replace the two placeholders above before the
> session — the `git clone` URL if the repo lands elsewhere, and the registry
> value. Also confirm participants arrive with `~/.mothership/config.json`
> already written and the registry credential already in their Docker config.
> Every minute of the 20 spent on auth is a minute not spent on the lifecycle.

---

## Step 1 — Publish the hello-world agent

Look at what you're about to ship. It is four files and no code:

```bash
ls -R agents/hello-world
```

| File | What it is |
|------|------------|
| `SOUL.md` | Mission, voice, and what it refuses |
| `USER.md` | Who it's talking to |
| `CLAUDE.md` | Where things are and which skills exist |
| `.claude/skills/iss-position/SKILL.md` | How to get the ISS's position, and what not to conclude from it |
| `agent.json` | Catalog metadata — never reaches the agent |

Give it a slug nobody else will take. Edit `agents/hello-world/agent.json` and
change `"slug"` to something like `"jsmith-hello-world"`.

Then publish:

```bash
./skills/workshop/publish-agent/publish.sh hello-world
```

Or, in Claude Code, just say: **"publish the hello-world agent"**.

This builds the image, pushes it, registers the agent, and mints version 1.
Three to five minutes, most of it the docker build.

It prints an `agent_id` like `agent_7f3a…`. Keep it — nearly every command
below wants it.

```bash
export AGENT=<the agent_id it printed>
```

While it builds, read `agents/hello-world/.claude/skills/iss-position/SKILL.md`.
Notice how much of it is about what the fields actually mean and what the data
does not support. That is the part that makes the agent trustworthy.

---

## Step 2 — Talk to it

```bash
mothership messages submit "Where is the ISS right now?" --agent-id $AGENT
```

First message takes 30–90 seconds — a sandbox has to start. It prints a
`thread_id`; pass `--thread-id` to keep the conversation going.

Now probe the boundary:

```bash
mothership messages submit "When does it next pass over Houston?" --agent-id $AGENT
```

It should decline. `SOUL.md` says pass predictions are out of scope, and the
skill says a single position sample cannot produce one. A general-purpose
model, asked the same thing with no persona, will give you a confident time.

That difference is the whole workshop. Everything else is how to make it
repeatable.

---

## Step 3 — Evaluate it

Two eval tasks ship with the agent. Look at them:

```bash
cat agents/hello-world/evals/iss-position.json
cat agents/hello-world/evals/stays-in-scope.json
```

The first checks that it uses live data and names a place. The second checks
the refusal you just saw by hand. Note that the refusal task's
highest-weighted criterion is a **binary** one: did it decline, yes or no.

Check them locally, then run:

```bash
python3 skills/workshop/author-eval/validate.py agents/hello-world/evals
./skills/workshop/run-eval/run.sh hello-world
```

Or say: **"run the evals for hello-world"**.

Each task gets its own fresh sandbox, so budget two to five minutes per task.
The script blocks and prints progress, then a scored report.

Note the `run_id`. You need it in the next step.

```bash
export BASELINE=<the run_id it printed>
```

Read the report before moving on. Which criterion scored lowest? Read its
reason — the judge explains itself, and it is usually right about what the
agent did.

---

## Step 4 — Change one thing and prove it

Now the loop closes.

Pick the weakest criterion and make one change aimed at it. Some options,
easiest first:

- **Scored low on `named_the_place`?** Strengthen that instruction in
  `SOUL.md`, or expand the "Name the place, don't just read coordinates"
  section of the skill.
- **Scored low on `concise_and_correct_units`?** `SOUL.md` says "be brief" —
  make it specific. A word budget scores better than an adjective.
- **Scored low on `used_live_data`?** The skill's "When it fails" section is
  where to push: make it explicit that a remembered position is always wrong.

Change **one** thing. Then:

```bash
./skills/workshop/publish-agent/publish.sh hello-world
./skills/workshop/run-eval/run.sh hello-world
mothership evals report --run-id <new_run_id> --previous $BASELINE
```

The last command prints Δ columns: what moved, and by how much.

Two things to be honest about when you read it:

- **A movement under about 0.1 on a single task is noise.** Both the agent and
  the judge are sampling. Look for consistent direction across criteria, not a
  decimal place.
- **If nothing moved, that is a real result.** The change you were sure would
  help did nothing measurable. Learning that in five minutes is exactly why
  the eval exists — without it you'd have shipped it and believed it worked.

---

## Then: build your own

```bash
cp -r agents/_template agents/my-agent
```

The template's comments walk you through each file. The order that works:

1. **`agent.json`** — set the slug first, so publishing can't surprise you.
2. **`SOUL.md`** — mission, capabilities, working habits, refusals. Spend most
   of your time here. Write the refusals before the capabilities; they are
   harder and they are what makes it an agent.
3. **`USER.md`** — one paragraph on who it serves.
4. **One skill.** Start with a public API and no auth. Copy
   `skills/library/http-json` as the starting shape.
5. **`CLAUDE.md`** — list the skill in the table. A skill the agent doesn't
   know about will never be invoked; this is the single most common bug.
6. **Two evals** — one that tests the job, one that tests the refusal.
7. Publish, talk to it, evaluate, iterate.

`agents/orbit-analyst/` is the worked version of exactly this: two skills, a
declared parameter, and two evals. Read it when you get stuck on shape.

In Claude Code you can stay in plain language the whole way — "write an eval
that checks it refuses to guess re-entry dates" loads the `author-eval` skill
and does it.

## If something breaks

[TROUBLESHOOTING.md](./TROUBLESHOOTING.md) covers the failures that actually
happen, in the order they happen.
