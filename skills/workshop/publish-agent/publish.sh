#!/usr/bin/env bash
# Build one agent directory into an image and make it the agent's current
# version in the Mothership catalog. Idempotent: first run registers the
# agent, later runs add a version and promote it.
#
#   ./publish.sh hello-world
#
# Requires: docker, jq, and the `mothership` CLI with a configured profile.
set -euo pipefail

AGENT="${1:-}"
if [[ -z "$AGENT" ]]; then
  echo "usage: publish.sh <agent-dir-name>   (e.g. publish.sh hello-world)" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
AGENT_DIR="$REPO_ROOT/agents/$AGENT"
MANIFEST="$AGENT_DIR/agent.json"

[[ -d "$AGENT_DIR" ]] || { echo "no such agent directory: agents/$AGENT" >&2; exit 1; }
[[ -f "$MANIFEST" ]]  || { echo "missing agents/$AGENT/agent.json" >&2; exit 1; }
for f in SOUL.md CLAUDE.md USER.md; do
  [[ -f "$AGENT_DIR/$f" ]] || { echo "missing agents/$AGENT/$f" >&2; exit 1; }
done

# TODO(workshop-staff): set a default registry for the workshop so participants
# don't have to. It must be a registry the target deployment's orchestrator can
# pull from — a local Docker daemon works only for a local deployment.
#   export MOTHERSHIP_IMAGE_REGISTRY=ghcr.io/<org>/agent-workshop
REGISTRY="${MOTHERSHIP_IMAGE_REGISTRY:-}"
if [[ -z "$REGISTRY" ]]; then
  cat >&2 <<'EOF'
MOTHERSHIP_IMAGE_REGISTRY is not set.

Set it to the registry prefix the deployment pulls from, then re-run:

  export MOTHERSHIP_IMAGE_REGISTRY=ghcr.io/<org>/agent-workshop

Ask the workshop staff for the value if you don't have it.
EOF
  exit 1
fi

SLUG=$(jq -r '.slug' "$MANIFEST")
NAME=$(jq -r '.name' "$MANIFEST")
DESCRIPTION=$(jq -r '.description // ""' "$MANIFEST")
HARNESS=$(jq -r '.harness // "openclaw"' "$MANIFEST")
TRANSPORT=$(jq -r '.transport // empty' "$MANIFEST")
MODEL=$(jq -r '.default_model // empty' "$MANIFEST")
PARAMETERS=$(jq -c '.parameters // []' "$MANIFEST")

if [[ "$SLUG" == "change-me" || "$SLUG" == "null" || -z "$SLUG" ]]; then
  echo "set a real 'slug' in agents/$AGENT/agent.json" >&2
  exit 1
fi

VERSION="${AGENT_VERSION:-$(date -u +%Y%m%d-%H%M%S)}"
IMAGE="$REGISTRY/$SLUG:$VERSION"

echo "▸ building $IMAGE from agents/$AGENT"
docker build \
  --build-arg "AGENT=$AGENT" \
  -t "$IMAGE" \
  -f "$REPO_ROOT/agents/Dockerfile" \
  "$REPO_ROOT/agents"

echo "▸ pushing $IMAGE"
docker push "$IMAGE"

echo "▸ resolving '$SLUG' in the catalog"
EXISTING=$(mothership --json agents search --slug.eq "$SLUG" | jq -r '.records[0].agent_id // empty')

if [[ -z "$EXISTING" ]]; then
  echo "▸ registering new agent '$SLUG'"
  EXTRA=()
  if [[ -n "$TRANSPORT" ]]; then EXTRA+=(--transport "$TRANSPORT"); fi
  if [[ -n "$MODEL" ]]; then EXTRA+=(--default-model "$MODEL"); fi
  # `agents create --parameters` is a list flag: an empty JSON array parses as
  # one bogus element, so omit it entirely when there are no parameters.
  if [[ "$PARAMETERS" != "[]" ]]; then EXTRA+=(--parameters "$PARAMETERS"); fi
  mothership agents create \
    --slug "$SLUG" \
    --name "$NAME" \
    --description "$DESCRIPTION" \
    --harness "$HARNESS" \
    --image "$IMAGE" \
    --version "$VERSION" \
    "${EXTRA[@]}"
  AGENT_ID=$(mothership --json agents search --slug.eq "$SLUG" | jq -r '.records[0].agent_id')
else
  AGENT_ID="$EXISTING"
  echo "▸ agent exists ($AGENT_ID) — adding version $VERSION and promoting it"
  mothership agents versions create "$AGENT_ID" \
    --version "$VERSION" \
    --image "$IMAGE" \
    --set-current
  # Parameters and model live on the catalog row, not the version, so a change
  # to agent.json has to be pushed separately.
  # Here --parameters is a plain JSON string flag, so "[]" is fine and means
  # "clear them" — unlike the list flag on `agents create` above.
  UPDATE=(--parameters "$PARAMETERS" --description "$DESCRIPTION" --name "$NAME")
  if [[ -n "$MODEL" ]]; then UPDATE+=(--default-model "$MODEL"); fi
  mothership agents update "$AGENT_ID" "${UPDATE[@]}" >/dev/null
fi

# A running sandbox holds the image it booted with. Stop it so the next
# message provisions a fresh one on the version we just promoted.
RUNNING=$(mothership --json sandboxes search --state.eq RUNNING --agent-id.eq "$AGENT_ID" \
  | jq -r '.records[].sandbox_id' || true)
for sb in $RUNNING; do
  echo "▸ stopping stale sandbox $sb"
  mothership sandboxes stop "$sb" >/dev/null
done

echo
echo "published: $SLUG"
echo "  agent_id: $AGENT_ID"
echo "  version:  $VERSION"
echo "  image:    $IMAGE"
echo
echo "talk to it:  mothership messages submit 'hello' --agent-id $AGENT_ID"
