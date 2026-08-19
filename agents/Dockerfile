# One agent image: the openclaw base plus the agent's files.
#
# `mothership publish` builds this from a temporary directory it stages, not
# from agents/. That staging copies the agent directory to workspace/ (minus
# agent.json and evals/, with skills/ moved to .claude/skills/) and places
# agent-pre-start.sh beside it. This file never changes per agent.
FROM --platform=linux/amd64 us-west1-docker.pkg.dev/skylight-proto-1/workshop-images/openclaw-mothership-base:2026-08-18@sha256:9fdb2117e0cf353b6c9d432aaf028a653b72c3f6657e24d15401660e996968a8

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
