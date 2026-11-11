# Setup runbook

Getting from a fresh clone to a working pipeline. Ordered so that each step is
verifiable before the next one depends on it.

Steps 1 and 2 need nothing but a GitHub repository. Step 3 onwards needs an
Azure subscription.

---

## 1. Verify the offline path first

Before touching Azure, confirm the repository works:

```bash
pip install -r requirements-dev.txt
make test          # 46 passing
make demo          # v3 passes, v4 is blocked
```

If that works, everything except the deployment is already proven on your
machine. Do this first — it isolates any later problem to the Azure side.

---

## 2. GitHub environments and protection rules

**The CD workflow references three environments. Until you create them, the
`environment:` keys are inert and production deploys with no approval.** This
is the single most important configuration step, and it is also the one the
client demo depends on.

**Settings → Environments**, create three: `dev`, `acceptance`, `production`.

| Environment | Required reviewers | Other |
| --- | --- | --- |
| `dev` | none | Deployment branches: `main` |
| `acceptance` | optional — one reviewer if the business wants sign-off | Deployment branches: `main` |
| `production` | **yes** — at least one, not the usual author | Enable **Prevent self-review**. Deployment branches: `main` |

Then **Settings → Branches → Add branch ruleset** for `main`:

- Require a pull request before merging
- Require status checks to pass, selecting: `Unit tests`,
  `Validate agent manifest`, `Evaluation gate (dev thresholds)`,
  `Validate infrastructure`
- Block force pushes

Until the status checks are *required*, the gate reports a failure but does
not stop a merge. The README's claim that the gate blocks a bad version is
only true once this is set.

> Verify: open a pull request that edits `agent/agent.yaml` to point at
> `prompts/system.v4-regressed.md`. CI should fail and the merge button should
> be blocked. That is also a good dry run of the demo.

---

## 3. Azure: identity for the pipeline

One app registration, with a federated credential per environment. No client
secret is created at any point.

```bash
# Create the app registration and its service principal.
APP_ID=$(az ad app create --display-name "github-triage-cicd" --query appId -o tsv)
az ad sp create --id "$APP_ID"
APP_OBJECT_ID=$(az ad app show --id "$APP_ID" --query id -o tsv)

echo "AZURE_CLIENT_ID    = $APP_ID"
echo "AZURE_TENANT_ID    = $(az account show --query tenantId -o tsv)"
echo "AZURE_SUBSCRIPTION_ID = $(az account show --query id -o tsv)"
echo "CICD_PRINCIPAL_ID  = $(az ad sp show --id "$APP_ID" --query id -o tsv)"
```

### The subject claim — read this before writing the credential

This is where setups created in late 2026 break, and the standard examples are
out of date.

GitHub changed the default OIDC subject format. <cite index="65-1">Repositories created after July 15, 2026 now use an immutable default subject format that includes both the owner ID and repository ID</cite>, with the syntax <cite index="65-1">`repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH`</cite>. <cite index="65-1">Repositories created before July 15, 2026 keep the previous format unless you opt in</cite>, and <cite index="65-1">repository renames and transfers after July 15, 2026 also move to the immutable format</cite>.

**This repository was created after that date, so it uses the immutable
format.** A credential written with the classic `repo:owner/repo:environment:x`
subject will never match, and the failure looks like a permissions problem
rather than a format problem.

Do not hand-assemble the string. Ask GitHub what it will actually send:

```bash
gh api /repos/vineet-builds-ai/foundry-triage-genaiops/actions/oidc/customization/sub
# -> { "use_default": true,
#      "use_immutable_subject": true,
#      "sub_claim_prefix": "repo:vineet-builds-ai@<owner-id>/foundry-triage-genaiops@<repo-id>" }
```

Take `sub_claim_prefix` verbatim and append `:environment:<name>`:

```bash
PREFIX=$(gh api /repos/vineet-builds-ai/foundry-triage-genaiops/actions/oidc/customization/sub \
           --jq .sub_claim_prefix)

for ENV in dev acceptance production; do
  az ad app federated-credential create --id "$APP_OBJECT_ID" --parameters "{
    \"name\": \"github-${ENV}\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"${PREFIX}:environment:${ENV}\",
    \"audiences\": [\"api://AzureADTokenExchange\"]
  }"
done
```

One credential per environment is deliberate: a workflow job running against
`dev` cannot obtain a token that Azure will accept for `production`, because
the subject will not match.

> Verify: `az ad app federated-credential list --id "$APP_OBJECT_ID" --query '[].subject'`
> and check the strings contain the `@<numeric-id>` segments.

---

## 4. Azure: resource groups and role assignments

One resource group per environment — these are the application landing zones.

```bash
LOCATION=westeurope
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

for ENV in dev acceptance prod; do
  RG="rg-tickettriage-${ENV}"
  az group create --name "$RG" --location "$LOCATION" \
    --tags workload=tickettriage environment="$ENV" costCentre=ai-platform

  # The pipeline needs to create resources and assign roles inside this group.
  # Scoped to the group, never the subscription.
  az role assignment create --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Contributor" \
    --scope "$(az group show --name "$RG" --query id -o tsv)"

  # Required because infra/modules/rbac.bicep creates role assignments.
  az role assignment create --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "User Access Administrator" \
    --scope "$(az group show --name "$RG" --query id -o tsv)"
done
```

`User Access Administrator` is a privileged role. It is needed because the
template assigns Foundry roles to the workload identity. Two alternatives if a
client's security team objects, and they will:

