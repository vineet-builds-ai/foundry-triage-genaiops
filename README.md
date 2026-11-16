# Evaluation-gated promotion for an AI product on Azure

A support ticket triage agent that moves from **dev** to **acceptance** to
**production** on Microsoft Foundry, where the thing that decides whether it
moves is an **evaluation gate**, not a test suite.

The product is deliberately small. The promotion machinery around it is the
point.

---

## The sixty-second version

```bash
pip install -r requirements-dev.txt
make demo
```

No Azure account. No API keys. No network. Roughly twenty seconds.

Someone tidies the triage prompt — three edits, each individually reasonable:

- trim a field nobody downstream reads out of the output contract
- fold the security routing rule into the general rules, one less special case
- stop dumping unmatched tickets into `triage-review`

Every unit test still passes. The code is untouched. Then:

```
  metric                      bar       v3       v4   verdict
  ------------------------ ------ -------- --------   ------------------
  schema_validity            1.00    1.000    0.000   BREACHED
  critical_queue_recall      1.00    1.000    0.000   BREACHED
  routing_accuracy           0.85    0.939    0.653   BREACHED
  priority_accuracy          0.85    0.939    0.775   BREACHED

  8 security tickets were sent somewhere else:
    SEC-001  security-incident -> billing
    SEC-002  security-incident -> account-access
    SEC-003  security-incident -> technical-support
    ...
```

A customer reporting a phishing campaign gets routed to **billing**. The
pipeline exits non-zero and the version never reaches acceptance.

`demo/reference-transcript.txt` holds the full captured run.

---

## Why this is the interesting part

A traditional pipeline gates on tests: the code either works or it does not.
An AI product has a second failure mode that tests cannot see. The code is
fine, the service is up, latency is flat, every assertion passes — and the
answers quietly got worse.

So the release gate has to be driven by evaluation outcomes, and the unit of
promotion has to be the thing that actually changed. Here that unit is
`agent/agent.yaml`: a versioned manifest pinning the prompt, the model
deployment, the decoding parameters and the tool surface.

```
agent/agent.yaml          -> ticket-triage-v3-7bcccbd59556
                             ^^^^^^^^^^^^ ^^ ^^^^^^^^^^^^
                             agent        version  prompt sha256
```

That identifier is resolved once at the top of the pipeline and carried
through every environment. Nothing is rebuilt between acceptance and
production, so what production runs is bit-for-bit what acceptance approved,
and rolling back is a pointer change rather than a rebuild.

---

## What the gate actually checks

Four metrics, thresholds in version control under `evals/thresholds/`, each
with its rationale written next to the number so a reviewer can argue with the
reasoning rather than guess at it.

| Metric | Acceptance bar | Why |
| --- | --- | --- |
| `schema_validity` | 1.00 | A malformed decision breaks the downstream router. No environment tolerates it. |
| `critical_queue_recall` | 1.00 | Measured **only** over security tickets, so a miss cannot be averaged away by the other 41 rows. |
| `routing_accuracy` | 0.85 | Shipping version measures 0.939. The bar sits about four mis-routes below it. |
| `priority_accuracy` | 0.85 | Wrong priority changes response time rather than destination. |

The conditional metric is the one worth stealing. An overall accuracy average
hides exactly the failure you most care about: lose all eight security tickets
out of forty-nine and overall accuracy still reads 0.84. Gate the subset
separately and the same failure reads 0.00.

Scoring runs through the Microsoft Foundry evaluation SDK
(`azure-ai-evaluation`), so the same harness runs locally and as a cloud
evaluation against a project.

---

## From dev to production

Every change takes the same path, and each stage asks a harder question.
[docs/release-process.md](docs/release-process.md) describes every check and
the file that runs it.

