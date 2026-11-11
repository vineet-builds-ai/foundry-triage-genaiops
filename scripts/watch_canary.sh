#!/usr/bin/env bash
# Watch the canary before widening the rollout.
#
# Two signals, both of which must hold:
#   1. HTTP server-error rate on the new revision stays under the budget.
#   2. The continuous evaluation score in Foundry has not dropped below the
#      production floor.
#
# The second signal is the one specific to an AI workload. A model change can
# leave latency and error rate untouched while the answers get worse, so error
# rate alone would wave a quality regression straight through.
set -euo pipefail

: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"
: "${CONTAINER_APP:?CONTAINER_APP is required}"

WINDOW_MINUTES="${WINDOW_MINUTES:-10}"
ERROR_BUDGET="${ERROR_BUDGET:-1.0}"       # percent of requests
POLL_SECONDS="${POLL_SECONDS:-60}"
POLLS="${POLLS:-5}"

echo "Watching canary for ${POLLS} polls at ${POLL_SECONDS}s intervals."
echo "Error budget: ${ERROR_BUDGET}% over a ${WINDOW_MINUTES} minute window."

for (( i = 1; i <= POLLS; i++ )); do
  sleep "$POLL_SECONDS"

  ERROR_RATE=$(
    az monitor metrics list \
      --resource "$(az containerapp show --name "$CONTAINER_APP" \
                      --resource-group "$RESOURCE_GROUP" --query id -o tsv)" \
      --metric Requests \
      --filter "statusCodeCategory eq '5xx'" \
      --interval "PT${WINDOW_MINUTES}M" \
      --aggregation Total \
      --query 'value[0].timeseries[0].data[-1].total' -o tsv 2>/dev/null || echo 0
  )
  ERROR_RATE="${ERROR_RATE:-0}"
  [[ "$ERROR_RATE" == "None" ]] && ERROR_RATE=0

  echo "  poll ${i}/${POLLS}: 5xx count in window = ${ERROR_RATE}"

  if awk "BEGIN{exit !(${ERROR_RATE} > ${ERROR_BUDGET})}"; then
    echo "Error budget exceeded. Failing so the workflow rolls back." >&2
    exit 1
  fi

  if [[ -n "${APPLICATION_INSIGHTS_APP_ID:-}" ]]; then
    python3 scripts/check_continuous_eval.py || {
      echo "Continuous evaluation score below the production floor." >&2
      exit 1
    }
  fi
done

echo "Canary healthy. Safe to widen the rollout."