- A custom role limited to `Microsoft.Authorization/roleAssignments/write`
  scoped to the resource group.
- Move the role assignments out of Bicep and have a platform team apply them
  separately.

Record whichever you choose as an accepted decision rather than leaving it
implicit.

---

## 5. GitHub variables

**Settings → Secrets and variables → Actions → Variables.** All of these are
*variables*, not secrets — none is sensitive, which is the point of OIDC.

Set at repository level (shared across environments):

| Variable | Where it comes from |
| --- | --- |
| `AZURE_CLIENT_ID` | Step 3 |
| `AZURE_TENANT_ID` | Step 3 |
| `AZURE_SUBSCRIPTION_ID` | Step 3 |
| `CICD_PRINCIPAL_ID` | Step 3 |
| `FOUNDRY_MODEL_DEPLOYMENT` | `gpt-4o-mini` unless you changed it |

Set per environment, because the value differs:

| Variable | Needed by | Notes |
| --- | --- | --- |
| `AZURE_RESOURCE_GROUP` | all three | `rg-tickettriage-dev` and so on |
| `DEVELOPER_GROUP_OBJECT_ID` | `dev` only | Entra group of developers. Deliberately absent elsewhere. |
| `PRIVATE_ENDPOINT_SUBNET_ID` | acceptance, production | From the platform team |
| `CONTAINER_APPS_SUBNET_ID` | acceptance, production | From the platform team, delegated to Container Apps |
| `DNS_ZONE_COGNITIVESERVICES` | acceptance, production | Platform-owned private DNS zone |
| `DNS_ZONE_OPENAI` | acceptance, production | Platform-owned |
| `DNS_ZONE_AISERVICES` | acceptance, production | Platform-owned |
| `FOUNDRY_PROJECT_ENDPOINT_ACCEPTANCE` | acceptance | Known only after the first acceptance deployment — see step 6 |
| `PROD_CONTAINER_APP` | production | Container app name, after the first production deployment |
| `APPLICATION_INSIGHTS_APP_ID` | production | Optional. Enables the continuous-evaluation check in the canary watch. |

The last three are chicken-and-egg: the deployment produces them. Leave them
unset for the first run and fill them in afterwards from the deployment
outputs. The workflows tolerate empty values — the canary watch skips the
continuous-evaluation check when `APPLICATION_INSIGHTS_APP_ID` is absent.

---

## 6. First deployment

Dev first, by hand, so you see the errors directly rather than through a
workflow log:

```bash
az deployment group create \
  --resource-group rg-tickettriage-dev \
  --template-file infra/main.bicep \
  --parameters infra/env/dev.bicepparam \
  --name triage-dev-manual-001
```

Expect friction on the first run. The usual causes, in rough order of
likelihood:

| Symptom | Cause |
| --- | --- |
| Model deployment fails on capacity | No `gpt-4o-mini` quota in that region. Check **Quotas** in the Foundry portal and either raise it or change region. |
| `InvalidResourceName` on the Foundry account | Name collision — `customSubDomainName` must be globally unique. The template uses `uniqueString`, but a leftover soft-deleted account holds the name. Purge it. |
| Role assignment fails | Missing `User Access Administrator` from step 4. |
| Policy denies the deployment | A landing zone policy requires a tag or forbids public network access. Read the denial; it names the policy. |

Then capture the outputs:

```bash
az deployment group show \
  --resource-group rg-tickettriage-dev \
  --name triage-dev-manual-001 \
  --query properties.outputs
```

Put `foundryProjectEndpoint` into `FOUNDRY_PROJECT_ENDPOINT_ACCEPTANCE` once
you have run the same for acceptance.

### Run the gate against the real model

The moment worth checking carefully — this is the first time a real model, not
the offline interpreter, is scored:

```bash
pip install -r requirements-cloud.txt
az login
export FOUNDRY_PROJECT_ENDPOINT="<foundryProjectEndpoint from the outputs>"
make gate
```

**Expect the numbers to differ from the offline run**, and treat that as
information rather than a fault. A real model generalises past the literal
keywords in the prompt, so routing accuracy will usually be *higher* on the
security tickets and may be lower on the ambiguous ones, where the offline
interpreter abstains cleanly and a model is tempted to guess.

This is the point at which the thresholds in `evals/thresholds/` need
re-deriving against the real baseline. The committed values were set against
the offline interpreter and are a starting point, not an answer.

---

## 7. Then the pipeline

Push to `main` and let CD run. It will stop at the `acceptance` approval if
you configured a reviewer, and again at `production`.

Verify the things the demo claims:

- [ ] A pull request pointing the manifest at the regressed prompt fails CI and cannot be merged
- [ ] The gate report appears as a comment on that pull request
- [ ] Production deployment waits for an approval, and the approver cannot be the author
- [ ] The release record in the run summary names the release id and prompt SHA-256
- [ ] `scripts/canary.sh 0` returns traffic to the previous revision

---

## Teardown

```bash
for ENV in dev acceptance prod; do
  az group delete --name "rg-tickettriage-${ENV}" --yes --no-wait
done
az ad app delete --id "$APP_ID"
```

Foundry accounts soft-delete and continue to hold their name. Purge them if
you intend to redeploy with the same names:

```bash
az cognitiveservices account list-deleted
az cognitiveservices account purge --location "$LOCATION" \
  --resource-group "rg-tickettriage-dev" --name "<account-name>"
```