```
pull request   unit + API tests, manifest check, gate (offline), container build + smoke, Bicep
     |
build once     image pushed and addressed by digest; every stage deploys these exact bytes
     |
dev            deploy -> smoke test (right version?) -> gate against the real model
     |
acceptance     business approval -> deploy -> smoke -> gate, worst of 3 runs -> latency/token budgets
     |
production     release approval -> new revision at 0% -> smoke it -> 10% canary -> watch errors
               and quality -> 100%, or automatic rollback to the previous revision
     |
after release  continuous evaluation, logs without ticket text, support corrections -> golden set
```

---

## Defence in depth

Three checks, deliberately ordered cheapest first.

| Check | Cost | Catches |
| --- | --- | --- |
| `scripts/validate_manifest.py` | milliseconds | Output contract drifted from the code schema, fallback policy removed, temperature off zero, a tool added to a classifier that should have none |
| Evaluation gate | seconds | What the change actually does to routing quality |
| Red team scan (`scripts/run_redteam.py`) | minutes, cloud | Adversarial inputs that talk the classifier out of its contract |

In the demo the static check already rejects the regression before any
evaluation runs. The gate still runs, because the number is what makes the
case: "this would have mis-routed every security ticket in the set" lands
differently from "a config check failed".

---

## The service

`src/triage/api.py` serves the agent over HTTP. The container image
(`Dockerfile`) bakes in the manifest and prompt, so the image is the release.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Liveness and readiness. No model call. |
| `GET /version` | The release id and prompt SHA-256 actually being served. Smoke tests compare it with the commit being promoted. |
| `POST /triage` | `{"ticket_id": "...", "text": "..."}` in, a validated decision out. |

If the model answers but breaks the output contract, the ticket is routed to
human triage and the response carries `X-Triage-Fallback`. If the model cannot
be reached, the API returns 503 so the failure shows in monitoring. Ticket
text is never logged.

```bash
pip install -r requirements-api.txt
PYTHONPATH=src uvicorn triage.api:app --port 8000
python scripts/smoke_test.py --url http://127.0.0.1:8000
```

---

## Running against real Azure

Everything above runs offline. To run against a live project:

```bash
pip install -r requirements-cloud.txt
export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
az login
make gate
```

The backend switches automatically. `LocalPolicyBackend` becomes
`FoundryBackend`, which sends the same prompt file verbatim to the model
deployment and authenticates with `DefaultAzureCredential` — no API keys, in
the repo or anywhere else.

> **On the offline backend, stated plainly.** `LocalPolicyBackend` is not a
> model and does not simulate one. It is a deterministic interpreter for the
> routing policy the prompt declares in its `RULE:` lines. That is what makes
> CI free, reproducible and credential-free, and it is why a removed rule
> shows up as a measurable behaviour change rather than a diff nobody reads.
> The evaluators, the output-contract check and the gate are identical either
> way; only the thing producing the rows changes.

---

## Infrastructure

Bicep, under `infra/`. Compiles clean with Bicep 0.49.2.

```bash
bicep build infra/main.bicep
bicep build-params infra/env/acceptance.bicepparam
```

Each environment is a **separate Foundry resource and project**, deployed into
its own application landing zone resource group. Per Microsoft's Cloud
Adoption Framework there is no separate "AI landing zone" — an AI workload is
a workload, so it goes into an application landing zone like anything else.

The virtual network, subnets and private DNS zones are **not** created here.
They are passed in by resource ID, because in a landing zone the platform team
owns them. The split is the point: this template deploys only what the
workload team is accountable for.

| Resource | Shape |
| --- | --- |
| Foundry resource | `Microsoft.CognitiveServices/accounts`, `kind: AIServices`, `allowProjectManagement: true` |
| Project | `accounts/projects` — the access-control and evaluation boundary |
| Model deployment | Version pinned per environment, `versionUpgradeOption: NoAutoUpgrade` |
| Hosting | Container Apps, multiple-revision mode for the canary |
| Observability | Log Analytics plus Application Insights, 30/90/365-day retention by environment |

Two properties worth pointing at in a review: `disableLocalAuth: true` on the
Foundry resource means no shared keys exist to leak, and
`publicNetworkAccess: Disabled` outside dev means the service is reachable
only through a private endpoint.

