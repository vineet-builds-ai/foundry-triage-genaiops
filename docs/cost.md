# What this costs to run

**No figures from memory.** Azure prices vary by region, agreement and
commitment, and any number written here would be stale and probably wrong for
your tenant. What follows is the cost *model* — what drives spend and roughly
how the environments compare — which is the part that survives a price change.
Put real numbers against it with the
[Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/)
for your region and agreement.

---

## What drives the bill

Roughly in order of size for a workload like this.

**1. Model inference.** Usually the dominant line. Driven by tokens, not
requests: ticket text in, a small JSON object out. Triage is a favourable
shape — short inputs, very short outputs — so per-ticket cost is low, and
volume is what matters. Get a token count per ticket from the golden set, then
multiply by ticket volume.

**2. Provisioned throughput.** `modelCapacity` in the Bicep parameters is
thousands of tokens per minute, set to 10 / 20 / 60 across dev, acceptance and
production. On `GlobalStandard` this is a rate limit rather than a reservation,
so it shapes throttling rather than cost. Moving to a provisioned deployment
turns it into a committed monthly cost — larger, more predictable, usually
worth it only at sustained high volume.

**3. Hosting.** Container Apps bills on vCPU-seconds and memory while running.
Dev and acceptance scale to zero (`minReplicas: 0`), so they cost roughly
nothing when idle. Production holds `minReplicas: 2` for availability, which
is a floor you pay for continuously.

**4. Log Analytics ingestion and retention.** Easy to underestimate. Agent
traces and evaluation results are verbose. Ingestion volume and the retention
period (30 / 90 / 365 days here) both bill.

**5. Private endpoints.** A fixed hourly charge per endpoint plus data
processing. Small, but multiplied across environments and services.

**6. Evaluation.** The deterministic evaluators are free — they run in CI with
no model calls. Cloud evaluation with judge evaluators costs model inference
per judged row. A 49-row set judged on three metrics is three judge calls per
row.

**7. Red teaming.** Adversarial generation plus safety scoring. This is why it
runs weekly rather than on every merge.

---

## Relative shape

Not prices — proportions, to aim a conversation.

| Environment | Idle cost | Notes |
| --- | --- | --- |
| Dev | Near zero | Scales to zero, no private endpoints, 30-day retention |
| Acceptance | Low | Scales to zero, but private endpoints and 90-day retention bill continuously |
| Production | The bulk of it | Two always-on replicas, zone redundancy, 365-day retention, all real traffic |

CI is free: the gate runs offline on GitHub-hosted runners with no model
calls. That is a deliberate design property, not a happy accident — a gate
that costs money per run is a gate people learn to skip.

---

## Where the savings are

- **Scale to zero outside production.** Already configured.
- **Match retention to need.** 365 days in production is an audit decision; if
  90 suffices, that is a straightforward reduction in the second-largest line.
- **Right-size the judge model.** Judge evaluators do not need your most
  capable model. A smaller deployment for judging is usually indistinguishable
  in gate outcomes and materially cheaper.
- **Keep the golden set tight.** Bigger is not better. 49 well-chosen rows
  including hard cases beat 500 easy ones, and cost a tenth as much to judge.
- **Sample production evaluation.** Continuous evaluation scores a *sample* of
  live traffic. The sample rate is a direct cost lever.
- **Shared Foundry resource.** Three projects under one resource instead of
  three resources reduces quota fragmentation — at the governance cost
  described in `architecture.md`, decision 1.

---

## Cost governance that is not yet wired up

Named as a gap rather than implied as done:

- No budget or spend alert on the resource groups.
- No per-environment cost dashboard.
- The `costCentre` tag is applied to every resource, so chargeback reporting
  is possible, but nothing consumes it yet.

For a production engagement these are a day's work and belong in the first
iteration, not the fifth.
