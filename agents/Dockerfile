# The shared runtime image every published agent boots from.
#
# It carries no agent of its own. `mothership publish` uploads the agent's
# workspace to the bucket and points that version's WORKSPACE_URL at the
# tarball, which agent-pre-start.sh fetches and unpacks at boot. Build and push
# it by hand when the base image or the deps below change:
#
#   docker build --platform linux/amd64 -t $MOTHERSHIP_RUNTIME_IMAGE agents/
FROM --platform=linux/amd64 us-west1-docker.pkg.dev/skylight-proto-1/workshop-images/openclaw-mothership-base:2026-08-18@sha256:9fdb2117e0cf353b6c9d432aaf028a653b72c3f6657e24d15401660e996968a8

USER root

# Skill scripts use pydantic; the base image ships neither python nor pip.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && pip3 install --no-cache-dir --break-system-packages pydantic pydantic-settings

# The harness init container runs this to seed the workspace into the sandbox.
COPY agent-pre-start.sh /usr/local/bin/agent-pre-start.sh

USER node
