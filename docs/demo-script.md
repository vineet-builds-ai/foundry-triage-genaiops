# Demo script

Twelve minutes, aimed at a client evaluating whether you can be trusted to
deliver AI into their production estate.

**The through-line:** anyone can get a model working. The question is whether
you can stop a bad version reaching their customers. Everything else is
supporting evidence.

---

## Before you start

```bash
pip install -r requirements-dev.txt
make test        # 46 passing, under a second
make demo        # warm the caches, then clear the terminal
```

Have open, in tabs:

1. A terminal in the repository root
2. `agent/prompts/system.v3.md`
3. `demo/output/gate-report-regressed.md` rendered as Markdown
4. `infra/modules/rbac.bicep`

If you have a live Azure environment, add the GitHub Actions run and the
Foundry portal. **The demo does not need them.** Say so — "this runs on a
plane with no wifi" is itself a selling point for a delivery team.

---

## 0:00 — Frame it (1 min)

> "You already know AI works. What you do not know is whether we can stop a
> bad version reaching your customers. That is what I want to show you, and I
> am going to break it on purpose."

Describe the product in one sentence: it reads an inbound support ticket and
assigns a queue and a priority. Note that it is deliberately small — the
interesting part is everything around it.

Do not demo the agent working. Resist this. It is the least interesting thing
here and it spends your credibility on a party trick.

---

## 1:00 — The unit of release (2 min)

Open `agent/agent.yaml`.

> "This file is what gets promoted. Not a branch, not a container tag. It
> pins the prompt, the model deployment, the temperature and the tool
> surface."

```bash
python scripts/validate_manifest.py agent/agent.yaml
```

Point at the release id:

```
ticket-triage-v3-7bcccbd59556
```

> "That last part is the SHA-256 of the prompt file. When something goes
> wrong at two in the morning, your on-call engineer can hash the prompt and
> know, not guess, which version is running. And rolling back is changing a
> pointer, not rebuilding anything."

---

## 3:00 — The change (2 min)

Open `agent/prompts/system.v3.md` and scroll to the routing rules and the
fallback policy.

> "Someone picks this up to tidy. Three edits. Watch how reasonable each one
> sounds."

Read them out as a well-meaning engineer would justify them:

1. "`needs_human_review` — nothing downstream reads it, drop it from the contract."
2. "The security rule is a special case of the general rules. Fold it in."
3. "`triage-review` had become a dumping ground. Always give a ticket a real home."

> "No code changed. Every unit test still passes. In most organisations this
> gets approved in ninety seconds by someone who trusts the author."

---

## 5:00 — The cheap check (1 min)

```bash
python scripts/validate_manifest.py agent/agent.regressed.yaml
```

```
FAILED with 2 problem(s):
  - the prompt's output contract disagrees with the code schema: missing ['needs_human_review']
  - no fallback policy declared; without one the agent guesses a destination
    for tickets that match no rule instead of deferring to human triage
```

> "That is milliseconds, on every pull request. It already caught it. But a
> failing config check does not tell anyone what it would have *cost*. So
> let us measure."

---

## 6:00 — The gate (3 min)

**This is the moment. Do not rush it and do not talk over it.**

```bash
make demo
```

Let it run. When the comparison table lands, stop talking and let them read:

```
  metric                      bar       v3       v4   verdict
  schema_validity            1.00    1.000    0.000   BREACHED
  critical_queue_recall      1.00    1.000    0.000   BREACHED
  routing_accuracy           0.85    0.939    0.653   BREACHED
  priority_accuracy          0.85    0.939    0.775   BREACHED

  8 security tickets were sent somewhere else:
    SEC-001  security-incident -> billing
```

Then, pointing at that first line:

> "SEC-001 is a customer reporting a phishing campaign against their staff.
> It went to the billing queue. It would have sat there with a two-day
> service-level clock on it."

Pause. Then the mechanism:

> "Note `critical_queue_recall` separately from overall accuracy. If I had
> only gated the average, losing all eight security tickets still reads 0.84
> and sails through. The failure you most care about is exactly the one an
> average hides. So we gate the subset that matters at zero tolerance."

The pipeline exited non-zero. The version never reached acceptance.

---

## 9:00 — Governance (2 min)

Switch to `demo/output/gate-report-regressed.md`.

> "This is what gets posted on the pull request automatically. The author sees
> the number, the bar, the reason the bar exists, and every ticket that
> failed. Nobody has to go and ask a data scientist what happened."

Then `infra/modules/rbac.bicep`:

> "Three principals. Developers get data-plane access in dev and nowhere else
> — no standing access to acceptance or production. The CI/CD identity is
> scoped to the project, with a federated credential, so there is no client
> secret in this repository and nothing to rotate. The running workload can
> call the model and change nothing."

If they are technical, add one line:

> "`disableLocalAuth: true` on the Foundry resource. There are no API keys to
> leak, because none can be created."

If they ask about approvals:

> "Required reviewers on the production environment, configured in repository
> settings — not in the workflow file. A developer editing the pipeline cannot
> grant themselves the right to release."

---

## 11:00 — Close (1 min)

> "Three checks, cheapest first: a config check in milliseconds, an
> evaluation gate in seconds, an adversarial scan weekly. Separate Foundry
> projects per environment, no standing human access above dev, no secrets
> anywhere, and a release record that names the exact prompt bytes that
> shipped and who approved them.
>
> Built on Microsoft's own baseline reference architecture. The deviations are
> written down in the architecture doc, with reasons."

Then hand them the gaps before they look for them:

> "What this is not: it has never been deployed into a subscription, the
> golden set is forty-nine tickets I wrote by hand, and the thresholds are a
> first draft. On a real engagement the first week is sampling your actual
> tickets and having your support leads label them. That is the highest-value
> thing to do first, and it is not a thing I can do for you in a demo."

That last paragraph is the one that gets you hired. Everyone demos the happy
path. Naming your own limitations first reads as someone who has shipped
before.

---

## Questions you should expect

**"Would a real model behave the same way?"**
Honest answer: the offline backend is a deterministic interpreter of the
policy the prompt declares, not a model. A real model generalises past the
literal keywords, so it would probably catch some of those security tickets.
It would also be non-deterministic, which is why the gate uses a fixed dataset
and temperature zero. The mechanism is identical either way — point at
`FoundryBackend` and the one environment variable that switches it.

**"What if the gate blocks a release we need?"**
Thresholds are in version control with their rationale. Changing one is a pull
request that someone reviews. That is the control working, not failing — the
alternative is a bar anyone can move silently.

**"How long to stand this up for us?"**
Scaffolding, perhaps a week. The real work is the golden set and arguing out
the thresholds with the people who own the queues, which is weeks and needs
their people, not yours. Be straight about this; the honest answer is more
convincing than the fast one.

**"Does this work for RAG / multi-agent / our use case?"**
The promotion machinery is indifferent to what the agent does. What changes is
which evaluators gate: groundedness for RAG, tool-call accuracy and task
adherence for multi-step agents. Point at decision 4 in the architecture doc.

**"Why not Azure DevOps?"**
It maps across directly: environments with approvals and checks instead of
GitHub environments, and the same gate script. Offer to port it if their
estate is Azure DevOps — it is a small job.
