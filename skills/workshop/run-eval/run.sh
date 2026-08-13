#!/usr/bin/env bash
# Sync an agent's eval task files to the platform, run them, and print the
# report. Idempotent: a task file that already exists as a task is updated in
# place, so re-running after editing a rubric re-scores against the new one.
#
#   ./run.sh hello-world                     # every task in agents/hello-world/evals/
#   ./run.sh hello-world iss-position        # just that file (extension optional)
#
# Requires: jq and the `mothership` CLI with a configured profile.
set -euo pipefail

AGENT="${1:-}"
if [[ -z "$AGENT" ]]; then
  echo "usage: run.sh <agent-dir-name> [task-file ...]" >&2
  exit 2
fi
shift || true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
AGENT_DIR="$REPO_ROOT/agents/$AGENT"
EVAL_DIR="$AGENT_DIR/evals"

[[ -f "$AGENT_DIR/agent.json" ]] || { echo "missing agents/$AGENT/agent.json" >&2; exit 1; }
[[ -d "$EVAL_DIR" ]] || { echo "no evals/ directory under agents/$AGENT" >&2; exit 1; }

SLUG=$(jq -r '.slug' "$AGENT_DIR/agent.json")
AGENT_ID=$(mothership --json agents search --slug.eq "$SLUG" | jq -r '.records[0].agent_id // empty')
if [[ -z "$AGENT_ID" ]]; then
  echo "agent '$SLUG' is not in the catalog — publish it first:" >&2
  echo "  ./skills/workshop/publish-agent/publish.sh $AGENT" >&2
  exit 1
fi
echo "▸ agent $SLUG ($AGENT_ID)"

# Which task files to sync.
FILES=()
if [[ $# -gt 0 ]]; then
  for arg in "$@"; do
    f="$EVAL_DIR/${arg%.json}.json"
    [[ -f "$f" ]] || { echo "no such eval file: $f" >&2; exit 1; }
    FILES+=("$f")
  done
else
  while IFS= read -r f; do FILES+=("$f"); done < <(find "$EVAL_DIR" -maxdepth 1 -name '*.json' | sort)
fi
[[ ${#FILES[@]} -gt 0 ]] || { echo "no eval task files under agents/$AGENT/evals/" >&2; exit 1; }

TASK_IDS=()
for f in "${FILES[@]}"; do
  TASK_SLUG=$(jq -r '.slug' "$f")
  EXISTING=$(mothership --json evals search --resource tasks \
    --query "$(jq -nc --arg s "$TASK_SLUG" '{slug: {eq: $s}, limit: 1}')" \
    | jq -r '.records[0].task_id // empty')

  if [[ -z "$EXISTING" ]]; then
    BODY=$(jq -c --arg aid "$AGENT_ID" '. + {agent_id: $aid}' "$f")
    TASK_ID=$(mothership evals create --resource tasks --body "$BODY" | jq -r '.records[0].task_id')
    echo "▸ created task $TASK_SLUG ($TASK_ID)"
  else
    TASK_ID="$EXISTING"
    # agent_id is immutable on a task; the update body carries content only.
    BODY=$(jq -c '{slug, description, tags, spec, enabled: true}' "$f")
    mothership evals update --resource tasks --resource-id "$TASK_ID" --body "$BODY" >/dev/null
    echo "▸ updated task $TASK_SLUG ($TASK_ID)"
  fi
  TASK_IDS+=("$TASK_ID")
done

RUN_BODY=$(jq -nc --arg aid "$AGENT_ID" --args '{agent_id: $aid, executor: "platform", task_ids: $ARGS.positional}' "${TASK_IDS[@]}")
RUN_ID=$(mothership evals create --resource runs --body "$RUN_BODY" | jq -r '.records[0].run_id')
echo "▸ run $RUN_ID over ${#TASK_IDS[@]} task(s)"

# Poll. Each task provisions its own sandbox, runs the agent, then judges the
# response — minutes, not seconds. The platform executor does the work; this
# loop only watches.
DEADLINE=$(( $(date +%s) + ${EVAL_TIMEOUT_SEC:-1800} ))
while :; do
  RUN=$(mothership evals get --resource runs --resource-id "$RUN_ID" | jq -r '.records[0]')
  STATUS=$(jq -r '.status' <<<"$RUN")
  DONE=$(jq -r '(.completed_count // 0) + (.failed_count // 0)' <<<"$RUN")
  TOTAL=$(jq -r '.task_count // 0' <<<"$RUN")
  printf '\r  %-12s %s/%s ' "$STATUS" "$DONE" "$TOTAL"
  case "$STATUS" in
    completed|failed|cancelled) echo; break ;;
  esac
  if (( $(date +%s) > DEADLINE )); then
    echo
    echo "timed out waiting for run $RUN_ID (still $STATUS)" >&2
    echo "it is still running server-side; check again with:" >&2
    echo "  mothership evals report --run-id $RUN_ID" >&2
    exit 1
  fi
  sleep 10
done

echo
mothership evals report --run-id "$RUN_ID"
echo
echo "run_id: $RUN_ID"
echo "compare against a previous run:"
echo "  mothership evals report --run-id $RUN_ID --previous <older_run_id>"
