# Agent Workshop

Publish an agent, talk to it, score it, change it, and see the score move.

```bash
git clone https://github.com/mikerjacobi/agent-workshop.git
cd agent-workshop
pip install -e cli
export MOTHERSHIP_IMAGE_REGISTRY=<ask workshop staff>
```

Then open [`workshop.ipynb`](workshop.ipynb) and run it top to bottom.

```
agents/quake-watch/   the agent: a persona, its skills, its evals
cli/                  the mothership CLI
skills/               the same steps, for anyone who'd rather ask Claude Code
workshop.ipynb        the walkthrough
```
