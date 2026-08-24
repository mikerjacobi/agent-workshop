# Agent Workshop

A hands-on loop: publish an agent, talk to it, score it, improve it.

```bash
cd ~/agent-workshop
git pull --ff-only
pip install -e cli
```

On the workshop JupyterHub, pull first: the image was built from an older copy
of this repo. Then open [`workshop.ipynb`](workshop.ipynb) (close and reopen it
if it was already open) and run it top to bottom. Everything
it uses is in this repo: the agent in `agents/quake-watch` (a personality,
skills, and evals), the `mothership` CLI in `cli/`, and `skills/` with the
same steps written for Claude Code.
