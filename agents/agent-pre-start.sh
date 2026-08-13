#!/bin/sh
# Harness init script for the mothership openclaw harness.
# Runs as an init container before the gateway starts. Seeds the
# workspace with the baked agent template from /etc/agent/.

PERSONA_ROOT="/etc/agent"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
WORKSPACE="$STATE_DIR/workspace"

# Copy the entire baked agent template onto the shared volume. The
# template is whatever the builder laid down under $PERSONA_ROOT —
# CLAUDE.md, USER.md, SOUL.md, and the .claude/skills the agent reads
# on demand. Copy it wholesale (dotfiles included, symlinks
# dereferenced) rather than cherry-picking known filenames, so a new
# top-level file in an agent directory reaches the workspace without a
# script change.
if [ -d "$PERSONA_ROOT" ]; then
  mkdir -p "$WORKSPACE"
  cp -RL "$PERSONA_ROOT"/. "$WORKSPACE"/
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