---

## Access control

`infra/modules/rbac.bicep` is the file a security reviewer should open first.

| Principal | Access | Where |
| --- | --- | --- |
| Developers (Entra group) | Foundry User — data plane | **Dev Foundry resource only.** No standing access to acceptance or production. |
| CI/CD identity | Foundry Project Manager on the project, Foundry User on the resource | Each environment; federated credential with no stored secret |
| Workload identity | Foundry User — data plane | Can call the model; cannot change deployments or projects |

Role **GUIDs** are used rather than names, because the Foundry roles were
renamed (Azure AI User became Foundry User and so on) while the IDs did not
change, and the display names are still rolling out across surfaces.

Who may approve a production release is configured under **Settings →
Environments**, not in the workflow file. A developer editing `cd.yml` cannot
grant themselves the right to release.

---

## Repository map

```
agent/
  agent.yaml                  The promotion artefact
  agent.regressed.yaml        The deliberate regression, for the demo
  prompts/                    Reviewable routing policy, with RULE: lines
src/triage/                   Agent, manifest loader, backends, output schema, HTTP API
Dockerfile                    The service image, built once and promoted by digest
evals/
  datasets/                   49 labelled tickets, including hard cases
  evaluators/                 Deterministic, code-based, no judge model
  thresholds/                 Per-environment bars, each with its rationale
  run_gate.py                 The gate
infra/                        Bicep: main, modules, per-environment params
scripts/                      Manifest validation, smoke and performance checks,
                              canary and its watch, red team, feedback harvesting
.github/workflows/            ci, cd, redteam
demo/                         One-command demo and a captured transcript
docs/                         Release process, architecture, governance, cost, demo script
```

---

## Verified

| | |
| --- | --- |
| Tests | 64 passing, including the HTTP API |
| Gate, shipping version, offline | Passes: routing 0.939, security recall 1.000 |
| Gate, regressed version, offline | Blocked, exit 1, on all four metrics |
| Gate, shipping version, **real model** (gpt-4o-mini in dev, 3 runs) | Passes the acceptance bar on every run: routing 0.959, security recall 1.000, priority 0.939 to 0.959 |
| Gate, regressed version, **real model** (2 runs) | Blocked: schema 0.000, security recall 0.875 on the worse run, priority 0.837 |
| Bicep | `main.bicep` and all three parameter files compile clean |
| Workflows | Parse and pass `actionlint` |
| Dev environment | Deployed to Azure (West Europe) by the pipeline. Live service passes the smoke test: right release id, real model, about 1 s and 573 tokens per ticket |
| Performance check, dev | Correctly fails under 4 concurrent callers: dev's 10K tokens-per-minute quota allows about 17 tickets a minute, so a quarter of requests were rate limited |

What the real model showed. It does not behave like the offline policy
interpreter: with the security rule deleted it still routed seven of eight
security tickets correctly, because it understands "phishing" without being
told. The regression is still blocked, mainly because dropping
`needs_human_review` breaks the output contract on every answer. And the two
runs disagreed: one missed SEC-002, the other caught all eight. A single run
could have passed it, which is why acceptance gates on the worst of several.

Not yet executed: acceptance and production deployments, which need
platform-owned private networking and a runner inside it.

---

## Further reading

- [docs/release-process.md](docs/release-process.md) — every stage from pull request to production, what it tests, and which file tests it
- [docs/setup.md](docs/setup.md) — getting from a fresh clone to a working pipeline, including the GitHub OIDC subject-claim change that breaks new repositories
- [docs/architecture.md](docs/architecture.md) — decisions and trade-offs, and where this deviates from the Microsoft baseline
- [docs/governance.md](docs/governance.md) — approvals, audit trail, data handling
- [docs/cost.md](docs/cost.md) — what this costs to run
- [docs/demo-script.md](docs/demo-script.md) — a timed walkthrough
