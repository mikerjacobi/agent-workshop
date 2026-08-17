# One agent image: the openclaw base plus the agent's files.
#
# `mothership publish` builds this from a temporary directory it stages, not
# from agents/. That staging copies the agent directory to workspace/ (minus
# agent.json and evals/, with skills/ moved to .claude/skills/) and places
# agent-pre-start.sh beside it. This file never changes per agent.
FROM --platform=linux/amd64 ghcr.io/vulcanskylight/mothership/openclaw-mothership:latest

USER root

# Skill scripts use pydantic; the base image ships neither python nor pip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages pydantic pydantic-settings

# The harness init container runs this to seed the workspace into the sandbox.
COPY agent-pre-start.sh /usr/local/bin/agent-pre-start.sh
COPY workspace/ /etc/agent/

USER node
