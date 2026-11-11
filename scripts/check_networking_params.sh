#!/usr/bin/env bash
# Private networking is mandatory outside dev.
#
# Enforced here rather than inside the template so the failure message names
# the parameter and the file, instead of surfacing as an opaque ARM error
# halfway through a deployment.
set -euo pipefail

fail=0

for env in acceptance prod; do
  file="infra/env/${env}.bicepparam"
  if ! grep -Eq '^param enablePrivateNetworking = true' "$file"; then
    echo "FAIL ${file}: enablePrivateNetworking must be true in ${env}"
    fail=1
  fi
  if ! grep -q 'privateEndpointSubnetId' "$file"; then
    echo "FAIL ${file}: ${env} must take a platform-owned privateEndpointSubnetId"
    fail=1
  fi
  if grep -Eq '^param developerGroupObjectId' "$file"; then
    echo "FAIL ${file}: ${env} must not grant standing developer data-plane access"
    fail=1
  fi
done

# Acceptance must test against the same model version as production.
acc=$(grep -E '^param modelVersion' infra/env/acceptance.bicepparam | sed "s/.*= *//" | tr -d "'\"")
prod=$(grep -E '^param modelVersion' infra/env/prod.bicepparam | sed "s/.*= *//" | tr -d "'\"")
if [[ "$acc" != "$prod" ]]; then
  echo "FAIL model version drift: acceptance=${acc} prod=${prod}"
  echo "     Acceptance testing against a different model version than production"
  echo "     is not acceptance testing."
  fail=1
fi

if [[ "$fail" -eq 0 ]]; then
  echo "Networking and model-pinning checks passed."
  echo "  acceptance and prod both pin model version ${acc}"
fi
exit "$fail"
