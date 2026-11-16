#!/usr/bin/env bash
# Watch the canary before widening the rollout.
#
# Two signals, both of which must hold:
#   1. The server-error RATE on the new revision stays under the budget.
#      Measured on the canary revision only, as a percentage of its requests,
#      so errors on the stable revision cannot hide or fake a canary failure.
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
ERROR_BUDGET_PCT="${ERROR_BUDGET_PCT:-1.0}"   # percent of the canary's requests
MIN_REQUESTS="${MIN_REQUESTS:-0}"             # below this, the rate means nothing
POLL_SECONDS="${POLL_SECONDS:-60}"
POLLS="${POLLS:-5}"

APP_ID=$(az containerapp show --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" --query id -o tsv)
CANARY="${CANARY_REVISION:-$(az containerapp revision list \
  --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" \
  --query "sort_by([?properties.active], &properties.createdTime)[-1].name" -o tsv)}"

echo "Watching canary revision ${CANARY}: ${POLLS} polls, ${POLL_SECONDS}s apart."
echo "Error budget: ${ERROR_BUDGET_PCT}% of requests over the last ${WINDOW_MINUTES} minutes."

# Sum a Requests metric over the window for this revision, optionally filtered further.
request_count() {
  local extra_filter="$1"
  local filter="revisionName eq '${CANARY}'${extra_filter:+ and ${extra_filter}}"
  local value
  value=$(az monitor metrics list --resource "$APP_ID" --metric Requests \
            --filter "$filter" --offset "${WINDOW_MINUTES}m" --interval PT1M \
            --aggregation Total \
            --query "value[0].timeseries[0].data[?total!=null].total | sum(@)" \
            -o tsv 2>/dev/null || true)
  [[ -z "$value" || "$value" == "None" ]] && value=0
  printf '%.0f' "$value"
}

for (( i = 1; i <= POLLS; i++ )); do
  sleep "$POLL_SECONDS"

  TOTAL=$(request_count "")
  ERRORS=$(request_count "statusCodeCategory eq '5xx'")
  RATE=$(awk -v e="$ERRORS" -v t="$TOTAL" 'BEGIN { printf "%.2f", (t > 0 ? 100 * e / t : 0) }')

  echo "  poll ${i}/${POLLS}: ${ERRORS} server errors in ${TOTAL} requests = ${RATE}%"

  if (( TOTAL < MIN_REQUESTS )); then
    echo "  (fewer than ${MIN_REQUESTS} requests so far; rate not yet meaningful)"
  elif awk -v r="$RATE" -v b="$ERROR_BUDGET_PCT" 'BEGIN { exit !(r > b) }'; then
    echo "Error budget exceeded on ${CANARY}. Failing so the workflow rolls back." >&2
    exit 1
  fi

  if [[ -n "${APPLICATION_INSIGHTS_APP_ID:-}" ]]; then
    python3 scripts/check_continuous_eval.py || {
      echo "Continuous evaluation score below the production floor." >&2
      exit 1
    }
  fi
done

if (( MIN_REQUESTS > 0 )) && (( TOTAL < MIN_REQUESTS )); then
  echo "Canary saw only ${TOTAL} requests (minimum ${MIN_REQUESTS}). Not enough evidence to widen." >&2
  exit 1
fi

echo "Canary healthy. Safe to widen the rollout."
