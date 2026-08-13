# <Agent Name>

<!--
The persona, and the only prose file an agent needs. Skills are discovered
automatically, so this file is about judgment, not wiring.

This is the highest-leverage file in the agent and the one people most often
underfill. Two sentences of "you are a helpful assistant for X" produces a
general-purpose model with a costume on.

Write these four things. Delete these comments when you do.

1. The mission. One paragraph: what this agent is for, stated as a job
   someone needs done, not a topic area.
2. What it does well. Two or three concrete capabilities, each tied to a
   skill that backs it.
3. How it works. The habits that make its output trustworthy — what it
   cites, what it shows, what it says when it is unsure.
4. What it refuses. Name the adjacent thing it will NOT do, and why. This is
   what stops the agent from confidently improvising, and it is what your
   scope eval will test. Write it first; it is the hard part.
-->

You are ...

## What you do

- ...

## How you work

- ...

## What you don't do

- ...

<!--
Delete this section if your agent declares no parameters in agent.json.

## Configuration

These come from your environment, declared as parameters in `agent.json`.

| Env var | Default | What it is |
|---------|---------|------------|
| `<KEY>` | `<val>` | ...        |

Never print their values back to the user.
-->
