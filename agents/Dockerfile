# Builds one agent workspace into a runnable harness image.
#
# The build context is this directory (`agents/`), so each top-level child
# is one agent's self-contained workspace. Nothing in here is agent-specific —
# you should never need to edit this file to ship your own agent.
#
#   cd agents
#   docker build --build-arg AGENT=hello-world -t hello-world:dev .
#
# The `publish-agent` skill runs this for you. See docs/ARCHITECTURE.md for
# what the layers mean.

# TODO(workshop-staff): pin BASE_IMAGE to a digest before the workshop so a
# floating upstream tag can't change what participants build. Confirm the tag
# below is readable from wherever participants build (it is public today).
ARG BASE_IMAGE=ghcr.io/vulcanskylight/mothership/openclaw-mothership:latest
ARG AGENT
ARG AGENT_TEMPLATE_DIR=/etc/agent
# Deploy target is amd64. Override with --platform=linux/arm64 for a local
# native build on Apple silicon (faster, but only runnable locally).
ARG DEPLOY_PLATFORM=linux/amd64

# ── Builder: stage the agent workspace ───────────────────────────────────
FROM --platform=$DEPLOY_PLATFORM $BASE_IMAGE AS builder

ARG AGENT
ARG AGENT_TEMPLATE_DIR

USER root

RUN test -n "$AGENT" || (echo "AGENT build arg is required: docker build --build-arg AGENT=<dir>" && exit 1)

COPY . /tmp/build/

# Stage the agent workspace, then reshape it for the runtime:
#   - agent.json and evals/ are CLI inputs, not agent content — they never ship.
#   - Skills are authored at `<agent>/skills/` because that is where a person
#     looks for them; the harness discovers them at `.claude/skills/`. The
#     rename happens here so no agent directory has to carry a dot directory.
RUN test -d "/tmp/build/${AGENT}" || (echo "agent '${AGENT}' not found under agents/" && exit 1) \
 && mkdir -p ${AGENT_TEMPLATE_DIR} \
 && cp -rL /tmp/build/${AGENT}/. ${AGENT_TEMPLATE_DIR}/ \
 && rm -rf ${AGENT_TEMPLATE_DIR}/agent.json ${AGENT_TEMPLATE_DIR}/evals \
 && if [ -d ${AGENT_TEMPLATE_DIR}/skills ]; then \
      mkdir -p ${AGENT_TEMPLATE_DIR}/.claude \
      && mv ${AGENT_TEMPLATE_DIR}/skills ${AGENT_TEMPLATE_DIR}/.claude/skills; \
    fi \
 && ls -A ${AGENT_TEMPLATE_DIR}

# ── Runtime: base + workspace, nothing else ──────────────────────────────
FROM --platform=$DEPLOY_PLATFORM $BASE_IMAGE AS base

ARG AGENT_TEMPLATE_DIR

USER root

# Skill scripts are Python and validate their inputs and their API responses
# with pydantic, so the runtime needs both. This layer sits above the agent
# workspace COPY on purpose: it caches, so only the first build pays for it and
# the edit-publish-evaluate loop stays fast.
#
# TODO(workshop-staff): fold this into a prebaked workshop base image so
# participants never pay the ~60s first build. Nothing here is agent-specific.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages pydantic pydantic-settings

COPY --from=builder ${AGENT_TEMPLATE_DIR} ${AGENT_TEMPLATE_DIR}
# The harness init container invokes this path by convention to seed the
# workspace onto the sandbox's shared volume.
COPY agent-pre-start.sh /usr/local/bin/agent-pre-start.sh
RUN chmod +x /usr/local/bin/agent-pre-start.sh
# mcporter registers MCP servers at runtime; skills that use MCP need it.
RUN npm install -g mcporter
USER node
