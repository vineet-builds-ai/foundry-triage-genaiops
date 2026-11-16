# Release process: dev to acceptance to production

How a change to this agent reaches customers, what is tested at each stage,
and which file does the testing. Each stage asks a harder question than the
last, with more realistic conditions and more people involved.

| Stage | Question | Who decides |
| --- | --- | --- |
| Pull request | Did this change make anything worse? | Automated checks, then a code reviewer |
| Dev | Does it deploy, and does the real model still clear the floor? | Automated |
| Acceptance | Is it good, fast and cheap enough, and does the business accept it? | Automated, then a business approver |
| Production | Is it safe for real customers? | A release approver, then the canary |
| After release | Is it still good next month? | Monitoring, and the support team's corrections |

---

## What makes an AI release different

For ordinary software the release question is "does the code still work?" and
tests answer it. An AI product can get worse with no code change at all: an
edited prompt, a model version that moved underneath it, a shift in how
customers write. So three extra things are true here.

1. **The release unit is everything that shapes behaviour.** `agent/agent.yaml`
   pins the prompt, model deployment, decoding parameters and tool surface.
   The container image bakes that manifest in, and the image is built once and
   promoted by digest.
2. **Behaviour is measured, not just code.** The evaluation gate scores the
   agent on a labelled golden set at every stage, against bars that tighten
   towards production.
3. **The model is not perfectly repeatable.** Acceptance scores several runs
   and gates on the worst one.

---

## 1. Pull request (CI)

`.github/workflows/ci.yml`. Runs on every pull request. Needs no Azure, costs
nothing, and all five checks must pass before `main` accepts a merge.

| Check | What it proves | File |
| --- | --- | --- |
| Unit tests | Parsing, schema, evaluators, the agent, and the HTTP API behave as specified, including fail-safe on a malformed model answer and 503 on a model outage | `tests/` |
| Validate agent manifest | Prompt contract matches the code schema, fallback policy present, temperature 0, no tools added | `scripts/validate_manifest.py` |
| Evaluation gate (dev thresholds) | The routing policy still clears the dev bar on the golden set. The report is posted on the pull request | `evals/run_gate.py` |
| Build and smoke-test container | The image builds, starts, contains the prompt, and serves this commit's release id | `Dockerfile`, `scripts/smoke_test.py` |
| Validate infrastructure | Bicep compiles; private networking is mandatory outside dev; acceptance and production pin the same model version | `infra/`, `scripts/check_networking_params.sh` |

The gate here uses the offline policy backend, which executes the prompt's
declared `RULE:` lines. It is not a model. That is what makes it free and
deterministic enough to run on every push. Real-model scoring starts in dev.

---

## 2. Dev

`cd.yml`, job `dev`. Runs automatically after merge.

1. **Build once.** The image is built and pushed to the registry, and every
   later stage deploys it by digest. A tag can be moved; a digest cannot.
2. **Deploy.** Bicep deploys the Foundry project, model, hosting and
   monitoring, and the image as a new Container Apps revision named after the
   run and commit.
3. **Smoke test.** Health, then `GET /version` must report the release id
   being promoted, then three clear-cut tickets through the real model. This
   catches "deployed, but the old version is still serving".
4. **Gate against the real model** at dev thresholds. The first time the real
   model is scored for this version.

Dev is public, scales to zero and holds only synthetic data.

---

## 3. Acceptance

`cd.yml`, job `acceptance`. Starts only after a **business approver** accepts
it in the `acceptance` environment.

1. **What-if.** Shows exactly what the infrastructure change will do before it does it.
2. **Deploy** the same image digest.
3. **Smoke test.**
4. **Evaluation gate, worst of three runs**, against the acceptance bar. The
   acceptance model version is pinned identical to production, so this is the
   result production will get.
5. **Performance check.** p95 latency, error rate, fail-safe rate and tokens
   per ticket against budgets (`scripts/perf_check.py`). A prompt change can
   pass the gate and still double the cost per ticket.

Acceptance is private: no public endpoints, production-like data. Its checks
therefore run on a runner inside the network (`PRIVATE_RUNNER_LABEL`).

---

## 4. Production

`cd.yml`, job `production`. Starts only after a **release approver** accepts it.

1. **Pre-flight gate** at the production bar on the exact manifest bytes.
2. **Deploy the new revision at 0% traffic.** The revision currently serving
   is named in the deployment, so customers stay on it.
3. **Smoke test the new revision directly** at its own address, before any
   customer request reaches it.
4. **Canary: 10% of traffic.**
5. **Watch.** Server-error rate on the canary revision only, and the
   continuous-evaluation quality score, for several minutes
   (`scripts/watch_canary.sh`). Error rate alone would miss a quality
   regression, which is the AI-specific failure.
6. **Widen to 100%.** Revisions older than the previous one are deactivated;
   the previous one stays available.
7. **Automatic rollback.** Any failure after the deploy puts all traffic back
   on the previous revision. A failure before the deploy leaves production
   untouched. Rollback is a traffic change, not a rebuild.
8. **Release record.** Release id, prompt hash, image digest, commit, old and
   new revision, outcome.

---

## 5. After release

- **Continuous evaluation** in Foundry scores a sample of live traffic.
- **Logs** carry the decision, release id, latency, tokens and whether the
  fail-safe fired. Ticket text is never logged.
- **Feedback loop.** When support staff correct a mis-routed ticket, those
  corrections become golden-set candidates (`scripts/harvest_feedback.py`).
  A reviewer accepts them; the gate then guards against that mistake forever.
  Real tickets go to the project's dataset storage, never into git.
- **Red teaming** weekly and before prompt changes (`redteam.yml`).

---

## What an AI engineer has to take care of

| Concern | Where it is handled here |
| --- | --- |
| Version everything that changes behaviour | `agent/agent.yaml`, release id with prompt SHA-256, image digest |
| A representative golden set | `evals/datasets/`, plus the feedback loop to keep it current |
| Metrics that cannot hide the critical failure | `critical_queue_recall`, measured on security tickets alone |
| Thresholds with reasons, under review | `evals/thresholds/*.yaml` |
| Model non-determinism | Temperature 0, worst-of-N gating in acceptance |
| Model version drift | `NoAutoUpgrade`, same version in acceptance and production, enforced in CI |
| Safe behaviour when the model misbehaves | Fail-safe to human review on a contract violation; 503 on outage |
| Latency and cost | `scripts/perf_check.py` budgets in acceptance |
| Safety and abuse | Content filters, red teaming, no tools for the agent |
| Quality in production, not just uptime | Canary watch on error rate and evaluation score |
| Data privacy | No ticket text in logs; real tickets never committed |
| Access and secrets | Separate environments, least privilege, OIDC, `disableLocalAuth` |
| Fast, rehearsed rollback | Multiple-revision mode, traffic-weight rollback |

---

## Limits, stated plainly

- Acceptance and production have not been deployed: they need platform-owned
  networking (subnets and private DNS zones) and a runner inside that network.
  Dev has been deployed.
- The golden set is 49 hand-written tickets, and the thresholds were first set
  against the offline policy backend. Both need re-deriving with real tickets
  and the real model's baseline.
- The continuous-evaluation check needs a continuous evaluation configured in
  the Foundry project and `APPLICATION_INSIGHTS_APP_ID` set; until then the
  canary watches error rate only.
