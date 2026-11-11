# Governance

What a security or compliance reviewer will ask, and where the answer lives.

---

## Who can release to production

| Question | Answer |
| --- | --- |
| Who approves? | Required reviewers on the `production` GitHub environment, configured under **Settings → Environments**. |
| Can a developer bypass it? | No. Approval is enforced by the platform, not by workflow YAML. Editing `cd.yml` does not change who may approve. |
| Can the approver also be the author? | Prevented by enabling **Prevent self-review** on the environment. |
| Is the approval recorded? | Yes — in the deployment history on the environment, and in the run's own release record (`github.actor`, the release id, the prompt SHA-256). |

## Who can reach what

See `infra/modules/rbac.bicep`.

| Principal | Role | Scope | Notes |
| --- | --- | --- | --- |
| Developer group | Foundry User | Dev project only | No standing access to acceptance or production. |
| CI/CD identity | Foundry Project Manager | Acceptance and production projects | Federated credential. No client secret exists. |
| Workload identity | Foundry User | Its own environment's project | Data plane only. Cannot alter deployments. |

Two deliberate absences: no human principal holds standing data-plane access
to acceptance or production, and no shared key exists anywhere —
`disableLocalAuth: true` on the Foundry resource means key-based auth is not
merely discouraged, it is unavailable.

Investigating a production problem is therefore an explicit, audited
elevation. That is a real operational cost, and it is the right trade.

### A note on role names

The Foundry roles were renamed: Azure AI User → Foundry User, Azure AI Project
Manager → Foundry Project Manager, and so on. **The role IDs did not change.**
This repository assigns by GUID, which is what Microsoft's own documentation
recommends while the display names roll out across surfaces.

Also worth knowing: despite the name, the **Azure AI Developer** role is
scoped to Azure Machine Learning workspaces and Foundry hubs, not to Foundry
projects. It is the wrong role for this architecture, and Microsoft's guidance
says so explicitly. Likewise the `Cognitive Services *` roles, except
`Cognitive Services Usages Reader` for quota visibility.

---

## No secrets

| | |
| --- | --- |
| Azure authentication | OIDC federated credentials via `azure/login@v2`. `permissions: id-token: write`. |
| Model authentication | `DefaultAzureCredential` — managed identity in Azure, developer sign-in locally. |
| API keys | None. `disableLocalAuth: true` means none can be used. |
| Secrets in the repository | None. Non-sensitive configuration uses GitHub **variables**, not secrets. |

There is nothing to rotate, which removes an entire class of operational task
and audit finding.

---

## Audit trail

For any production release, these can be reconstructed from the run:

- which agent version shipped (release id, including the prompt SHA-256)
- which prompt bytes were scored, verifiable by re-hashing the file
- the measured value of every gated metric, and the bar it was measured against
- every row that scored below full marks, with expected and actual routing
- who approved, and when
- the Bicep what-if output for the infrastructure change

Gate artefacts are retained for 30 days on CI runs and 90 days for red team
scans. Both are workflow settings, easily lengthened where retention policy
requires it.

Log retention follows the environment: 30 days in dev, 90 in acceptance, 365
in production — long enough that an incident half a year old can still be
reconstructed from agent traces and evaluation history.

---

## Data handling

| Environment | Classification | What is in it |
| --- | --- | --- |
| Dev | `synthetic-only` | The golden set. No customer data. |
| Acceptance | `production-like` | Shaped like production; sourced and minimised deliberately. |
| Production | `customer-data` | Real tickets. |

The tag is on every resource (`dataClassification`), so Azure Policy can
enforce rules against it rather than against a naming convention.

The golden set under `evals/datasets/` is synthetic and safe to commit. **A
real engagement must not commit sampled production tickets to source
control.** They belong in the project's own dataset storage, referenced by
the manifest, with access controlled like any other customer data. This is
the most common way a well-intentioned evaluation suite becomes a data
incident.

---

## Responsible AI

- `raiPolicyName: Microsoft.DefaultV2` on the model deployment — content
  filters are on by default, not opt-in.
- Safety evaluators (`ContentSafety`, `IndirectAttack`) run in cloud
  evaluation and are reported on every acceptance gate.
- The AI Red Teaming Agent runs weekly and before any prompt change, with
  findings logged to the project so the trend across releases is visible.
- `needs_human_review` exists so the agent can abstain. An agent that cannot
  say "I don't know" will guess, confidently, and the fallback policy is what
  makes abstention the default for unmatched tickets.
- The empty tool surface (`tools: []`) is a security property. The manifest
  validator fails the build if a tool is added, so expanding what this agent
  can *do* is a deliberate, reviewed act.

---

## Change control summary

| Change | What is required |
| --- | --- |
| Prompt edit | PR, static manifest check, dev gate, acceptance gate, production approval |
| Threshold change | PR. Visible in the diff, with its rationale, and reviewable like code. |
| Model version bump | Parameter change in **both** acceptance and prod, or CI fails on drift |
| New tool for the agent | Manifest validator fails by default. Requires an explicit decision to allow. |
| Infrastructure change | Bicep compile, what-if against acceptance, then the same approval chain |
| Rollback | Traffic-weight change to the previous revision. No rebuild. |
