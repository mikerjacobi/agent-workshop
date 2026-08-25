# Agent Workshop

A hands-on loop: publish an agent, talk to it, score it, improve it.

```bash
cd ~/agent-workshop
git pull --ff-only
pip install -e cli
```

On the workshop JupyterHub, pull first: the image was built from an older copy
of this repo. Then open [`workshop.ipynb`](workshop.ipynb) (close and reopen it
if it was already open) and run it top to bottom.

Before committing the notebook, run `python3 clean_notebook.py`: it strips
outputs and blanks the paste-in fields, so nobody's ids or results land in git. Everything
it uses is in this repo: the agent in `agents/quake-watch` (a personality,
skills, and evals), the `mothership` CLI in `cli/`, and `.claude/skills/` with the
same steps written for Claude Code.
