#!/usr/bin/env bash
# Shift a percentage of production traffic to the latest revision.
#
#   canary.sh 10    send 10% to the new revision
#   canary.sh 100   send everything to the new revision
#   canary.sh 0     send everything back to the previous revision (rollback)
#
# Rolling back is a traffic-weight change, not a redeploy, because both
# revisions are already running. That is the difference between a thirty-second
# rollback and a fifteen-minute one.
set -euo pipefail

WEIGHT="${1:?usage: canary.sh <percentage 0-100>}"
: "${RESOURCE_GROUP:?RESOURCE_GROUP is required}"
: "${CONTAINER_APP:?CONTAINER_APP is required}"

if ! [[ "$WEIGHT" =~ ^[0-9]+$ ]] || (( WEIGHT > 100 )); then
  echo "Weight must be an integer between 0 and 100, got '${WEIGHT}'" >&2
  exit 2
fi

mapfile -t REVISIONS < <(
  az containerapp revision list \
    --name "$CONTAINER_APP" \
    --resource-group "$RESOURCE_GROUP" \
    --query "sort_by([?properties.active], &properties.createdTime)[].name" \
    -o tsv
)

if (( ${#REVISIONS[@]} == 0 )); then
  echo "No active revisions found for ${CONTAINER_APP}" >&2
  exit 1
fi

# The workflow passes both names explicitly, so traffic always moves between
# the two revisions of THIS release and never onto an older one by accident.
# Without them, fall back to the two most recently created active revisions.
LATEST="${CANARY_REVISION:-${REVISIONS[-1]}}"

if [[ -z "${STABLE_REVISION:-}" ]] && (( ${#REVISIONS[@]} == 1 )); then
  echo "Only one active revision (${LATEST}); sending all traffic to it."
  az containerapp ingress traffic set \
    --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" \
    --revision-weight "${LATEST}=100"
  exit 0
fi

PREVIOUS="${STABLE_REVISION:-${REVISIONS[-2]}}"
REMAINDER=$(( 100 - WEIGHT ))

if [[ "$PREVIOUS" == "$LATEST" ]]; then
  echo "Stable and canary are the same revision (${LATEST}); nothing to split."
  exit 0
fi

echo "Previous revision : ${PREVIOUS}  -> ${REMAINDER}%"
echo "New revision      : ${LATEST}    -> ${WEIGHT}%"

az containerapp ingress traffic set \
  --name "$CONTAINER_APP" \
  --resource-group "$RESOURCE_GROUP" \
  --revision-weight "${PREVIOUS}=${REMAINDER}" "${LATEST}=${WEIGHT}"

if (( WEIGHT == 0 )); then
  echo "ROLLED BACK: all traffic is on ${PREVIOUS}."
fi

# Once a release is fully live, retire everything older than the revision it
# replaced. The previous revision stays active so rollback is still a traffic
# change, but revisions from several releases ago stop holding replicas (in
# production that is minReplicas each) and stop counting toward the app's
# revision limit.
if (( WEIGHT == 100 )); then
  for OLD in "${REVISIONS[@]}"; do
    [[ "$OLD" == "$LATEST" || "$OLD" == "$PREVIOUS" ]] && continue
    echo "Deactivating old revision ${OLD}"
    az containerapp revision deactivate \
      --name "$CONTAINER_APP" --resource-group "$RESOURCE_GROUP" --revision "$OLD" -o none
  done
fi
