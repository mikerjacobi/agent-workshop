#!/bin/sh
# Harness init script for the mothership openclaw harness.
# Runs as an init container before the gateway starts, and seeds the
# workspace the agent boots into.
#
# Two sources, in order:
#   1. WORKSPACE_URL (an agent parameter): a gs:// or https:// tarball,
#      fetched and unpacked. This is how published workspaces reach a
#      shared runtime image without a rebuild.
#   2. The template baked into the image at /etc/agent — the fallback,
#      and the whole story for images built the docker way.

PERSONA_ROOT="/etc/agent"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
WORKSPACE="$STATE_DIR/workspace"

mkdir -p "$WORKSPACE"

seed_baked() {
  # Copy the baked template wholesale (dotfiles included, symlinks
  # dereferenced) so a new top-level file in an agent directory reaches
  # the workspace without a script change.
  if [ -d "$PERSONA_ROOT" ]; then
    cp -RL "$PERSONA_ROOT"/. "$WORKSPACE"/
  fi
}

fetch_workspace() {
  # Anonymous first (public bucket), then with a token from the GKE metadata
  # server (private bucket readable by the cluster service account).
  URL=$(printf '%s' "$WORKSPACE_URL" | sed 's|^gs://|https://storage.googleapis.com/|')
  echo "seeding workspace from $URL"
  if curl -fsSL --retry 3 --max-time 60 "$URL" | tar -xz -C "$WORKSPACE"; then
    return 0
  fi
  TOKEN=$(curl -fsS -m 5 -H "Metadata-Flavor: Google"     "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"     | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
  [ -n "$TOKEN" ] || return 1
  curl -fsSL --retry 3 --max-time 60 -H "Authorization: Bearer $TOKEN" "$URL" | tar -xz -C "$WORKSPACE"
}

if [ -n "$WORKSPACE_URL" ]; then
  if fetch_workspace; then
    echo "workspace seeded from WORKSPACE_URL"
  else
    echo "WARN: workspace fetch failed; falling back to the baked template"
    seed_baked
  fi
else
  seed_baked
fi

# Install channel connector plugins onto the volume. Runs after the
# lifeline init's clean_home (init containers run in order), so the
# install survives. Plugins land in OPENCLAW_STATE_DIR/npm; point npm's
# cache at the volume to avoid a wrong-owner $HOME/.npm.
if [ -n "$OPENCLAW_CHANNEL_PLUGINS" ]; then
  export npm_config_cache="$STATE_DIR/.npmcache"
  for pkg in $OPENCLAW_CHANNEL_PLUGINS; do
    echo "installing channel plugin: $pkg"
    node /app/openclaw.mjs plugins install "$pkg" || echo "WARN: failed to install channel plugin $pkg"
  done
fi
