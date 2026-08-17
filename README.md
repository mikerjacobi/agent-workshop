# Agent Workshop

An agent is a folder: a written personality, some skills, and some tests.
This repo has one — `quake-watch`, which reports recent earthquakes near a
place — plus the `mothership` CLI to publish it, talk to it, and score it.

```bash
pip install -e cli
```

Then open [`workshop.ipynb`](workshop.ipynb) and run it top to bottom. It
publishes the agent, talks to it, scores it, changes one thing, and shows the
score move. Make the agent your own by editing its personality and skills, or
run the loop on it as it is.

```
agents/quake-watch/   the agent: personality, skills, evals
cli/                  the mothership CLI
skills/               the same steps, for anyone who'd rather ask Claude Code
workshop.ipynb        the walkthrough
```
