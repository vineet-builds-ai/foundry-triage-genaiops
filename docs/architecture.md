# Architecture, decisions and trade-offs

Written as a decision record. Each entry says what was chosen, what was given
up, and what would change the decision — which is the part most architecture
documents leave out.

---

## 1. Three Foundry projects, not one

**Decision.** Each environment gets its own Foundry resource and its own
project.

**Why.** A Foundry project is the access-control and evaluation boundary. One
shared project would put a developer iterating on a prompt and production
traffic inside the same boundary, which means a developer needs production
data-plane access to do their job, and evaluation history mixes experiments
with releases.

**Given up.** Three sets of resources to provision and three model quota
allocations instead of one. Higher baseline cost, more deployment surface.

**Would change if.** A client's quota is genuinely constrained and cannot be
raised. In that case the fallback is a shared Foundry resource with three
projects under it, which keeps the project-level boundary while sharing one
quota pool. It is a real weakening, because resource-scope role assignments
then span environments, and it should be recorded as an accepted risk rather
than quietly adopted.

---

## 2. The promotion artefact is a manifest, not a container image

**Decision.** `agent/agent.yaml` is what gets promoted. It pins the prompt
file, the model deployment, decoding parameters and the tool surface. The
release identifier embeds the prompt's SHA-256.

**Why.** For an agent, the thing that changes most often is the prompt, and
the thing that breaks most often is the prompt. A container tag does not tell
you which prompt is running. `ticket-triage-v3-7bcccbd59556` does, and it is
verifiable: re-hash the file and compare.

**Given up.** A second artefact to reason about alongside the image. The
manifest and the code can drift, which is why
`scripts/validate_manifest.py` cross-checks the prompt's declared output
contract against the code's schema on every pull request.

---

## 3. Routing policy is declared, not described

**Decision.** The prompt declares its policy in structured `RULE:` lines
rather than only in prose.

**Why.** Three benefits, and the third is the one that matters most:

1. A reviewer can diff a policy change and see exactly what moved.
2. The offline backend can execute the declared policy, so CI needs no model,
   no credentials and no budget.
3. A removed rule becomes a **visible absence** that a static check can catch,
   rather than a subtle behavioural drift nobody notices for a month.

**Given up.** Some expressiveness. A keyword-ordered rule list cannot capture
everything a well-written paragraph of instructions can, and a real model
given this prompt will generalise beyond the literal keywords. The rules are
a floor on behaviour, not a ceiling.

**Would change if.** The task stopped being classification. For open-ended
generation there is nothing to declare, and the gate would lean entirely on
LLM-judge and safety evaluators.

---

## 4. Deterministic evaluators first, judge models second

**Decision.** The gated metrics are all computed by code. LLM-judge evaluators
(`Relevance`, `Coherence`, `IntentResolution`, `TaskAdherence`) and the safety
evaluators (`ContentSafety`, `IndirectAttack`) layer on top when a project
endpoint is configured, and are reported rather than gated.

**Why.** A gate has to be defensible. "Your release was blocked because a
judge model scored it 3.8 out of 5 and the bar is 4.0" invites an argument
about the judge. "Your release was blocked because eight of eight security
tickets went to the wrong queue, here they are" does not. Deterministic
metrics are also reproducible: the same version scores the same number today
and in six months, so a threshold means something over time.

**Given up.** Coverage. Code cannot score whether a rationale reads sensibly.
That is exactly what the judge evaluators are good at, which is why they run
— just not as the thing that blocks.

**Would change if.** The product's quality were genuinely subjective. Then
judge metrics would have to gate, and the work shifts to validating the judge
against human labels before trusting it with a release decision.

---

## 5. Container Apps, not AKS

**Decision.** Container Apps, in multiple-revision mode.

**Why.** This is one stateless HTTP service that should scale to zero outside
production. A Kubernetes cluster adds a control plane, node image patching and
a platform bill for no benefit here. Multiple-revision mode gives the canary
and makes rollback a traffic-weight change rather than a redeploy — the
difference between a thirty-second rollback and a fifteen-minute one.

**Given up.** Scheduling control, sidecar patterns, and reuse of an existing
cluster's tooling.

**Would change if.** The client already runs AKS with established platform
tooling. Then this becomes a Deployment plus a service mesh traffic split, and
everything else in this repository is unchanged — the gate does not care what
runs the container.

---

## 6. Acceptance pins the same model version as production

**Decision.** `modelVersion` is identical in `acceptance.bicepparam` and
`prod.bicepparam`, with `versionUpgradeOption: NoAutoUpgrade`. A CI check
fails the build if they drift.

**Why.** Acceptance testing against a different model version than production
is not acceptance testing. Auto-upgrade means the model underneath a validated
agent can change without a release, which makes the acceptance result stale
without anyone touching the repository.

**Given up.** Automatic access to model improvements. Moving to a new version
is a reviewed parameter change that re-runs the gate — which is the intent.

---

## Where this deviates from the Microsoft baseline

Built on the [baseline Microsoft Foundry chat reference
architecture](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/architecture/baseline-openai-e2e-chat)
and the [AI Landing Zones](https://github.com/Azure/AI-Landing-Zones)
accelerator. Deviations, stated so a reviewer does not have to find them:

| Deviation | Reason |
| --- | --- |
| No Azure AI Search | Triage is classification over the ticket text. There is nothing to retrieve. Add it back for a RAG workload. |
| No API Management in front of Foundry | One consumer, one model. APIM earns its place with several consumers needing token budgets and quota isolation — the AI Gateway landing zone variant covers that. |
| Container Apps rather than App Service | See decision 5. |
| Single region | No cross-region requirement stated. Zone-redundant in production. Multi-region would mean a second Foundry resource, traffic management, and a decision about evaluation state. |
| Hand-written Bicep rather than the `avm/ptn/ai-ml/ai-foundry` AVM module | The module is excellent and would be the right call for a production engagement. Hand-written here so the resource shapes are legible rather than hidden behind module parameters — this repository is partly a teaching artefact. |

On naming: the platform is **Microsoft Foundry**, renamed from Azure AI
Foundry effective January 2026 (and Azure AI Studio before that). The ARM
resource type is unchanged — still `Microsoft.CognitiveServices/accounts` —
which is why older templates keep working.

---

## Known gaps

Stated plainly, because a client will find them anyway and it is better to
have named them first.

- **Never deployed.** Templates compile; nothing has been applied to a live
  subscription. First deployment will surface quota, naming and policy
  friction that no amount of compiling catches.
- **The golden set is synthetic.** 49 tickets written by hand. A real
  engagement starts by sampling production tickets and having the support team
  label them, which is a week of someone's time and the single highest-value
  thing to do first.
- **Thresholds are first-draft.** They sit just below a measured baseline on a
  synthetic set. Real thresholds come from arguing about consequences with the
  people who own the queues.
- **No drift detection on the dataset itself.** If ticket language shifts, the
  golden set silently stops representing production. Periodic re-sampling
  needs an owner.
- **Cost controls are structural, not enforced.** Quota is pinned per
  environment, but there is no budget alert or spend cap wired up.
